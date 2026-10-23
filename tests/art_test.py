#!/usr/bin/env python3
"""Checks the embedded-art extraction against synthetic audio files.

The fallback runs whenever a player ships no mpris:artUrl, so its parsers
are pinned here against hand-built ID3v2.2/2.3/2.4, FLAC and MP4 files:
a wrong picture, a skipped frame header or an accepted remote URL would
all be invisible until a cover silently fails to appear.

Run: python3 tests/art_test.py
"""

import importlib.util
import os
import sys
import tempfile
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(os.path.dirname(HERE), "bin", "omarchy-scrobble")

# The helper is an extensionless executable, so it needs an explicit loader.
spec = importlib.util.spec_from_loader(
    "scrobble_helper", SourceFileLoader("scrobble_helper", HELPER)
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

# Keep every extraction out of the user's real cache.
CACHE_ROOT = tempfile.mkdtemp(prefix="scrobble-art-test-")
os.environ["XDG_CACHE_HOME"] = CACHE_ROOT
FILES = tempfile.mkdtemp(prefix="scrobble-art-files-")

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def syncsafe(size):
    return bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])


def write_file(name, blob):
    path = os.path.join(FILES, name)
    with open(path, "wb") as handle:
        handle.write(blob)
    return path


PICTURE = b"\x89PNG\r\n\x1a\n" + b"fake png payload for the scrobble art tests" * 4


def id3_tag(major, frame):
    return b"ID3" + bytes([major, 0]) + b"\x00" + syncsafe(len(frame)) + frame


def apic_v3(picture):
    body = b"\x00" + b"image/png\x00" + b"\x03" + b"\x00" + picture
    return b"APIC" + len(body).to_bytes(4, "big") + b"\x00\x00" + body


def apic_v4(picture):
    body = b"\x00" + b"image/png\x00" + b"\x03" + b"desc\x00" + picture
    return b"APIC" + syncsafe(len(body)) + b"\x00\x00" + body


def pic_v2(picture):
    body = b"\x00" + b"PNG" + b"\x03" + b"\x00" + picture
    return b"PIC" + len(body).to_bytes(3, "big") + body


def flac_file(picture):
    block = (
        (0).to_bytes(4, "big")
        + len(b"image/png").to_bytes(4, "big")
        + b"image/png"
        + (0).to_bytes(4, "big")
        + (16).to_bytes(4, "big")
        + (16).to_bytes(4, "big")
        + (24).to_bytes(4, "big")
        + (0).to_bytes(4, "big")
        + len(picture).to_bytes(4, "big")
        + picture
    )
    return b"fLaC" + b"\x86" + len(block).to_bytes(3, "big") + block


def mp4_atom(kind, payload):
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def mp4_file(picture):
    data = mp4_atom(b"data", (13).to_bytes(4, "big") + (0).to_bytes(4, "big") + picture)
    covr = mp4_atom(b"covr", data)
    ilst = mp4_atom(b"ilst", covr)
    meta = mp4_atom(b"meta", b"\x00\x00\x00\x00" + ilst)
    udta = mp4_atom(b"udta", meta)
    moov = mp4_atom(b"moov", udta)
    ftyp = mp4_atom(b"ftyp", b"isom\x00\x00\x02\x00isom")
    return ftyp + moov + mp4_atom(b"mdat", b"audio bytes")


print("embedded art extraction")

mp3_v3 = write_file("track-v3.mp3", id3_tag(3, apic_v3(PICTURE)) + b"\xff\xfb" + b"audio" * 32)
art = helper.extract_art(mp3_v3)
check("id3v2.3 art is extracted", art != "" and os.path.exists(art), f"got {art!r}")
check(
    "id3v2.3 art content matches",
    art.endswith(".png") and open(art, "rb").read() == PICTURE,
)
check("id3v2.3 cache is reused", helper.extract_art(f"file://{mp3_v3}") == art)
check("cached art is private", (os.stat(art).st_mode & 0o777) == 0o600)

mp3_v4 = write_file("track-v4.mp3", id3_tag(4, apic_v4(PICTURE)) + b"\xff\xfb" + b"audio" * 32)
art4 = helper.extract_art(mp3_v4)
check("id3v2.4 art is extracted", art4 != "" and open(art4, "rb").read() == PICTURE, f"got {art4!r}")

mp3_v2 = write_file("track-v2.mp3", id3_tag(2, pic_v2(PICTURE)) + b"audio" * 32)
art2 = helper.extract_art(mp3_v2)
check("id3v2.2 art is extracted", art2 != "" and open(art2, "rb").read() == PICTURE, f"got {art2!r}")

flac = write_file("track.flac", flac_file(PICTURE) + b"\x00" * 4096)
art_flac = helper.extract_art(flac)
check("flac art is extracted", art_flac != "" and open(art_flac, "rb").read() == PICTURE, f"got {art_flac!r}")

mp4 = write_file("track.m4a", mp4_file(PICTURE))
art_mp4 = helper.extract_art(mp4)
check("mp4 art is extracted", art_mp4 != "" and open(art_mp4, "rb").read() == PICTURE, f"got {art_mp4!r}")

