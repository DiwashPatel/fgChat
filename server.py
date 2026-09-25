"""Small authenticated chat server. Accounts are stored in users.sqlite3."""
import hashlib
import hmac
import os
import re
import socket
import sqlite3
import threading

HOST = "127.0.0.1"
PORT = 5000
DATABASE = os.path.join(os.path.dirname(__file__), "users.sqlite3")
PBKDF2_ROUNDS = 310_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,24}$")
clients = {}  # socket -> authenticated username
clients_lock = threading.Lock()


def initialize_database():
    with sqlite3.connect(DATABASE) as db:
        db.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY COLLATE NOCASE, salt BLOB NOT NULL, password_hash BLOB NOT NULL)")


def authenticate(line):
    """Return (username, error). Auth wire format: REGISTER|LOGIN username password."""
    fields = line.strip().split(maxsplit=2)
    if len(fields) != 3 or fields[0] not in ("REGISTER", "LOGIN") or not fields[2]:
        return None, "Use REGISTER or LOGIN followed by username and password."
    action, username, password = fields
    if not USERNAME_RE.fullmatch(username):
        return None, "Username must be 3-24 letters, numbers, or underscores."
    if not 10 <= len(password) <= 128:
        return None, "Password must be 10-128 characters."

    with sqlite3.connect(DATABASE, timeout=10) as db:
        row = db.execute("SELECT username, salt, password_hash FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if action == "REGISTER":
            if row:
                return None, "That username is already registered."
            salt = os.urandom(16)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
            try:
                db.execute("INSERT INTO users VALUES (?, ?, ?)", (username, salt, digest))
            except sqlite3.IntegrityError:
                return None, "That username is already registered."
            return username, None
        if not row:
            return None, "Invalid username or password."
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), row[1], PBKDF2_ROUNDS)
        if not hmac.compare_digest(digest, row[2]):
            return None, "Invalid username or password."
        return row[0], None


def remove_client(sock):
    with clients_lock:
        username = clients.pop(sock, None)
    try:
        sock.close()
    except OSError:
        pass
    if username:
        broadcast(f"* {username} disconnected\n", exclude=None)


def broadcast(message, exclude):
    data = message.encode("utf-8")
    with clients_lock:
        recipients = [sock for sock in clients if sock is not exclude]
    for sock in recipients:
        try:
            sock.sendall(data)
        except OSError:
            remove_client(sock)


def handle_client(sock, address):
    username = None
    try:
        sock.sendall(b"Welcome. Send REGISTER username password or LOGIN username password.\n")
        stream = sock.makefile("r", encoding="utf-8", errors="replace")
        while True:
            line = stream.readline()
            if not line:
                return
            username, error = authenticate(line)
            if error:
                sock.sendall((f"AUTH_ERROR {error}\n").encode())
                continue
            break
        with clients_lock:
            clients[sock] = username
        sock.sendall(f"AUTH_OK Welcome, {username}. Messages can now be sent.\n".encode())
        broadcast(f"* {username} joined the chat\n", exclude=sock)

        for line in stream:
            message = line.rstrip("\r\n")
            if not message:
                continue
            if len(message.encode("utf-8")) > 4096:
                sock.sendall(b"Message too long (maximum 4096 bytes).\n")
                continue
            print(f"{username}@{address}: {message}")
            broadcast(f"{username}: {message}\n", exclude=sock)
    except (OSError, UnicodeError):
        pass
    finally:
        if username:
            remove_client(sock)
        else:
            try:
                sock.close()
            except OSError:
                pass


def main():
    initialize_database()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Server started on {HOST}:{PORT} (pid {os.getpid()})")
    try:
        while True:
            sock, address = server.accept()
            threading.Thread(target=handle_client, args=(sock, address), daemon=True).start()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.close()
        with clients_lock:
            active = list(clients)
        for sock in active:
            sock.close()


if __name__ == "__main__":
    main()
