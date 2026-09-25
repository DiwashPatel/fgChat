import struct
from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"FGCH"
PROTOCOL_VERSION = 1
HEADER_FORMAT = "!4sBBHI"
MAX_FRAME_PAYLOAD_SIZE = 1024 * 1024

HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

class ProtocolError(Exception):
    """Base Exception for FgChat protocol violations."""


class UnsupportedProtocolVersion(ProtocolError):
    """Peer is using a protocol version we do not support."""


class FrameTooLarge(ProtocolError):
    """Frame declares a payload larger than our configured limit."""


class FrameType(IntEnum):
    DATA = 0x01
    PING = 0x02
    PONG = 0x03
    CLOSE = 0x04

@dataclass(frozen=True)
class FrameHeader:
    version: int
    frame_type: FrameType
    flags: int
    payload_length: int


@dataclass(frozen=True)
class Frame:
    frame_header: FrameHeader
    payload: bytes


def encode_header(
        frame_type: FrameType,
        flags: int,
        payload_length: int, 
) -> bytes:

    if not 0 <= flags <= 0xFFFF:
        raise ValueError("flags must fit in 16 bits.")

    if not 0 <= payload_length <= MAX_FRAME_PAYLOAD_SIZE:
        raise FrameTooLarge(
            f"payload length {payload_length} is invalid."
        )

    return struct.pack(
        HEADER_FORMAT, 
        MAGIC,
        PROTOCOL_VERSION, 
        int(frame_type),
        flags,
        payload_length,
    )

def decode_header(data:bytes) -> FrameHeader:

    if len(data) != HEADER_SIZE:
        raise ProtocolError(
            f"expected {HEADER_SIZE} header bytes, got {len(data)}"
        )

    magic, version, raw_type, flags, payload_length = struct.unpack(HEADER_FORMAT, data)

    if magic != MAGIC:
        raise ProtocolError("invalid FgChat magic bytes")

    if version != PROTOCOL_VERSION:
        raise UnsupportedProtocolVersion(
            f"unsupported protocol version {version}"
        )

    try:
        frame_type = FrameType(raw_type)
    except ValueError as exc:
        raise ProtocolError(
            f"unknown frame type: {raw_type}"
        ) from exc 

    if payload_length > MAX_FRAME_PAYLOAD_SIZE:
        raise FrameTooLarge(
            f"frame payload is {payload_length} bytes"
        )  

    return FrameHeader(
        version=version, 
        frame_type=frame_type, 
        flags=flags,
        payload_length=payload_length,
    )


def recv_exact(sock, size: int) -> bytes:

    if size < 0:
        raise ValueError(f"size cannot be negative")

    data = bytearray()

    while len(data) < size:

        remaining = size - len(data)

        chunk = sock.recv(remaining)

        if not chunk:
            raise ConnectionError(
                "peer closed the connection while receiving data"
            )

        data.extend(chunk)

    return bytes(data)


def receive_frame(sock) -> Frame:

    header_bytes = recv_exact(
        sock,
        HEADER_SIZE,
    )

    header = decode_header(header_bytes)

    payload = recv_exact(sock, header.payload_length)

    return Frame(frame_header=header, payload=payload)


def send_frame(
        sock,
        frame_type: FrameType,
        payload: bytes,
        *,
        flags: int = 0,
) -> None:

    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")

    if len(payload) > MAX_FRAME_PAYLOAD_SIZE:
        raise FrameTooLarge(
            f"payload is {len(payload)} bytes"
        )

    header = encode_header(
        frame_type=frame_type,
        flags=flags,
        payload_length=len(payload),
    )

    sock.sendall(header + payload)
