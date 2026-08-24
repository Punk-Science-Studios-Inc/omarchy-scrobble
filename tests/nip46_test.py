#!/usr/bin/env python3
"""Drives the whole NIP-46 remote-signing path against a mock phone signer.

The QR login is the one flow that is genuinely hard to check by hand — it
needs a relay, a phone, and a track playing. So the phone is simulated here:
a thread holding the "user" key that answers `connect`, `get_public_key` and
`sign_event` exactly as Amber would, over a real WebSocket to a real (if
in-memory) relay.

Both encryption schemes are exercised, because which one a signer picks is
not up to us.

Run: python3 tests/nip46_test.py
"""

import importlib.util
import json
import os
import sys
import threading
import time
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

spec = importlib.util.spec_from_loader(
    "scrobble_helper",
    SourceFileLoader("scrobble_helper", os.path.join(os.path.dirname(HERE), "bin", "omarchy-scrobble")),
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

from mock_relay import MockRelay  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


class MockSigner(threading.Thread):
    """Stands in for Amber: holds the user key, answers NIP-46 requests."""

    daemon = True

    def __init__(self, relay_url, user_secret, scheme):
        super().__init__()
        self.relay_url = relay_url
        self.user_secret = user_secret
        self.user_pubkey = helper.public_key_from_secret(user_secret)
        # A signer's transport key is separate from the user's identity key.
        self.signer_secret = os.urandom(32)
        self.signer_pubkey = helper.public_key_from_secret(self.signer_secret)
        self.scheme = scheme
        self.client_pubkey = None
        self.stop = threading.Event()
        self.seen = []

    def encrypt_to(self, message, peer):
        if self.scheme == "nip04":
            return helper.nip04_encrypt(message, self.signer_secret, peer)
        return helper.nip44_encrypt(
            message, helper.nip44_conversation_key(self.signer_secret, peer)
        )

    def decrypt_from(self, content, peer):
        if helper.is_nip04_payload(content):
            return helper.nip04_decrypt(content, self.signer_secret, peer)
        return helper.nip44_decrypt(
            content, helper.nip44_conversation_key(self.signer_secret, peer)
        )

    def reply(self, ws, peer, body):
        event = helper.build_event(
            self.signer_secret,
            helper.KIND_NIP46,
            [["p", peer.hex()]],
            self.encrypt_to(json.dumps(body), peer),
        )
        ws.send_json(["EVENT", event])

    def pair(self, client_pubkey, secret):
        """What scanning the QR does: send the ack the client is waiting for."""
        self.client_pubkey = client_pubkey
        with helper.WebSocket(self.relay_url, 10) as ws:
            self.reply(ws, client_pubkey, {"id": os.urandom(4).hex(), "result": secret})
            time.sleep(0.3)

    def run(self):
        with helper.WebSocket(self.relay_url, 60) as ws:
            sub = "signer"
            ws.send_json(["REQ", sub, {"kinds": [helper.KIND_NIP46], "#p": [self.signer_pubkey.hex()]}])
            ws.extend_deadline(60)
            while not self.stop.is_set():
                try:
                    message = ws.recv_json()
                except Exception:
                    return
                if not isinstance(message, list) or len(message) < 3 or message[0] != "EVENT":
                    continue
                event = message[2]
                peer = bytes.fromhex(event["pubkey"])
                try:
                    body = json.loads(self.decrypt_from(event["content"], peer))
                except Exception:
                    continue
                self.seen.append(body)
                method, params = body.get("method"), body.get("params") or []

                if method == "connect":
                    self.reply(ws, peer, {"id": body["id"], "result": "ack"})
                elif method == "get_public_key":
                    self.reply(ws, peer, {"id": body["id"], "result": self.user_pubkey.hex()})
                elif method == "sign_event":
                    unsigned = json.loads(params[0])
                    signed = helper.build_event(
                        self.user_secret,
                        unsigned["kind"],
                        unsigned["tags"],
                        unsigned["content"],
                        unsigned.get("created_at"),
                    )
                    self.reply(ws, peer, {"id": body["id"], "result": json.dumps(signed)})
                else:
                    self.reply(ws, peer, {"id": body["id"], "error": f"unsupported: {method}"})


def run_scheme(scheme):
    print(f"pairing and signing over {scheme}")
    relay = MockRelay()
    user_secret = os.urandom(32)
    signer = MockSigner(relay.url, user_secret, scheme)
    signer.start()
    time.sleep(0.3)

    # -- the client half of the QR flow
    client_secret = os.urandom(32)
    client_pubkey = helper.public_key_from_secret(client_secret)
    secret = os.urandom(16).hex()
    uri = helper.build_nostrconnect_uri(client_pubkey, [relay.url], secret, "Omarchy Scrobble")
    check(f"[{scheme}] nostrconnect URI carries the client key", client_pubkey.hex() in uri)

    paired = {}

    def wait():
        paired.update(helper.await_pairing(client_secret, [relay.url], secret, 20.0) or {})

    waiter = threading.Thread(target=wait, daemon=True)
    waiter.start()
    time.sleep(0.5)
    signer.pair(client_pubkey, secret)   # the phone scans
    waiter.join(20)

    check(f"[{scheme}] pairing completed", bool(paired), paired)
    if not paired:
        signer.stop.set()
        return
    check(f"[{scheme}] learned the signer's key", paired["signerPubkey"] == signer.signer_pubkey.hex())
    check(f"[{scheme}] detected the encryption scheme", paired["encryption"] == scheme, paired["encryption"])

    session = {
        "clientSecret": client_secret.hex(),
        "signerPubkey": paired["signerPubkey"],
        "userPubkey": "",
        "relays": [relay.url],
        "encryption": paired["encryption"],
    }
    remote = helper.RemoteSigner(session)

    user_hex = remote.request("get_public_key", [], timeout=20)
    check(f"[{scheme}] get_public_key returns the user's key", user_hex == signer.user_pubkey.hex(), user_hex)
    session["userPubkey"] = user_hex

    # -- the thing the plugin actually does every track
    remote = helper.RemoteSigner(session)
    event = remote.sign(
        helper.KIND_USER_STATUS,
        [["d", "music"], ["r", "https://example.test/x"]],
        "Ella Fitzgerald - Blue Skies",
    )
    check(f"[{scheme}] signed event is attributed to the user", event["pubkey"] == signer.user_pubkey.hex())
    check(f"[{scheme}] signed event kind is 30315", event["kind"] == 30315)
    check(f"[{scheme}] signed event content survived", event["content"] == "Ella Fitzgerald - Blue Skies")
    check(
        f"[{scheme}] signature verifies against the user's key",
        helper.schnorr_verify(
            bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]), bytes.fromhex(event["sig"])
        ),
    )
    # The whole point of remote signing: this process never held the user key.
    check(
        f"[{scheme}] the client key is not the signing key",
        event["pubkey"] != client_pubkey.hex(),
    )

    published = helper.publish([relay.url], event, timeout=10)
    check(f"[{scheme}] the signed event is accepted by a relay", published["ok"])

    # -- the signer refusing must surface, not be swallowed
    try:
        remote.request("nip04_encrypt", ["x"], timeout=20)
        check(f"[{scheme}] a signer error is raised", False)
    except helper.SignerError:
        check(f"[{scheme}] a signer error is raised", True)

    signer.stop.set()


for scheme in ("nip44", "nip04"):
    run_scheme(scheme)

print("session storage")
os.environ["XDG_DATA_HOME"] = os.path.join(HERE, "_tmp_state")
path = helper.session_path()
helper.save_session({"clientSecret": "aa" * 32, "signerPubkey": "bb" * 32, "userPubkey": "cc" * 32})
check("session round-trips", helper.load_session()["signerPubkey"] == "bb" * 32)
check("session file is not readable by others", os.stat(path).st_mode & 0o077 == 0, oct(os.stat(path).st_mode))
check("a saved session selects remote signing", helper.signing_mode({}) == "remote")
check("logout removes it", helper.delete_session() and helper.load_session() is None)
check("no session and no key means unconfigured", helper.signing_mode({}) == "none")
check("a local nsec is used when no phone is paired",
      helper.signing_mode({"nsec": "11" * 32}) == "local")

import shutil  # noqa: E402
shutil.rmtree(os.path.join(HERE, "_tmp_state"), ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all NIP-46 checks passed")
