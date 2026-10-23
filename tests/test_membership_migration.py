"""Backfill direct-chat memberships without changing conversations or messages."""

from datetime import datetime, timezone

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import Conversation, ConversationMember, Message, User


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
            db.session.add_all(
                [
                    User(id=user_id, username=name, display_name=name.title())
                    for user_id, name in enumerate(("alice", "bobby", "charlie"), 1)
                ]
            )
            db.session.flush()
            db.session.add_all(
                [
                    Conversation(id=10, user_a_id=1, user_b_id=2),
                    Conversation(id=20, user_a_id=2, user_b_id=3),
                ]
            )
            db.session.flush()
            read_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            db.session.add_all(
                [
                    Message(id=100, conversation_id=10, sender_id=1, body="Read", read_at=read_at),
                    Message(id=101, conversation_id=20, sender_id=3, body="Unread"),
                ]
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
            messages = db.session.scalars(db.select(Message).order_by(Message.id)).all()
            assert [(message.id, message.body) for message in messages] == [
                (100, "Read"),
                (101, "Unread"),
            ]
            assert messages[0].read_at.replace(tzinfo=timezone.utc) == read_at
            assert messages[1].read_at is None
        finally:
            db.session.remove()
            db.engine.dispose()
