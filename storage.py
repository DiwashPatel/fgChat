"""SQLite persistence for accounts and direct chat history."""

import hashlib
import hmac
import os
import sqlite3
import time
from pathlib import Path

PBKDF2_ROUNDS = 310_000


class ChatStore:
    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at INTEGER NOT NULL
            )""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
            if "created_at" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0")
            db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL COLLATE NOCASE,
                recipient TEXT NOT NULL COLLATE NOCASE,
                body TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS messages_conversation ON messages(sender, recipient, id)")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def register(self, username: str, password: str) -> bool:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
        try:
            with self.connect() as db:
                db.execute("INSERT INTO users(username, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                          (username, salt, digest, int(time.time())))
        except sqlite3.IntegrityError:
            return False
        return True

    def authenticate(self, username: str, password: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT username, salt, password_hash FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            hashlib.pbkdf2_hmac("sha256", password.encode(), b"\0" * 16, PBKDF2_ROUNDS)
            return None
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), row["salt"], PBKDF2_ROUNDS)
        return row["username"] if hmac.compare_digest(digest, row["password_hash"]) else None

    def user_exists(self, username: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None

    def save_message(self, sender: str, recipient: str, body: str) -> dict:
        created_at = int(time.time())
        with self.connect() as db:
            cursor = db.execute("INSERT INTO messages(sender, recipient, body, created_at) VALUES (?, ?, ?, ?)",
                                (sender, recipient, body, created_at))
            message_id = cursor.lastrowid
        return {"id": message_id, "sender": sender, "recipient": recipient,
                "body": body, "created_at": created_at}

    def history(self, first: str, second: str, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT id, sender, recipient, body, created_at FROM messages
                WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
                ORDER BY id DESC LIMIT ?""", (first, second, second, first, limit)).fetchall()
        return [dict(row) for row in reversed(rows)]
