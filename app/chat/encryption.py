"""Validation of public encryption metadata; no private keys or plaintext processing."""

import base64
import binascii
import uuid

P256_PRIME = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B


def decode_base64(value, minimum, maximum):
    if not isinstance(value, str) or len(value) > ((maximum + 2) // 3) * 4:
        raise ValueError("Invalid encryption data.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid encryption data.") from error
    if not minimum <= len(raw) <= maximum or base64.b64encode(raw).decode() != value:
        raise ValueError("Invalid encryption data.")
    return raw


def validate_public_key(value):
    raw = decode_base64(value, 65, 65)
    x, y = int.from_bytes(raw[1:33]), int.from_bytes(raw[33:])
    if (
        raw[0] != 4
        or x >= P256_PRIME
        or y >= P256_PRIME
        or (y * y - (x * x * x - 3 * x + P256_B)) % P256_PRIME != 0
    ):
        raise ValueError("Invalid P-256 public key.")
    return value


def validate_envelope(value, sender_key, recipient_key):
    fields = {"v", "sender_key", "recipient_key", "message_id", "iv", "ciphertext"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("A complete encrypted message is required for private chats.")
    if type(value["v"]) is not int or value["v"] != 1:
        raise ValueError("Unsupported encryption version.")
    if not sender_key or not recipient_key:
        raise ValueError("Both people must open FgChat to set up encryption first.")
    if value["sender_key"] != sender_key or value["recipient_key"] != recipient_key:
        raise ValueError("Encryption keys do not match this conversation.")
    message_id = value["message_id"]
    try:
        parsed = uuid.UUID(message_id) if isinstance(message_id, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.version != 4 or str(parsed) != message_id:
        raise ValueError("Invalid encrypted message ID.")
    decode_base64(value["iv"], 12, 12)
    decode_base64(value["ciphertext"], 17, 4016)
    return value
