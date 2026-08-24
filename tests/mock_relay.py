"""A small in-memory Nostr relay, for tests only.

Enough of the protocol to exercise the client: EVENT with an OK verdict, REQ
with filter matching, stored-then-EOSE replay, and live broadcast to open
subscriptions. That last part is what makes the NIP-46 handshake testable
without a phone in the loop.
"""

import base64
import hashlib
import json
import socket
import struct
import threading


def _frame(payload, opcode=0x1):
    data = payload.encode()
    head = bytearray([0x80 | opcode])
    n = len(data)
    if n < 126:
        head.append(n)
    elif n < 65536:
        head.append(126)
        head += struct.pack("!H", n)
    else:
        head.append(127)
        head += struct.pack("!Q", n)
    return bytes(head) + data


def matches(filters, event):
    if "kinds" in filters and event.get("kind") not in filters["kinds"]:
        return False
    if "authors" in filters and event.get("pubkey") not in filters["authors"]:
        return False
    if "ids" in filters and event.get("id") not in filters["ids"]:
        return False
    for key, wanted in filters.items():
        if not key.startswith("#") or len(key) != 2:
            continue
        letter = key[1]
        values = [t[1] for t in event.get("tags", []) if len(t) >= 2 and t[0] == letter]
        if not any(v in wanted for v in values):
            return False
    if "since" in filters and event.get("created_at", 0) < filters["since"]:
        return False
    if "until" in filters and event.get("created_at", 0) > filters["until"]:
        return False
    return True


class MockRelay:
    def __init__(self, accept=True, detail=""):
        self.accept, self.detail = accept, detail
        self.received = []
        self.events = []
        self._subscriptions = []   # (conn, subscription_id, filters)
        self._lock = threading.Lock()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.url = f"ws://127.0.0.1:{self.sock.getsockname()[1]}"
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _send(self, conn, message):
        try:
            conn.sendall(_frame(json.dumps(message)))
        except OSError:
            pass

    def _store_and_broadcast(self, event):
        with self._lock:
            self.events.append(event)
            targets = [
                (conn, sub) for conn, sub, filters in self._subscriptions if matches(filters, event)
            ]
        for conn, sub in targets:
            self._send(conn, ["EVENT", sub, event])

    def _client(self, conn):
        conn.settimeout(30)
        buf = b""
        try:
            while b"\r\n\r\n" not in buf:
                buf += conn.recv(4096)
            head, buf = buf.split(b"\r\n\r\n", 1)
            key = ""
            for line in head.decode("latin-1").split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode()
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )

            def need(n):
                nonlocal buf
                while len(buf) < n:
                    chunk = conn.recv(4096)
                    if not chunk:
                        raise ConnectionError
                    buf += chunk
                out, buf = buf[:n], buf[n:]
                return out

            while True:
                b0, b1 = need(2)
                opcode, masked, ln = b0 & 0x0F, b1 & 0x80, b1 & 0x7F
                if ln == 126:
                    ln = struct.unpack("!H", need(2))[0]
                elif ln == 127:
                    ln = struct.unpack("!Q", need(8))[0]
                mask = need(4) if masked else None
                payload = need(ln) if ln else b""
                if not masked:  # clients MUST mask; catching this is the point
                    self._send(conn, ["NOTICE", "unmasked frame"])
                    continue
                payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
                if opcode == 0x8:
                    conn.close()
                    return
                if opcode != 0x1:
                    continue

                msg = json.loads(payload.decode())
                self.received.append(msg)

                if msg[0] == "EVENT":
                    event = msg[1]
                    self._send(conn, ["NOTICE", "hello"])  # must be ignored by clients
                    self._send(conn, ["OK", event["id"], self.accept, self.detail])
                    if self.accept:
                        self._store_and_broadcast(event)

                elif msg[0] == "REQ":
                    sub, filters = msg[1], msg[2] if len(msg) > 2 else {}
                    with self._lock:
                        self._subscriptions.append((conn, sub, filters))
                        stored = [e for e in self.events if matches(filters, e)]
                    if filters.get("limit") != 0:
                        for event in stored:
                            self._send(conn, ["EVENT", sub, event])
                    self._send(conn, ["EOSE", sub])

                elif msg[0] == "CLOSE":
                    with self._lock:
                        self._subscriptions = [
                            s for s in self._subscriptions if not (s[0] is conn and s[1] == msg[1])
                        ]
        except Exception:
            pass
        finally:
            with self._lock:
                self._subscriptions = [s for s in self._subscriptions if s[0] is not conn]
            try:
                conn.close()
            except Exception:
                pass
