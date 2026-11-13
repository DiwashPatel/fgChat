"""Backfill direct-chat memberships without changing conversations or messages."""

from datetime import datetime, timezone

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import Conversation, ConversationMember


def test_membership_migration_backfills_existing_chats_and_preserves_data(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'migration.sqlite3'}",
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        try:
            upgrade(revision="f2fe16aeb3f9")
            db.session.execute(
                db.text("""
                INSERT INTO users (id, username, display_name, auth_provider, created_at)
                VALUES (1, 'alice', 'Alice', 'password', CURRENT_TIMESTAMP),
                       (2, 'bobby', 'Bobby', 'password', CURRENT_TIMESTAMP),
                       (3, 'charlie', 'Charlie', 'password', CURRENT_TIMESTAMP)
            """)
            )
            # Seed the historical schema without today's ORM-only columns.
            db.session.execute(
                db.text("""
                INSERT INTO conversations (id, user_a_id, user_b_id, created_at)
                VALUES (10, 1, 2, CURRENT_TIMESTAMP), (20, 2, 3, CURRENT_TIMESTAMP)
            """)
            )
            db.session.flush()
            read_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            db.session.execute(
                db.text("""
                INSERT INTO messages (id, conversation_id, sender_id, body, created_at, read_at)
                VALUES (100, 10, 1, 'Read', CURRENT_TIMESTAMP, :read_at),
                       (101, 20, 3, 'Unread', CURRENT_TIMESTAMP, NULL)
            """),
                {"read_at": read_at},
            )
            db.session.commit()
            db.session.remove()

            upgrade()
            memberships = db.session.execute(
                db.select(ConversationMember.conversation_id, ConversationMember.user_id).order_by(
                    ConversationMember.conversation_id, ConversationMember.user_id
                )
            ).all()
            assert memberships == [(10, 1), (10, 2), (20, 2), (20, 3)]
            assert db.session.get(Conversation, 10).includes(1)
            assert db.session.get(Conversation, 20).includes(3)
            with pytest.raises(IntegrityError):
                db.session.execute(
                    db.insert(ConversationMember).values(conversation_id=10, user_id=1)
                )
            db.session.rollback()
            db.session.remove()

            downgrade(revision="f2fe16aeb3f9")
            assert db.session.execute(
                db.select(Conversation.id, Conversation.user_a_id, Conversation.user_b_id).order_by(
                    Conversation.id
                )
            ).all() == [(10, 1, 2), (20, 2, 3)]
            messages = db.session.execute(
                db.text("SELECT id, body, read_at FROM messages ORDER BY id")
            ).all()
            assert [(message.id, message.body) for message in messages] == [
                (100, "Read"),
                (101, "Unread"),
            ]
            assert (
                datetime.fromisoformat(messages[0].read_at).replace(tzinfo=timezone.utc) == read_at
            )
            assert messages[1].read_at is None
        finally:
            db.session.remove()
            db.engine.dispose()
