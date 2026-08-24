#!/usr/bin/env python3
"""Checks the helper's crypto against published test vectors.

The signing path is the one part of this plugin that cannot be verified by
looking at it: a wrong signature is indistinguishable from a right one until a
relay rejects it. So it is pinned to the BIP-340 and NIP-19 vectors here.

Run: python3 tests/helper_test.py
"""

import hashlib
import importlib.util
import json
import os
import sys
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(os.path.dirname(HERE), "bin", "omarchy-scrobble")

# The helper is an extensionless executable, so it needs an explicit loader.
spec = importlib.util.spec_from_loader(
    "scrobble_helper", SourceFileLoader("scrobble_helper", HELPER)
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


# ------------------------------------------------- BIP-340 signing vectors
# https://github.com/bitcoin/bips/blob/master/bip-0340/test-vectors.csv

BIP340_VECTORS = [
    (
        "0000000000000000000000000000000000000000000000000000000000000003",
        "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9",
        "0000000000000000000000000000000000000000000000000000000000000000",
        "0000000000000000000000000000000000000000000000000000000000000000",
        "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
        "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0",
    ),
    (
        "B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF",
        "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659",
        "0000000000000000000000000000000000000000000000000000000000000001",
        "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
        "6896BD60EEAE296DB48A229FF71DFE071BDE413E6D43F917DC8DCF8C78DE3341"
        "8906D11AC976ABCCB20B091292BFF4EA897EFCB639EA871CFA95F6DE339E4B0A",
    ),
    (
        "C90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9",
        "DD308AFEC5777E13121FA72B9CC1B7CC0139715309B086C960E18FD969774EB8",
        "C87AA53824B4D7AE2EB035A2B5BBBCCC080E76CDC6D1692C4B0B62D798E6D906",
        "7E2D58D8B3BCDF1ABADEC7829054F90DDA9805AAB56C77333024B9D0A508B75C",
        "5831AAEED7B44BB74E5EAB94BA9D4294C49BCF2A60728D8B4C200F50DD313C1B"
        "AB745879A5AD954A72C45A91C3A51D3C7ADEA98D82F8481E0E1E03674A6F3FB7",
    ),
    (
        "0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710",
        "25D1DFF95105F5253C4022F628A996AD3A0D95FBF21D468A1B33F8C160D8F517",
        "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
        "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
        "7EB0509757E246F19449885651611CB965ECC1A187DD51B64FDA1EDC9637D5EC"
        "97582B9CB13DB3933705B32BA982AF5AF25FD78881EBB32771FC5922EFC66EA3",
    ),
]

print("BIP-340 Schnorr vectors")
for index, (seckey, pubkey, aux, msg, sig) in enumerate(BIP340_VECTORS):
    secret = bytes.fromhex(seckey)
    derived = helper.public_key_from_secret(secret)
    check(f"vector {index} public key", derived.hex().upper() == pubkey, derived.hex())

    produced = helper.schnorr_sign(bytes.fromhex(msg), secret, bytes.fromhex(aux))
    check(f"vector {index} signature", produced.hex().upper() == sig, produced.hex())

    check(
        f"vector {index} verifies",
        helper.schnorr_verify(bytes.fromhex(msg), bytes.fromhex(pubkey), produced),
    )

# A tampered signature must not verify, or the verifier is proving nothing.
msg = bytes.fromhex(BIP340_VECTORS[1][3])
pub = bytes.fromhex(BIP340_VECTORS[1][1])
good = bytes.fromhex(BIP340_VECTORS[1][4])
bad = good[:-1] + bytes([good[-1] ^ 0x01])
check("tampered signature rejected", not helper.schnorr_verify(msg, pub, bad))

# ------------------------------------------------------------ NIP-19 vectors
# The nsec/npub pair published in NIP-19.

print("NIP-19 bech32 vectors")
# The nsec published in NIP-19, and the pubkey it derives to.
NSEC = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"
NSEC_HEX = "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"
NPUB_HEX = "7e7e9c42a91bfef19fa929e5fda1b72e0ebc1a4c1141673e2794234d86addf4e"
NPUB = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptg"

# NIP-19's standalone npub example, which belongs to an unrelated key. It is
# here because it pins the decoder against a published string we did not
# produce ourselves.
FOREIGN_NPUB = "npub1sn0wdenkukak0d9dfczzeacvhkrgz92ak56egt7vdgzn8pv2wfqqhrjdv9"
FOREIGN_HEX = "84dee6e676e5bb67b4ad4e042cf70cbd8681155db535942fcc6a0533858a7240"

decoded = helper.bech32_to_bytes(NSEC, "nsec")
check("nsec decodes to the documented hex", decoded.hex() == NSEC_HEX, decoded.hex())
check("nsec re-encodes", helper.bytes_to_bech32(decoded, "nsec") == NSEC)

derived_pub = helper.public_key_from_secret(decoded)
check("nsec derives the documented pubkey", derived_pub.hex() == NPUB_HEX, derived_pub.hex())
check("pubkey encodes to the documented npub", helper.bytes_to_bech32(derived_pub, "npub") == NPUB)
check("npub decodes back", helper.bech32_to_bytes(NPUB, "npub").hex() == NPUB_HEX)
check(
    "the published npub example decodes to its documented hex",
    helper.bech32_to_bytes(FOREIGN_NPUB, "npub").hex() == FOREIGN_HEX,
)

try:
    helper.bech32_to_bytes(NPUB[:-1] + ("9" if NPUB[-1] != "9" else "8"), "npub")
    check("corrupt npub rejected", False)
except ValueError:
    check("corrupt npub rejected", True)

try:
    helper.bech32_to_bytes(NPUB, "nsec")
    check("hrp mismatch rejected", False)
except ValueError:
    check("hrp mismatch rejected", True)

# ------------------------------------------------------------- event signing

print("Nostr event construction")
event = helper.build_event(
    decoded,
    helper.KIND_USER_STATUS,
    [["d", "music"], ["r", "https://example.test/x"]],
    "Ella Fitzgerald - Blue Skies",
    created_at=1700000000,
)
check("event pubkey matches the key", event["pubkey"] == NPUB_HEX)
check("event kind is the NIP-38 status kind", event["kind"] == 30315)

recomputed = hashlib.sha256(
    helper.serialize_event(
        event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]
    )
).hexdigest()
check("event id is the hash of the serialization", event["id"] == recomputed, event["id"])
check(
    "event signature verifies against the event id",
    helper.schnorr_verify(bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]), bytes.fromhex(event["sig"])),
)

