"""Length-prefixed JSON messages for the FgChat TCP protocol."""

import json
import socket
import struct
from typing import Any

HEADER = struct.Struct("!I")
MAX_MESSAGE_SIZE = 64 * 1024


class ProtocolError(Exception):
    """Raised when a peer sends an invalid protocol message."""


def _receive_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            if not chunks:
                return b""
            raise ProtocolError("connection closed during a frame")
        chunks.extend(chunk)
    return bytes(chunks)


def receive_message(sock: socket.socket) -> dict[str, Any] | None:
    header = _receive_exact(sock, HEADER.size)
    if not header:
        return None
    (size,) = HEADER.unpack(header)
    if size == 0 or size > MAX_MESSAGE_SIZE:
        raise ProtocolError("invalid message size")
    payload = _receive_exact(sock, size)
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("message must contain valid UTF-8 JSON") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    return message


def send_message(sock: socket.socket, message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not payload or len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError("message exceeds the size limit")
    sock.sendall(HEADER.pack(len(payload)) + payload)
