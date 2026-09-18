#!/usr/bin/env python3
"""Pins the marketplace security-review blockers from issue #6347.

Each block maps to one reviewer finding:

1. A fixed trusted interpreter runs the helper (checked against Service.qml).
2. config.json is read through a retained no-follow descriptor with strict
   size/type/owner/link checks, never a pathname open followed by a stat.
3. Secret session files are written with randomized exclusive staging and
   fsync, not a predictable ``.part`` path, and read back the same safe way.
4. Credentials only ever go to a first-party ListenBrainz HTTPS origin.
5. Relay handshake headers are capped, so a hostile relay cannot exhaust
   memory before the frame limits apply.
6. Every relay-supplied event is authenticated (id + Schnorr signature) and
   matched against the requested filter before it is trusted.
7. Profile-picture fetches are confined to public HTTPS addresses, pinned
   across redirects, so a forged profile cannot reach loopback or private
   services.

POSIX-only assertions (permission bits, symlinks, fifos) are skipped on
platforms that lack them rather than failing, so the suite is green on the
Linux target and does not produce false failures elsewhere.

Run: python3 tests/security_test.py
"""

import importlib.util
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
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


print("relay handshake cap")


def flooding_handshake_relay():
    """A relay that sends a 101 status then endless header bytes."""
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]

    def serve():
        conn, _ = sock.accept()
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nX-Filler: "
            + b"a" * (helper.MAX_WS_HANDSHAKE_BYTES + 4096)
        )
        time.sleep(2)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"ws://127.0.0.1:{port}/"


try:
    with helper.WebSocket(flooding_handshake_relay(), timeout=5):
        pass
    check("an oversized relay handshake is refused", False, "no error raised")
except helper.WebSocketError as error:
    check("an oversized relay handshake is refused", "handshake" in str(error), error)


print("relay event authentication")

NSEC = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"
seckey = helper.bech32_to_bytes(NSEC, "nsec")
author = helper.public_key_from_secret(seckey).hex()
event = helper.build_event(
    seckey, helper.KIND_METADATA, [], json.dumps({"name": "Darryl", "picture": "https://8.8.8.8/a.png"})
)
matching = {"kinds": [helper.KIND_METADATA], "authors": [author]}

check("a well-formed event with a matching filter verifies", helper.verify_event(event, matching))

tampered = dict(event)
tampered["content"] = json.dumps({"name": "Attacker", "picture": "https://127.0.0.1/x"})
check("a tampered event (id no longer matches) is rejected", not helper.verify_event(tampered, matching))

bad_sig = dict(event)
bad_sig["sig"] = "00" * 64
check("a tampered signature is rejected", not helper.verify_event(bad_sig, matching))

other = helper.build_event(bytes.fromhex("11" * 32), helper.KIND_METADATA, [], "{}")
check("a validly signed event from another key fails the author filter",
      not helper.verify_event(other, matching))
check("that other event verifies against its own author",
      helper.verify_event(other, {"authors": [other["pubkey"]]}))
check("a kind mismatch fails the filter",
      not helper.verify_event(event, {"kinds": [helper.KIND_USER_STATUS]}))
check("a malformed event is rejected, not raised",
      not helper.verify_event(["not", "a", "dict"], matching)
      and not helper.verify_event({"id": "zz"}, matching))


print("avatar fetch confinement")

for label, bad in [
    ("plain http", "http://8.8.8.8/a.png"),
    ("loopback v4", "https://127.0.0.1/a.png"),
    ("loopback v6", "https://[::1]/a.png"),
    ("private v4", "https://10.0.0.1/a.png"),
    ("link-local metadata", "https://169.254.169.254/latest/meta-data"),
    ("unspecified", "https://0.0.0.0/a.png"),
    ("embedded credentials", "https://user:pass@8.8.8.8/a.png"),
    ("a non-443 port", "https://8.8.8.8:8443/a.png"),
]:
    try:
        helper.validate_avatar_url(bad)
        check(f"avatar fetch refuses {label}", False, "no error raised")
    except ValueError:
        check(f"avatar fetch refuses {label}", True)

check("a public HTTPS avatar is accepted",
      helper.validate_avatar_url("https://8.8.8.8/a.png") == "8.8.8.8")

# The connection must dial the validated address, not re-resolve the host and
# reopen the DNS-rebinding window.
pinned = helper._pinned_connection_class("203.0.113.7")
connection = pinned("public.example")
dialed = {}
real_create_connection = helper.socket.create_connection


def stop_before_tls(target, *args, **kwargs):
    dialed["target"] = target
    raise OSError("stop before the TLS handshake")


helper.socket.create_connection = stop_before_tls
try:
    connection.connect()
except OSError:
    pass
finally:
    helper.socket.create_connection = real_create_connection
check("the avatar connection is pinned to the validated address",
      dialed.get("target") == ("203.0.113.7", 443), dialed)

# A handler that silently follows a redirect would bypass the per-hop check.
check("automatic redirects are refused",
      helper._NoRedirectHandler().redirect_request(
          None, None, 302, "Found", {}, "https://127.0.0.1/"
      ) is None)


print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all security checks passed")