# Non-ASCII content must be serialized unescaped, or the id will not match what
# relays compute.
unicode_event = helper.build_event(decoded, 1, [], "Björk – Jóga", created_at=1700000000)
serialized = helper.serialize_event(unicode_event["pubkey"], 1700000000, 1, [], "Björk – Jóga")
check("unicode content is serialized as UTF-8, not escaped", b"Bj\xc3\xb6rk" in serialized)
check(
    "unicode event id is the hash of that serialization",
    unicode_event["id"] == hashlib.sha256(serialized).hexdigest(),
)

# ---------------------------------------------------------------- listen data

print("ListenBrainz payloads")
metadata = helper.track_metadata("Ella Fitzgerald", "Blue Skies", "Ella in Berlin", 214000)
check("artist and track are set", metadata["track_metadata"]["artist_name"] == "Ella Fitzgerald")
check("album maps to release_name", metadata["track_metadata"]["release_name"] == "Ella in Berlin")
check("duration is carried in ms", metadata["track_metadata"]["additional_info"]["duration_ms"] == 214000)
check("no album means no release_name", "release_name" not in helper.track_metadata("A", "B", "", 0)["track_metadata"])
check("zero duration is omitted", "duration_ms" not in helper.track_metadata("A", "B", "", 0)["track_metadata"]["additional_info"])
# playing_now submissions must not carry listened_at; only `single` may.
check("playing-now metadata has no listened_at", "listened_at" not in metadata)

# ------------------------------------------------ nip-44 (official vectors)
#
# The encryption NIP-46 uses to talk to a phone signer. Vectors from
# https://github.com/paulmillr/nip44.

print("NIP-44 v2 vectors")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "nip44.vectors.json")) as handle:
    V2 = json.load(handle)["v2"]

ok = all(helper.nip44_padded_len(a) == b for a, b in V2["valid"]["calc_padded_len"])
check(f"calc_padded_len ({len(V2['valid']['calc_padded_len'])} vectors)", ok)

ok = all(
    helper.nip44_conversation_key(bytes.fromhex(v["sec1"]), bytes.fromhex(v["pub2"])).hex()
    == v["conversation_key"]
    for v in V2["valid"]["get_conversation_key"]
)
check(f"get_conversation_key ({len(V2['valid']['get_conversation_key'])} vectors)", ok)

group = V2["valid"]["get_message_keys"]
conversation_key = bytes.fromhex(group["conversation_key"])
ok = all(
    helper.nip44_message_keys(conversation_key, bytes.fromhex(v["nonce"]))
    == (bytes.fromhex(v["chacha_key"]), bytes.fromhex(v["chacha_nonce"]), bytes.fromhex(v["hmac_key"]))
    for v in group["keys"]
)
check(f"get_message_keys ({len(group['keys'])} vectors)", ok)

ok = True
for v in V2["valid"]["encrypt_decrypt"]:
    key = helper.nip44_conversation_key(
        bytes.fromhex(v["sec1"]), helper.public_key_from_secret(bytes.fromhex(v["sec2"]))
    )
    if key.hex() != v["conversation_key"]:
        ok = False
    if helper.nip44_encrypt(v["plaintext"], key, bytes.fromhex(v["nonce"])) != v["payload"]:
        ok = False
    if helper.nip44_decrypt(v["payload"], key) != v["plaintext"]:
        ok = False
check(f"encrypt_decrypt ({len(V2['valid']['encrypt_decrypt'])} vectors)", ok)