mp4_tail = write_file(
    "tail.m4a",
    mp4_atom(b"ftyp", b"isom\x00\x00\x02\x00isom")
    + mp4_atom(b"mdat", b"audio" * 1024)
    + mp4_atom(b"moov", mp4_atom(b"udta", mp4_atom(b"meta", b"\x00\x00\x00\x00" + mp4_atom(b"ilst", mp4_atom(b"covr", mp4_atom(b"data", (14).to_bytes(4, "big") + (0).to_bytes(4, "big") + PICTURE)))))),
)
art_tail = helper.extract_art(mp4_tail)
check("mp4 art found with moov at the end", art_tail != "" and open(art_tail, "rb").read() == PICTURE, f"got {art_tail!r}")

print("failure paths")

try:
    helper.extract_art("https://example.com/track.mp3")
    check("remote art urls are refused", False, "no exception raised")
except ValueError:
    check("remote art urls are refused", True)

try:
    helper.extract_art("relative/path.mp3")
    check("relative paths are refused", False, "no exception raised")
except ValueError:
    check("relative paths are refused", True)

silent = write_file("silent.mp3", b"\xff\xfb" + b"audio" * 32)
check("a file with no art yields no path", helper.extract_art(silent) == "")

oversized = b"\x89PNG\r\n\x1a\n" + b"x" * (helper.MAX_ART_BYTES + 1)
huge = write_file("huge.mp3", id3_tag(3, apic_v3(oversized)) + b"audio" * 32)
check("oversized art is refused", helper.extract_art(huge) == "")

try:
    helper.extract_art(os.path.join(FILES, "does-not-exist.mp3"))
    check("missing files are reported, not crashed", False, "no exception raised")
except ValueError:
    check("missing files are reported, not crashed", True)


print("remote art fetch")

# The runtime function shares the profile-picture path: public HTTPS only,
# size-bounded, no automatic redirects, pinned to the validated address.
# Exercise it against a fake transport so nothing leaves this process.
class FakeResponse:
    def __init__(self, blob, content_type="image/png"):
        self.blob = blob
        self.headers = {"Content-Type": content_type}

    def read(self, limit):
        return self.blob[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        self.request = request
        return self.response


urls_seen = []


def fake_download(url, blobs, prefix="art"):
    """Drive _download_image with validate/opener stubs; no sockets."""
    saved_validate = helper.validate_avatar_url
    saved_opener = helper._avatar_opener
    queue = list(blobs)
    try:
        helper.validate_avatar_url = lambda value: urls_seen.append(value) or "203.0.113.7"
        helper._avatar_opener = lambda address: FakeOpener(queue.pop(0))
        return helper.download_art(url)
    finally:
        helper.validate_avatar_url = saved_validate
        helper._avatar_opener = saved_opener


small = b"\x89PNG\r\n\x1a\n" + b"cover art payload for the fetch tests" * 4
path = fake_download("https://covers.example/a.png", [FakeResponse(small)])
check("remote art is cached to disk", path != "" and open(path, "rb").read() == small, f"got {path!r}")
check("remote art is cached under the art prefix",
      os.path.basename(path).startswith("art-"), path)
check("remote art is cached in the test cache, not the user's",
      path.startswith(CACHE_ROOT), path)
check("a repeated remote art fetch reuses the cached file",
      fake_download("https://covers.example/a.png", [FakeResponse(small)]) == path)
check("the fetch validates the url before opening",
      urls_seen[-1] == "https://covers.example/a.png", urls_seen[-1])

oversize_body = b"x" * (helper.MAX_AVATAR_BYTES + 1)
try:
    fake_download("https://covers.example/huge.png", [FakeResponse(oversize_body)])
    check("an oversized remote response is refused", False, "no error raised")
except ValueError:
    check("an oversized remote response is refused", True)

try:
    fake_download("https://covers.example/empty.png", [FakeResponse(b"")])
    check("an empty remote response is refused", False, "no error raised")
except ValueError:
    check("an empty remote response is refused", True)

for label, bad in [
    ("http", "http://covers.example/a.png"),
    ("ftp", "ftp://covers.example/a.png"),
    ("file", "file:///tmp/cover.png"),
    ("garbage", "not a url"),
]:
    try:
        helper.download_art(bad)
        check(f"fetch-art refuses a {label} url", False, "no error raised")
    except ValueError:
        check(f"fetch-art refuses a {label} url", True)

# Redirects to the png are followed after each hop is revalidated — the
# redirected url is what lands in the cache and the digest.
redirects_seen = []
saved_validate = helper.validate_avatar_url
saved_opener = helper._avatar_opener
try:
    helper.validate_avatar_url = lambda value: redirects_seen.append(value) or "203.0.113.7"
    helper._avatar_opener = lambda address: FakeOpener(FakeResponse(small, "image/jpeg"))
    helper.download_art("https://covers.example/b.png")
finally:
    helper.validate_avatar_url = saved_validate
    helper._avatar_opener = saved_opener
check("downloaded redirects are revalidated per hop",
      redirects_seen == ["https://covers.example/b.png"], redirects_seen)

# And the whole thing hangs off the same validator the reviewers already
# vetted for profile pictures.
saved_validate = helper.validate_avatar_url
try:
    helper.validate_avatar_url = lambda value: (_ for _ in ()).throw(ValueError("stopped"))
    try:
        helper.download_art("https://covers.example/a.png")
        check("download_art routes through the public-address validator", False, "no error raised")
    except ValueError:
        check("download_art routes through the public-address validator", True)
finally:
    helper.validate_avatar_url = saved_validate

print()
if failures:
    print(f"{len(failures)} art extraction check(s) failed")
    sys.exit(1)
print("all art extraction checks passed")
