"""Opaque wire fixtures only. Browser tests exercise actual encryption/decryption."""

import base64
import os
import uuid

_X = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_Y = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
KEYS = tuple(
    base64.b64encode(b"\x04" + _X.to_bytes(32) + y.to_bytes(32)).decode() for y in (_Y, _P - _Y)
)


def enroll(alice, bob):
    for client, key in zip((alice, bob), KEYS):
        assert client.post("/api/e2ee/key", json={"public_key": key}).status_code == 200


def envelope(reverse=False):
    sender, recipient = reversed(KEYS) if reverse else KEYS
    return {
        "v": 1,
        "sender_key": sender,
        "recipient_key": recipient,
        "message_id": str(uuid.uuid4()),
        "iv": base64.b64encode(os.urandom(12)).decode(),
        "ciphertext": base64.b64encode(os.urandom(32)).decode(),
    }
