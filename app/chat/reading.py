"""Shared read handling for HTTP history and realtime messages."""

from app.extensions import db, socketio
from app.models import ConversationMember, Message, utcnow


def mark_conversation_read(conversation, user_id):
    if conversation.is_group:
        member = db.session.get(ConversationMember, (conversation.id, user_id))
        latest_id = (
            db.session.scalar(
                db.select(db.func.max(Message.id)).where(Message.conversation_id == conversation.id)
            )
            or 0
        )
        member.last_read_message_id = max(member.last_read_message_id, latest_id)
        db.session.commit()
        return

    unread = db.session.scalars(
        db.select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_id != user_id,
            Message.read_at.is_(None),
        )
    ).all()
    if not unread:
        return
    for message in unread:
        message.read_at = utcnow()
    db.session.commit()
    receipt = {
        "conversation_id": conversation.id,
        "message_ids": [message.id for message in unread],
    }
    for member in conversation.memberships:
        socketio.emit("message:read_receipt", receipt, to=f"user:{member.user_id}")
