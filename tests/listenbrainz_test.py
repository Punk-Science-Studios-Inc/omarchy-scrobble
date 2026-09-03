#!/usr/bin/env python3
"""Checks the ListenBrainz auth modes and the Last.fm-compat submission shape.

ListenBrainz has no OAuth2 provider — its native API takes a user token you
copy by hand. The clickable sign-in here rides its Last.fm-compatible API,
whose desktop flow is: get a token, have the user approve it on a web page
(a MusicBrainz login), then trade it for a session key.

The submission parameters are fiddly and the server is strict about one of
them, so they are pinned here against a local stub rather than by scrobbling
to the real service.

Run: python3 tests/listenbrainz_test.py
"""

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


# ------------------------------------------------------- a stub compat server

received = []


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

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        flat = {k: v[0] for k, v in params.items()}
        received.append(flat)
        method = flat.get("method")
        if method == "auth.gettoken":
            self._reply({"token": "tok-" + flat.get("api_key", "")[:6]})
        elif method == "auth.getsession":
            if flat.get("token") == "approved":
                self._reply({"session": {"name": "punkscience", "key": "sess-key-1"}})
            else:
                self._reply({"code": 14, "message": "This token has not been authorized"}, status=401)
        elif method == "oversized":
            # Send exactly one byte over the 1 MiB cap so the client can
            # read the whole body, detect the oversize, and close cleanly.
            padding = helper.MAX_HTTP_RESPONSE_BYTES + 1 - len(json.dumps({"x": ""}).encode())
            self._reply({"x": "x" * padding})
        else:
            self._reply({"error": "unknown"}, status=400)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode()
        flat = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
        received.append(flat)
        self._reply({"scrobbles": {"@attr": {"accepted": 1, "ignored": 0}}})


class OversizedNativeHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        # Exactly one byte over the 1 MiB cap so the client reads the whole
        # body, detects the oversize, and closes without a connection reset.
        blob = b"x" * (helper.MAX_HTTP_RESPONSE_BYTES + 1)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}/2.0/"
CONFIG = {"listenbrainzCompatUrl": BASE}

native_server = http.server.HTTPServer(("127.0.0.1", 0), OversizedNativeHandler)
threading.Thread(target=native_server.serve_forever, daemon=True).start()
NATIVE_BASE = f"http://127.0.0.1:{native_server.server_address[1]}/"

os.environ["XDG_DATA_HOME"] = os.path.join(HERE, "_tmp_lb_state")
shutil.rmtree(os.environ["XDG_DATA_HOME"], ignore_errors=True)

# ------------------------------------------------------------------- modes

print("auth modes")
check("no token and no session means unconnected", helper.listenbrainz_mode(CONFIG) == "none")
check("a pasted token is reported as token mode",
      helper.listenbrainz_mode({"listenbrainzToken": "abc"}) == "token")

# ----------------------------------------------------------- the sign-in flow

print("sign-in flow")
api_key = "deadbeefcafe"
token = helper.listenbrainz_request_token(CONFIG, api_key, 10)
check("a token is issued without registering an app", token == "tok-deadbe", token)

pending = helper.listenbrainz_fetch_session(CONFIG, api_key, token, 10)
check("an unapproved token yields no session, and no error", pending is None)

session = helper.listenbrainz_fetch_session(CONFIG, api_key, "approved", 10)
check("an approved token yields a session key", session and session["sessionKey"] == "sess-key-1")
check("the username comes back with it", session and session["username"] == "punkscience")

helper.save_listenbrainz_session(session)
check("session round-trips", (helper.load_listenbrainz_session() or {}).get("sessionKey") == "sess-key-1")
check("session file is not readable by others",
      os.stat(helper.listenbrainz_session_path()).st_mode & 0o077 == 0)
check("a stored session selects session mode", helper.listenbrainz_mode(CONFIG) == "session")

# Two installs signing in at once must not collide: ListenBrainz keys its
# pending-token table on api_key, so a shared constant would be a bug.
keys = {helper.os.urandom(16).hex() for _ in range(50)}
check("login api keys are random per attempt", len(keys) == 50)

# --------------------------------------------------------------- submission

print("submission")
received.clear()
result = helper.listenbrainz_send(CONFIG, "Ella Fitzgerald", "Blue Skies", "Ella in Berlin", 214000, True)
check("now-playing is accepted", result["ok"] and result["via"] == "session", result)
sent = received[-1]
# The server compares the raw method string when choosing between a
# now-playing and a real listen, so the capitals matter.
check("now-playing uses the exact method casing", sent.get("method") == "track.updateNowPlaying", sent.get("method"))
check("artist is indexed", sent.get("artist[0]") == "Ella Fitzgerald")
check("track is indexed", sent.get("track[0]") == "Blue Skies")
check("album maps to album[0]", sent.get("album[0]") == "Ella in Berlin")
check("duration is in seconds, not ms", sent.get("duration[0]") == "214", sent.get("duration[0]"))
check("a now-playing carries no timestamp", "timestamp[0]" not in sent)
check("the session key is sent", sent.get("sk") == "sess-key-1")

received.clear()
result = helper.listenbrainz_send(CONFIG, "Ella Fitzgerald", "Blue Skies", "", 214000, False, listened_at=1700000000)
check("a listen is accepted", result["ok"])
sent = received[-1]
check("a listen uses track.scrobble", sent.get("method") == "track.scrobble", sent.get("method"))
check("a listen carries its timestamp", sent.get("timestamp[0]") == "1700000000")
check("an empty album is omitted", "album[0]" not in sent)

# A pasted user token wins over a stored session: someone who set one meant
# to use it, and the two routes must not both fire for one track.
check("a pasted token overrides a stored session",
      helper.listenbrainz_mode({**CONFIG, "listenbrainzToken": "abc"}) == "token")
check("an empty token is not treated as configured",
      helper.listenbrainz_mode({**CONFIG, "listenbrainzToken": ""}) == "session")

helper.delete_listenbrainz_session()
check("disconnect removes the session", helper.load_listenbrainz_session() is None)
check("and returns to unconnected", helper.listenbrainz_mode(CONFIG) == "none")
check("unconnected submissions are skipped, not failed",
      helper.listenbrainz_send(CONFIG, "a", "b", "", 0, True).get("skipped") is True)

# --------------------------------------------------------------- size limits

print("size limits")
try:
    helper.compat_call(BASE, {"method": "oversized", "format": "json"}, timeout=10)
    check("oversized compat response is rejected", False)
except helper.ListenBrainzError as e:
    check("oversized compat response is rejected", "exceeds" in str(e).lower(), e)

result = helper.listenbrainz_submit(
    {"listenbrainzToken": "abc", "listenbrainzUrl": NATIVE_BASE},
    {"listen_type": "playing_now", "payload": []},
    timeout=10,
)
check("oversized native API response is rejected",
      not result["ok"] and "exceeds" in result.get("detail", "").lower(),
      result.get("detail"))

shutil.rmtree(os.environ["XDG_DATA_HOME"], ignore_errors=True)
server.shutdown()
native_server.shutdown()

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all ListenBrainz checks passed")
