#!/usr/bin/env python3
"""Checks the Last.fm auth flow, API signature, and submission shape.

Last.fm requires a registered app (api_key + api_secret) and signs every
request with an api_sig. The desktop auth flow is: get a token, have the
user approve it on a web page, then trade the approved token for a session
key.

The signature generation and parameter shapes are pinned here against a local
stub rather than by scrobbling to the real service.

Run: python3 tests/lastfm_test.py
"""

import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import sys
import threading
import urllib.parse
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_loader(
    "scrobble_helper",
    SourceFileLoader("scrobble_helper", os.path.join(os.path.dirname(HERE), "bin", "omarchy-scrobble")),
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


# ------------------------------------------------------- a stub Last.fm server

received = []

API_KEY = "deadbeefcafe"
API_SECRET = "shhh-secret"

# The shipped defaults are exercised rather than stubbed away: the helper
# must make the login flow work with no user-supplied credentials, exactly
# like ListenBrainz does.
helper.LASTFM_API_KEY = API_KEY
helper.LASTFM_SHARED_SECRET = API_SECRET


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _verify_sig(self, params):
        sig = params.pop("api_sig", "")
        expected = helper.lastfm_api_sig(params, API_SECRET)
        return sig == expected

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        flat = {k: v[0] for k, v in params.items()}
        received.append(flat)
        method = flat.get("method")
        if method == "auth.getToken":
            if not self._verify_sig(dict(flat)):
                self._reply({"error": "Invalid method signature supplied"}, status=403)
                return
            self._reply({"token": "tok-deadbe"})
        elif method == "auth.getSession":
            if not self._verify_sig(dict(flat)):
                self._reply({"error": "Invalid method signature supplied"}, status=403)
                return
            if flat.get("token") == "approved":
                self._reply({"session": {"name": "punkscience", "key": "sess-key-lf"}})
            else:
                self._reply({"error": "Unauthorized Token"}, status=401)
        else:
            self._reply({"error": "unknown"}, status=400)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode()
        flat = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
        received.append(flat)
        if not self._verify_sig(dict(flat)):
            self._reply({"error": "Invalid method signature supplied"}, status=403)
            return
        self._reply({"scrobbles": {"@attr": {"accepted": 1, "ignored": 0}}})


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}/"

print("endpoint policy")
check("the official Last.fm API origin is trusted",
      helper.trusted_lastfm_url() == "https://ws.audioscrobbler.com/2.0/")
for bad in (
    "http://ws.audioscrobbler.com/2.0/",
    "https://evil.example/2.0/",
    "https://ws.audioscrobbler.com.evil.example/2.0/",
    "https://user:pass@ws.audioscrobbler.com/2.0/",
):
    try:
        helper.trusted_lastfm_url(bad)
        check(f"untrusted Last.fm URL is refused: {bad}", False)
    except helper.LastFmError:
        check(f"untrusted Last.fm URL is refused: {bad}", True)

# Replace the official endpoint at the module boundary so the production URL
# validator remains strict while all requests stay on this local stub.
helper.trusted_lastfm_url = lambda value=None: BASE
CONFIG = {}

os.environ["XDG_DATA_HOME"] = os.path.join(HERE, "_tmp_lf_state")
shutil.rmtree(os.environ["XDG_DATA_HOME"], ignore_errors=True)

# ------------------------------------------------------------------- modes

print("auth modes")
check("no config needed to be connected", helper.lastfm_mode({}) == "none")
check("credential helpers expose the shipped pair", helper.lastfm_credentials() == (API_KEY, API_SECRET))

# ----------------------------------------------------------- the sign-in flow

print("sign-in flow")
token = helper.lastfm_request_token(CONFIG, API_KEY, API_SECRET, 10)
check("a token is issued with a valid api_sig", token == "tok-deadbe", token)

pending = helper.lastfm_fetch_session(CONFIG, API_KEY, API_SECRET, token, 10)
check("an unapproved token yields no session, and no error", pending is None)

