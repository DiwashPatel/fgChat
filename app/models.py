"""Relational models for identities, direct conversations, and messages."""

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(24), nullable=False, index=True)
    display_name = db.Column(db.String(48), nullable=False)
    email = db.Column(db.String(254), nullable=True, index=True)
    password_hash = db.Column(db.String(256), nullable=True)
    auth_provider = db.Column(db.String(24), nullable=False, default="password")
    provider_subject = db.Column(db.String(255), nullable=True, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        db.Index("uq_users_username_lower", func.lower(username), unique=True),
        db.Index(
            "uq_users_email_lower",
            func.lower(email),
            unique=True,
            sqlite_where=email.is_not(None),
            postgresql_where=email.is_not(None),
        ),
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        return bool(self.password_hash and check_password_hash(self.password_hash, password))

    def public_profile(self) -> dict:
        return {"id": self.id, "username": self.username, "display_name": self.display_name}


class Conversation(db.Model):
    __tablename__ = "conversations"
    __table_args__ = (
        db.UniqueConstraint("user_a_id", "user_b_id", name="uq_conversation_pair"),
        db.CheckConstraint("user_a_id < user_b_id", name="ck_conversation_sorted_pair"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_a_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_b_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    user_a = db.relationship(User, foreign_keys=[user_a_id])
    user_b = db.relationship(User, foreign_keys=[user_b_id])
    memberships = db.relationship(
        "ConversationMember", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages = db.relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
        lazy="select",
    )

    def includes(self, user_id: int) -> bool:
        return any(member.user_id == user_id for member in self.memberships)

    def peer_for(self, user_id: int) -> User:
        return self.user_b if user_id == self.user_a_id else self.user_a


class ConversationMember(db.Model):
    __tablename__ = "conversation_members"
    __table_args__ = (db.Index("ix_conversation_members_user", "user_id", "conversation_id"),)

    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    conversation = db.relationship(Conversation, back_populates="memberships")


class Message(db.Model):
    __tablename__ = "messages"
    __table_args__ = (db.Index("ix_message_conversation_created", "conversation_id", "id"),)

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body = db.Column(db.String(4000), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    conversation = db.relationship(Conversation, back_populates="messages")
    sender = db.relationship(User)

    def public_message(self) -> dict:
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "sender_id": self.sender_id,
            "sender": self.sender.display_name,
            "body": self.body,
            "created_at": created.isoformat(),
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }
