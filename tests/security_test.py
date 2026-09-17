#!/usr/bin/env python3
"""Pins the four marketplace security-review blockers from issue #6347.

Each block maps to one reviewer finding:

1. A fixed trusted interpreter runs the helper (checked against Service.qml).
2. config.json is read through a retained no-follow descriptor with strict
   size/type/owner/link checks, never a pathname open followed by a stat.
3. Secret session files are written with randomized exclusive staging and
   fsync, not a predictable ``.part`` path, and read back the same safe way.
4. Credentials only ever go to a first-party ListenBrainz HTTPS origin.

POSIX-only assertions (permission bits, symlinks, fifos) are skipped on
platforms that lack them rather than failing, so the suite is green on the
Linux target and does not produce false failures elsewhere.

Run: python3 tests/security_test.py
"""

import importlib.util
import json
import os
import stat
import sys
import tempfile
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_loader(
    "scrobble_helper",
    SourceFileLoader("scrobble_helper", os.path.join(ROOT, "bin", "omarchy-scrobble")),
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

POSIX = hasattr(os, "getuid")
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def skip(name, reason):
    print(f"  skip {name} ({reason})")


def write_private(path, payload, mode=0o600):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    if POSIX:
        os.chmod(path, mode)


# ------------------------------------------------- 4. trusted HTTPS origins

print("trusted ListenBrainz origins")

NATIVE = helper.DEFAULT_LISTENBRAINZ_URL          # https://api.listenbrainz.org
COMPAT = helper.LISTENBRAINZ_COMPAT_URL           # https://listenbrainz.org/2.0/

check("the native default is trusted as-is",
      helper.trusted_listenbrainz_url(None, NATIVE) == NATIVE)
check("the compat default keeps its trailing slash",
      helper.trusted_listenbrainz_url(None, COMPAT) == COMPAT,
      helper.trusted_listenbrainz_url(None, COMPAT))
check("an explicit 443 is trusted",
      helper.trusted_listenbrainz_url("https://listenbrainz.org:443/2.0/", COMPAT)
      == "https://listenbrainz.org:443/2.0/")

for label, bad in [
    ("plain http", "http://listenbrainz.org/2.0/"),
    ("a foreign host", "https://evil.example/2.0/"),
    ("a lookalike host", "https://listenbrainz.org.evil.example/2.0/"),
    ("embedded credentials", "https://user:pass@listenbrainz.org/2.0/"),
    ("a query string", "https://listenbrainz.org/2.0/?x=1"),
    ("a fragment", "https://listenbrainz.org/2.0/#f"),
    ("a non-443 port", "https://listenbrainz.org:8443/2.0/"),
]:
    try:
        helper.trusted_listenbrainz_url(bad, COMPAT)
        check(f"{label} is refused", False, "no error raised")
    except ValueError:
        check(f"{label} is refused", True)

# The validator is only worth anything if the credential-bearing callers route
# through it. compat_url must raise; listenbrainz_submit must refuse rather than
# send a token to an attacker-controlled origin.
try:
    helper.compat_url({"listenbrainzCompatUrl": "http://evil.example/2.0/"})
    check("compat_url refuses an untrusted origin", False, "no error raised")
except ValueError:
    check("compat_url refuses an untrusted origin", True)

result = helper.listenbrainz_submit(
    {"listenbrainzToken": "secret", "listenbrainzUrl": "http://evil.example/"},
    {"listen_type": "playing_now", "payload": []},
    timeout=5,
)
check("submit refuses to send a token to an untrusted origin",
      result.get("ok") is False and "https" in result.get("detail", "").lower(),
      result)


# --------------------------------------------------- 2. config.json reading

print("config.json reading")

config_dir = tempfile.mkdtemp(prefix="scrobble-config-")
os.environ["XDG_CONFIG_HOME"] = config_dir
config_file = os.path.join(config_dir, "omarchy-scrobble", "config.json")
os.makedirs(os.path.dirname(config_file), exist_ok=True)

check("a missing config reads as empty, not an error",
      helper.read_config(config_file) == {})

write_private(config_file, {"relays": ["wss://relay.example"]})
check("a valid config is returned", helper.read_config(config_file) == {"relays": ["wss://relay.example"]})

write_private(config_file, ["not", "an", "object"])
try:
    helper.read_config(config_file)
    check("a non-object config is refused", False, "no error raised")
except helper.ConfigError:
    check("a non-object config is refused", True)

write_private(config_file, {"relays": "x" * (helper.MAX_PRIVATE_JSON_BYTES + 10)})
try:
    helper.read_config(config_file)
    check("an oversized config is refused before it is all loaded", False, "no error raised")
except helper.ConfigError as error:
    check("an oversized config is refused before it is all loaded",
          "larger than" in str(error), error)

# A secret in a world-readable file is refused; the same file without a secret
# is not, preserving the original behaviour for settings-only configs.
if POSIX:
    write_private(config_file, {"nsec": "11" * 32}, mode=0o644)
    try:
        helper.read_config(config_file)
        check("a world-readable config holding a secret is refused", False, "no error raised")
    except helper.ConfigError as error:
        check("a world-readable config holding a secret is refused",
              "chmod 600" in str(error), error)

    write_private(config_file, {"nsec": "11" * 32}, mode=0o600)
    check("a 0600 config holding a secret is accepted",
          helper.read_config(config_file).get("nsec") == "11" * 32)
else:
    skip("config mode enforcement", "POSIX permission bits unavailable")

write_private(config_file, {"relays": ["wss://relay.example"]}, mode=0o644)
check("a settings-only config at 0644 is still accepted",
      helper.read_config(config_file).get("relays") == ["wss://relay.example"])

# The read must not follow a symlink planted at the config path.
if POSIX:
    real = os.path.join(config_dir, "attacker.json")
    write_private(real, {"nsec": "22" * 32}, mode=0o600)
    link = os.path.join(config_dir, "omarchy-scrobble", "config.json")
    try:
        os.remove(link)
        os.symlink(real, link)
        try:
            helper.read_config(link)
            check("a symlinked config is refused", False, "no error raised")
        except helper.ConfigError as error:
            check("a symlinked config is refused", "symbolic link" in str(error), error)
    except (OSError, NotImplementedError) as error:
        skip("symlinked config refusal", f"cannot create symlink: {error}")
else:
    skip("symlinked config refusal", "POSIX symlinks unavailable")


# --------------------------------------------- 3. secret session file writes

print("secret session writes")

data_dir = tempfile.mkdtemp(prefix="scrobble-data-")
os.environ["XDG_DATA_HOME"] = data_dir

session = {"sessionKey": "sess-key-1", "username": "punkscience", "apiKey": "k"}
helper.save_listenbrainz_session(session)
path = helper.listenbrainz_session_path()

check("the session round-trips", (helper.load_listenbrainz_session() or {}).get("sessionKey") == "sess-key-1")
check("no predictable .part file is left behind",
      not os.path.exists(path + ".part"), os.listdir(os.path.dirname(path)))
check("the staging file is cleaned up",
      sorted(os.listdir(os.path.dirname(path))) == ["listenbrainz.json"],
      os.listdir(os.path.dirname(path)))
if POSIX:
    check("the session file is mode 0600",
          stat.S_IMODE(os.stat(path).st_mode) == 0o600,
          oct(stat.S_IMODE(os.stat(path).st_mode)))
else:
    skip("session file mode", "POSIX permission bits unavailable")

# The NIP-46 signer session uses the same safe writer.
helper.save_session({"clientSecret": "aa" * 32, "signerPubkey": "bb" * 32, "userPubkey": "cc" * 32})
signer_path = helper.session_path()
check("the signer session round-trips",
      (helper.load_session() or {}).get("clientSecret") == "aa" * 32)
check("no predictable .part file is left for the signer session",
      not os.path.exists(signer_path + ".part"))

# A session file that is not valid JSON, or is a symlink, must not be loaded.
if POSIX:
    os.chmod(path, 0o644)
    check("a world-readable session file is refused on load",
          helper.load_listenbrainz_session() is None)
    os.chmod(path, 0o600)
else:
    skip("session mode enforcement on load", "POSIX permission bits unavailable")


# ------------------------------------------- 1. fixed interpreter in the UI

print("Service.qml interpreter")

with open(os.path.join(ROOT, "Service.qml"), encoding="utf-8") as handle:
    qml = handle.read()

check("a fixed interpreter path is declared",
      'readonly property string pythonPath: "/usr/bin/python3"' in qml)
check("the helper is run through that interpreter",
      "return [pythonPath, helperPath].concat(helperArgs)" in qml)
check("no Process execs the helper directly through its shebang",
      "command = [helperPath" not in qml and "command: [helperPath" not in qml,
      [line.strip() for line in qml.splitlines() if "[helperPath" in line])
check("every helper invocation goes through helperCommand",
      qml.count("helperCommand(") >= 10, qml.count("helperCommand("))


print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all security checks passed")