ok = True
for v in V2["valid"]["encrypt_decrypt_long_msg"]:
    key = bytes.fromhex(v["conversation_key"])
    plaintext = v["pattern"] * v["repeat"]
    payload = helper.nip44_encrypt(plaintext, key, bytes.fromhex(v["nonce"]))
    if hashlib.sha256(payload.encode()).hexdigest() != v["payload_sha256"]:
        ok = False
    if helper.nip44_decrypt(payload, key) != plaintext:
        ok = False
check(f"encrypt_decrypt_long_msg ({len(V2['valid']['encrypt_decrypt_long_msg'])} vectors)", ok)

# A cipher that never rejects anything is not providing integrity.
rejected = 0
for v in V2["invalid"]["decrypt"]:
    try:
        helper.nip44_decrypt(v["payload"], bytes.fromhex(v["conversation_key"]))
    except Exception:
        rejected += 1
check(f"invalid payloads rejected ({rejected}/{len(V2['invalid']['decrypt'])})",
      rejected == len(V2["invalid"]["decrypt"]))

rejected = 0
for v in V2["invalid"]["get_conversation_key"]:
    try:
        helper.nip44_conversation_key(bytes.fromhex(v["sec1"]), bytes.fromhex(v["pub2"]))
    except Exception:
        rejected += 1
check(f"invalid conversation keys rejected ({rejected}/{len(V2['invalid']['get_conversation_key'])})",
      rejected == len(V2["invalid"]["get_conversation_key"]))

# ----------------------------------------------------- chacha20 (RFC 8439)

print("ChaCha20 and AES vectors")
rfc_key = bytes(range(32))
rfc_nonce = bytes.fromhex("000000000000004a00000000")
rfc_plain = (
    b"Ladies and Gentlemen of the class of '99: If I could offer you only one "
    b"tip for the future, sunscreen would be it."
)
rfc_cipher = helper.chacha20(rfc_key, rfc_nonce, rfc_plain, counter=1)
check("RFC 8439 chacha20 keystream",
      rfc_cipher.hex().startswith("6e2e359a2568f98041ba0728dd0d6981"), rfc_cipher.hex()[:32])
check("chacha20 is its own inverse",
      helper.chacha20(rfc_key, rfc_nonce, rfc_cipher, counter=1) == rfc_plain)

# ------------------------------------------------ aes / nip-04 (legacy path)

aes_words, aes_rounds = helper._aes_expand_key(
    bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
)
aes_ct = helper._aes_encrypt_block(bytes.fromhex("00112233445566778899aabbccddeeff"), aes_words, aes_rounds)
check("FIPS-197 AES-256 encrypt", aes_ct.hex() == "8ea2b7ca516745bfeafc49904b496089", aes_ct.hex())
check("FIPS-197 AES-256 decrypt",
      helper._aes_decrypt_block(aes_ct, aes_words, aes_rounds).hex() == "00112233445566778899aabbccddeeff")

# NIST SP 800-38A F.2.5, first CBC block.
nist_words, nist_rounds = helper._aes_expand_key(
    bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
)
nist_iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
nist_block = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
nist_out = helper._aes_encrypt_block(
    bytes(a ^ b for a, b in zip(nist_block, nist_iv)), nist_words, nist_rounds
)
check("NIST SP 800-38A CBC-AES256 block 1",
      nist_out.hex() == "f58c4c04d6e5f1ba779eabfb5f7bfbd6", nist_out.hex())

for size in (0, 1, 15, 16, 17, 1000):
    message = os.urandom(size)
    aes_key, iv = os.urandom(32), os.urandom(16)
    if helper.aes_cbc_decrypt(aes_key, iv, helper.aes_cbc_encrypt(aes_key, iv, message)) != message:
        check(f"CBC round trip at {size} bytes", False)
        break
else:
    check("CBC+PKCS#7 round-trips across block boundaries", True)

alice, bob = os.urandom(32), os.urandom(32)
alice_pub = helper.public_key_from_secret(alice)
bob_pub = helper.public_key_from_secret(bob)
request = '{"id":"1","method":"sign_event","params":["{}"]}'
nip04_payload = helper.nip04_encrypt(request, alice, bob_pub)
check("nip04 payload carries an iv", helper.is_nip04_payload(nip04_payload))
check("nip04 decrypts on the peer side", helper.nip04_decrypt(nip04_payload, bob, alice_pub) == request)
check("nip04 shared secret is symmetric",
      helper.nip04_shared_secret(alice, bob_pub) == helper.nip04_shared_secret(bob, alice_pub))
check("unicode survives nip04",
      helper.nip04_decrypt(helper.nip04_encrypt("Björk – Jóga ♪", alice, bob_pub), bob, alice_pub)
      == "Björk – Jóga ♪")
# The two schemes must stay distinguishable, or the wrong decrypt gets tried.
check("a nip44 payload is not mistaken for nip04",
      not helper.is_nip04_payload(
          helper.nip44_encrypt("hi", helper.nip44_conversation_key(alice, bob_pub))))

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all helper checks passed")
