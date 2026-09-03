#!/usr/bin/env python3
"""Drives the relay client against a local mock relay.

Nothing here touches a public relay: publishing junk events to shared
infrastructure to test your own code is rude, and a local double exercises the
failure paths (rejection, dead host) that a real relay will not perform on cue.

Run: python3 tests/relay_test.py
"""

import base64
import hashlib
import importlib.util
import os
import socket
import struct
import sys
import threading
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


NSEC = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"
seckey = helper.bech32_to_bytes(NSEC, "nsec")

accepting = MockRelay(accept=True)
rejecting = MockRelay(accept=False, detail="blocked: pow required")

print("publishing")
event = helper.build_event(
    seckey, helper.KIND_USER_STATUS, [["d", "music"]], "Ella Fitzgerald - Blue Skies"
)
result = helper.publish([accepting.url], event, timeout=8)
check("relay accepts the event", result["ok"] and result["accepted"] == [accepting.url])

seen = accepting.received[0]
check("relay received an EVENT message", seen[0] == "EVENT")
check("the event arrived intact", seen[1]["id"] == event["id"])
check(
    "the signature verifies on the far side",
    helper.schnorr_verify(
        bytes.fromhex(seen[1]["id"]),
        bytes.fromhex(seen[1]["pubkey"]),
        bytes.fromhex(seen[1]["sig"]),
    ),
)
# The mock sends a NOTICE before the OK; a client that treats the first frame
# as the verdict would report success even when the relay refuses.
check("a NOTICE before the OK is not mistaken for the verdict", len(result["relays"]) == 1)

print("failure paths")
rejected = helper.publish([rejecting.url], event, timeout=8)
check("a rejection is reported as a failure", rejected["ok"] is False)
check(
    "the relay's reason is preserved",
    rejected["relays"][0]["detail"] == "blocked: pow required",
    rejected["relays"][0]["detail"],
)

mixed = helper.publish([accepting.url, "ws://127.0.0.1:1"], event, timeout=5)
check("one dead relay does not sink the others", mixed["ok"] and len(mixed["accepted"]) == 1)
check("every relay is accounted for in the report", len(mixed["relays"]) == 2)

print("framing")
# Payload lengths of 126+ and 65536+ switch the frame header format; a bug
# there only shows up on long track titles.
large = helper.build_event(seckey, 1, [], "x" * 400)
check("payloads over 125 bytes are framed correctly", helper.publish([accepting.url], large, timeout=8)["ok"])

huge = helper.build_event(seckey, 1, [], "y" * 70000)
check("payloads over 65535 bytes are framed correctly", helper.publish([accepting.url], huge, timeout=8)["ok"])

unicode_event = helper.build_event(seckey, 1, [], "Björk – Jóga ♪")
helper.publish([accepting.url], unicode_event, timeout=8)
check(
    "unicode survives masking and framing",
    accepting.received[-1][1]["content"] == "Björk – Jóga ♪",
    accepting.received[-1][1]["content"],
)

print("frame limits")

def oversized_relay():
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]

    def serve():
        conn, _ = sock.accept()
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += conn.recv(4096)
        key = ""
        for line in buf.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        conn.sendall((
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode())
        payload = b"x" * (helper.MAX_WS_PAYLOAD_BYTES + 1)
        head = bytearray([0x81])  # fin=1, opcode=text
        head.append(127)
        head += struct.pack("!Q", len(payload))
        conn.sendall(bytes(head) + payload)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"ws://127.0.0.1:{port}/"

url = oversized_relay()
try:
    with helper.WebSocket(url, timeout=5) as ws:
        ws.recv_json()
    check("oversized websocket frame is rejected", False)
except helper.WebSocketError as e:
    check("oversized websocket frame is rejected", "exceeds" in str(e).lower(), e)

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all relay checks passed")
