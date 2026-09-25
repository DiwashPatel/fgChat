from __future__ import annotations

import base64
import json
import secrets
import socket
import string
import threading
from dataclasses import dataclass, field

from protocol import FrameType, ProtocolError, receive_frame, send_frame

HOST = "127.0.0.1"
PORT = 5050


@dataclass
class Client:
    socket: socket.socket
    username: str | None = None
    public_key: str | None = None
    active_peer: str | None = None
    pending_from: set[str] = field(default_factory=set)
    send_lock: threading.Lock = field(default_factory=threading.Lock)


clients_by_name = {}
clients_lock = threading.Lock()


def send(client, message):
    data = json.dumps(message, separators=(",", ":")).encode()
    with client.send_lock:
        send_frame(client.socket, FrameType.DATA, data)


def send_error(client, message):
    send(client, {"type": "error", "message": message})


def new_username():
    while True:
        name = "".join(secrets.choice(string.ascii_lowercase) for _ in range(3))
        if name not in clients_by_name:
            return name


def remove_client(client):
    peer = None
    with clients_lock:
        if client.username:
            clients_by_name.pop(client.username, None)
        if client.active_peer:
            peer = clients_by_name.get(client.active_peer)
            if peer and peer.active_peer == client.username:
                peer.active_peer = None
        for other in clients_by_name.values():
            other.pending_from.discard(client.username)

    if peer:
        try:
            send(peer, {"type": "peer_left", "username": client.username})
        except OSError:
            pass
    try:
        client.socket.close()
    except OSError:
        pass


def register(client, message):
    public_key = message.get("public_key")
    if client.username is not None:
        return send_error(client, "Already registered")
    try:
        decoded_key = base64.b64decode(public_key, validate=True)
    except (ValueError, TypeError):
        decoded_key = b""
    if len(decoded_key) != 32:
        return send_error(client, "Invalid public key")

    with clients_lock:
        client.username = new_username()
        client.public_key = public_key
        clients_by_name[client.username] = client
    send(client, {"type": "registered", "username": client.username})


def request_chat(client, message):
    target_name = message.get("username")
    with clients_lock:
        target = clients_by_name.get(target_name)
        if not target or target is client:
            target = None
            busy = False
        elif client.active_peer or target.active_peer:
            busy = True
        else:
            busy = False
            target.pending_from.add(client.username)

    if not target:
        return send_error(client, f"User {target_name} was not found")
    if busy:
        return send_error(client, "One of you is already in a chat")
    send(target, {"type": "hello", "from": client.username})
    send(client, {"type": "request_sent", "username": target_name})


def accept_chat(client, message):
    requester_name = message.get("username")
    with clients_lock:
        requester = clients_by_name.get(requester_name)
        valid = bool(
            requester
            and requester_name in client.pending_from
            and not client.active_peer
            and not requester.active_peer
        )
        if valid:
            client.pending_from.discard(requester_name)
            client.active_peer = requester_name
            requester.active_peer = client.username

    if not valid:
        return send_error(client, "That invitation is no longer available")
    send(requester, {"type": "accepted", "username": client.username, "public_key": client.public_key})
    send(client, {"type": "chat_started", "username": requester.username, "public_key": requester.public_key})


def reject_chat(client, message):
    requester_name = message.get("username")
    with clients_lock:
        existed = requester_name in client.pending_from
        client.pending_from.discard(requester_name)
        requester = clients_by_name.get(requester_name)
    if existed and requester:
        send(requester, {"type": "rejected", "username": client.username})


def route_message(client, message):
    ciphertext = message.get("ciphertext")
    with clients_lock:
        target = clients_by_name.get(client.active_peer)
        valid = target and target.active_peer == client.username
    if not valid:
        return send_error(client, "You are not in a chat")
    if not isinstance(ciphertext, str):
        return send_error(client, "Invalid encrypted message")
    send(target, {"type": "message", "from": client.username, "ciphertext": ciphertext})


def leave_chat(client, _message):
    with clients_lock:
        peer = clients_by_name.get(client.active_peer)
        client.active_peer = None
        if peer and peer.active_peer == client.username:
            peer.active_peer = None
    if peer:
        send(peer, {"type": "peer_left", "username": client.username})
    send(client, {"type": "left"})


HANDLERS = {
    "register": register,
    "connect": request_chat,
    "accept": accept_chat,
    "reject": reject_chat,
    "message": route_message,
    "leave": leave_chat,
}


def handle_client(client_socket, address):
    client = Client(client_socket)
    print(f"{address} connected")

    try:
        while True:
            frame = receive_frame(client_socket)
            if frame.frame_header.frame_type != FrameType.DATA:
                continue
            try:
                message = json.loads(frame.payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                send_error(client, "Invalid message")
                continue
            message_type = message.get("type") if isinstance(message, dict) else None
            if message_type == "register" or client.username is not None:
                handler = HANDLERS.get(message_type)
                if handler:
                    handler(client, message)
                else:
                    send_error(client, "Unknown message type")
            else:
                send_error(client, "Register first")
    except (ConnectionError, OSError, ProtocolError):
        pass
    finally:
        remove_client(client)
        print(f"{address} disconnected")


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()

print(f"Server started at {HOST}:{PORT}")

try:
    while True:
        client_socket, address = server.accept()
        threading.Thread(target=handle_client, args=(client_socket, address), daemon=True).start()
except KeyboardInterrupt:
    print("\nStopping server.")
finally:
    with clients_lock:
        connected_clients = list(clients_by_name.values())
    for client in connected_clients:
        client.socket.close()
    server.close()
