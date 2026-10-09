"""Threaded TLS chat server with account authentication and persistent direct messages."""

import argparse
import logging
import os
import re
import socket
import ssl
import threading
from pathlib import Path

from protocol import ProtocolError, receive_message, send_message
from storage import ChatStore

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,24}$")
MAX_TEXT_LENGTH = 4000


class ChatServer:
    def __init__(self, host: str, port: int, store: ChatStore, tls_context: ssl.SSLContext) -> None:
        self.host = host
        self.port = port
        self.store = store
        self.tls_context = tls_context
        self.clients: dict[str, ssl.SSLSocket] = {}
        self.client_send_locks: dict[ssl.SSLSocket, threading.Lock] = {}
        self.clients_lock = threading.RLock()
        self.stopping = threading.Event()

    def send(self, client: ssl.SSLSocket, message: dict) -> None:
        with self.clients_lock:
            lock = self.client_send_locks.setdefault(client, threading.Lock())
        with lock:
            send_message(client, message)

    def deliver(self, username: str, message: dict) -> bool:
        with self.clients_lock:
            recipient = self.clients.get(username.casefold())
        if recipient is None:
            return False
        try:
            self.send(recipient, message)
            return True
        except OSError:
            return False

    def handle(self, raw_client: socket.socket, address: tuple) -> None:
        client = None
        username = None
        try:
            raw_client.settimeout(10)
            client = self.tls_context.wrap_socket(raw_client, server_side=True)
            request = receive_message(client)
            if request is None:
                return
            action = request.get("action")
            supplied_name = request.get("username")
            password = request.get("password")
            if action not in ("register", "login") or not isinstance(supplied_name, str) or not USERNAME_RE.fullmatch(supplied_name):
                self.send(client, {"type": "error", "message": "Use a 3–24 character username containing letters, numbers, or underscores."})
                return
            if not isinstance(password, str) or not 10 <= len(password) <= 128:
                self.send(client, {"type": "error", "message": "Password must contain 10–128 characters."})
                return
            if action == "register":
                if not self.store.register(supplied_name, password):
                    self.send(client, {"type": "error", "message": "That username is already registered."})
                    return
                username = supplied_name
            else:
                username = self.store.authenticate(supplied_name, password)
                if username is None:
                    self.send(client, {"type": "error", "message": "Invalid username or password."})
                    return
            with self.clients_lock:
                if username.casefold() in self.clients:
                    self.send(client, {"type": "error", "message": "This account is already connected."})
                    return
                self.clients[username.casefold()] = client
                self.client_send_locks[client] = threading.Lock()
            client.settimeout(None)
            self.send(client, {"type": "ready", "username": username})
            logging.info("%s connected from %s:%s", username, *address)
            while not self.stopping.is_set():
                request = receive_message(client)
                if request is None:
                    break
                if request.get("action") == "send":
                    self.handle_send(client, username, request)
                elif request.get("action") == "history":
                    peer = request.get("with")
                    if not isinstance(peer, str) or not USERNAME_RE.fullmatch(peer) or not self.store.user_exists(peer):
                        self.send(client, {"type": "error", "message": "Choose an existing username for history."})
                    else:
                        self.send(client, {"type": "history", "with": peer, "messages": self.store.history(username, peer)})
                else:
                    self.send(client, {"type": "error", "message": "Unknown action."})
        except (OSError, ProtocolError, ssl.SSLError) as exc:
            logging.debug("Connection %s ended: %s", address, exc)
        finally:
            if username:
                with self.clients_lock:
                    if self.clients.get(username.casefold()) is client:
                        self.clients.pop(username.casefold(), None)
                    self.client_send_locks.pop(client, None)
                logging.info("%s disconnected", username)
            if client is not None:
                try:
                    client.close()
                except OSError:
                    pass
            else:
                raw_client.close()

    def handle_send(self, client: ssl.SSLSocket, sender: str, request: dict) -> None:
        recipient = request.get("to")
        body = request.get("text")
        if not isinstance(recipient, str) or not USERNAME_RE.fullmatch(recipient) or not isinstance(body, str):
            self.send(client, {"type": "error", "message": "Provide a valid recipient and message."})
            return
        body = body.strip()
        if not body or len(body.encode("utf-8")) > MAX_TEXT_LENGTH:
            self.send(client, {"type": "error", "message": "Messages must contain 1–4000 UTF-8 bytes."})
            return
        if not self.store.user_exists(recipient):
            self.send(client, {"type": "error", "message": "That user does not exist."})
            return
        canonical_recipient = recipient
        message = self.store.save_message(sender, canonical_recipient, body)
        event = {"type": "message", **message}
        self.send(client, event)
        self.deliver(canonical_recipient.casefold(), event)

    def serve_forever(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(128)
        listener.settimeout(1)
        logging.info("Listening on %s:%s with TLS", self.host, self.port)
        try:
            while not self.stopping.is_set():
                try:
                    client, address = listener.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self.handle, args=(client, address), daemon=True).start()
        finally:
            self.stopping.set()
            listener.close()
            with self.clients_lock:
                clients = list(self.clients.values())
            for client in clients:
                client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Encrypted FgChat TCP server")
    parser.add_argument("--host", default=os.getenv("FGCHAT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FGCHAT_PORT", "5000")))
    parser.add_argument("--database", type=Path, default=Path(os.getenv("FGCHAT_DATABASE", "users.sqlite3")))
    parser.add_argument("--cert", type=Path, default=Path(os.getenv("FGCHAT_TLS_CERT", "certs/server.crt")))
    parser.add_argument("--key", type=Path, default=Path(os.getenv("FGCHAT_TLS_KEY", "certs/server.key")))
    args = parser.parse_args()
    if not args.cert.is_file() or not args.key.is_file():
        parser.error("TLS certificate not found; run ./scripts/create-dev-cert.sh for local development")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ChatServer(args.host, args.port, ChatStore(args.database), context).serve_forever()


if __name__ == "__main__":
    main()