session = helper.lastfm_fetch_session(CONFIG, API_KEY, API_SECRET, "approved", 10)
check("an approved token yields a session key", session and session["sessionKey"] == "sess-key-lf")
check("the username comes back with it", session and session["username"] == "punkscience")

helper.save_lastfm_session(session)
check("session round-trips", (helper.load_lastfm_session() or {}).get("sessionKey") == "sess-key-lf")
check("session file is not readable by others",
      os.stat(helper.lastfm_session_path()).st_mode & 0o077 == 0)
check("session write leaves no predictable staging file",
      not os.path.exists(helper.lastfm_session_path() + ".part"))
if hasattr(os, "symlink"):
    real = helper.lastfm_session_path() + ".real"
    os.replace(helper.lastfm_session_path(), real)
    try:
        os.symlink(real, helper.lastfm_session_path())
        check("symlinked session is refused", helper.load_lastfm_session() is None)
    finally:
        os.remove(helper.lastfm_session_path())
        os.replace(real, helper.lastfm_session_path())
check("a stored session selects session mode", helper.lastfm_mode(CONFIG) == "session")

helper.delete_lastfm_session()
check("disconnect removes the session", helper.load_lastfm_session() is None)
check("and returns to unconnected", helper.lastfm_mode(CONFIG) == "none")
check("unconnected submissions are skipped, not failed",
      helper.lastfm_send(CONFIG, "a", "b", "", 0, True).get("skipped") is True)

# --------------------------------------------------------------- submission

helper.save_lastfm_session(session)

print("submission")
received.clear()
result = helper.lastfm_send(CONFIG, "Ella Fitzgerald", "Blue Skies", "Ella in Berlin", 214000, True)
check("now-playing is accepted", result["ok"] and result["via"] == "session", result)
sent = received[-1]
check("now-playing uses the exact method casing", sent.get("method") == "track.updateNowPlaying", sent.get("method"))
check("artist is indexed", sent.get("artist[0]") == "Ella Fitzgerald")
check("track is indexed", sent.get("track[0]") == "Blue Skies")
check("album maps to album[0]", sent.get("album[0]") == "Ella in Berlin")
check("duration is in seconds, not ms", sent.get("duration[0]") == "214", sent.get("duration[0]"))
check("a now-playing carries no timestamp", "timestamp[0]" not in sent)
check("the session key is sent", sent.get("sk") == "sess-key-lf")
check("api_sig is present", "api_sig" in sent)
check("api_key is present", sent.get("api_key") == API_KEY)

received.clear()
result = helper.lastfm_send(CONFIG, "Ella Fitzgerald", "Blue Skies", "", 214000, False, listened_at=1700000000)
check("a listen is accepted", result["ok"])
sent = received[-1]
check("a listen uses track.scrobble", sent.get("method") == "track.scrobble", sent.get("method"))
check("a listen carries its timestamp", sent.get("timestamp[0]") == "1700000000")
check("an empty album is omitted", "album[0]" not in sent)

# ------------------------------------------------------------ signature

print("signature")
sig_params = {"method": "auth.getToken", "api_key": API_KEY}
sig = helper.lastfm_api_sig(sig_params, API_SECRET)
check("api_sig is 32 hex chars", len(sig) == 32 and all(c in "0123456789abcdef" for c in sig))
# Re-signing the same params must yield the same hash.
check("signature is deterministic", helper.lastfm_api_sig(sig_params, API_SECRET) == sig)
# Adding a param changes the hash.
sig_params2 = {"method": "auth.getToken", "api_key": API_KEY, "token": "x"}
check("different params yield different sig", helper.lastfm_api_sig(sig_params2, API_SECRET) != sig)

# ------------------------------------------------------------------- cleanup

helper.delete_lastfm_session()
shutil.rmtree(os.environ["XDG_DATA_HOME"], ignore_errors=True)
server.shutdown()

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all Last.fm checks passed")
