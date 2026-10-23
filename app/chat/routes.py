"""Authenticated chat pages and JSON APIs."""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.chat import chat_bp
from app.extensions import db, socketio
from app.models import Conversation, ConversationMember, Message, User

PAGE_SIZE = 50


def conversation_for_user(conversation_id: int) -> Conversation | None:
    return db.session.scalar(
        db.select(Conversation)
        .options(joinedload(Conversation.user_a), joinedload(Conversation.user_b))
        .where(
            Conversation.id == conversation_id,
            Conversation.memberships.any(ConversationMember.user_id == current_user.id),
        )
    )


@chat_bp.get("/chat")
@login_required
def index():
    return render_template("index.html")


@chat_bp.get("/api/me")
@login_required
def me():
    return jsonify(user=current_user.public_profile())


@chat_bp.get("/api/users")
@login_required
def search_users():
    query = request.args.get("q", "").strip()[:80]
    if len(query) < 2:
        return jsonify(users=[])
    pattern = f"%{query}%"
    users = db.session.scalars(
        db.select(User)
        .where(
            User.id != current_user.id,
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
        )
        .order_by(User.display_name, User.username)
        .limit(20)
    ).all()
    from app.chat.events import state

    online_ids = {user.id for user in users if state.online(user.id)}
    return jsonify(
        users=[{**user.public_profile(), "online": user.id in online_ids} for user in users]
    )


@chat_bp.get("/api/conversations")
@login_required
def conversations():
    items = db.session.scalars(
        db.select(Conversation)
        .options(joinedload(Conversation.user_a), joinedload(Conversation.user_b))
        .where(Conversation.memberships.any(ConversationMember.user_id == current_user.id))
    ).all()
    ids = [item.id for item in items]
    latest_by_conversation = {}
    unread_by_conversation = {}
    if ids:
        latest_rows = db.session.execute(
            db.text("""
            SELECT m.id, m.conversation_id
            FROM messages m
            JOIN (
                SELECT conversation_id, MAX(id) AS latest_id
                FROM messages WHERE conversation_id IN :conversation_ids
                GROUP BY conversation_id
            ) latest ON latest.latest_id = m.id
        """).bindparams(db.bindparam("conversation_ids", expanding=True)),
            {"conversation_ids": ids},
        ).all()
        latest_ids = [row.id for row in latest_rows]
        if latest_ids:
            latest_messages = db.session.scalars(
                db.select(Message)
                .options(joinedload(Message.sender))
                .where(Message.id.in_(latest_ids))
            ).all()
            latest_by_conversation = {
                message.conversation_id: message for message in latest_messages
            }
        unread_rows = db.session.execute(
            db.select(Message.conversation_id, func.count(Message.id))
            .where(
                Message.conversation_id.in_(ids),
                Message.sender_id != current_user.id,
                Message.read_at.is_(None),
            )
            .group_by(Message.conversation_id)
        ).all()
        unread_by_conversation = dict(unread_rows)

    from app.chat.events import state

    result = []
    for conversation in items:
        peer = conversation.peer_for(current_user.id)
        latest = latest_by_conversation.get(conversation.id)
        result.append(
            {
                "id": conversation.id,
                "peer": {**peer.public_profile(), "online": state.online(peer.id)},
                "last_message": latest.public_message() if latest else None,
                "unread_count": unread_by_conversation.get(conversation.id, 0),
            }
        )
    result.sort(
        key=lambda item: item["last_message"]["created_at"] if item["last_message"] else "",
        reverse=True,
    )
    return jsonify(conversations=result)


@chat_bp.post("/api/conversations")
@login_required
def create_conversation():
    data = request.get_json(silent=True) or {}
    target = data.get("user_id")
    try:
        target_id = int(target)
    except (TypeError, ValueError):
        return jsonify(error="Choose a valid user."), 400
    if target_id == current_user.id:
        return jsonify(error="You cannot start a conversation with yourself."), 400
    peer = db.session.get(User, target_id)
    if peer is None:
        return jsonify(error="That user could not be found."), 404
    low_id, high_id = sorted((current_user.id, peer.id))
    conversation = db.session.scalar(
        db.select(Conversation).where(
            Conversation.user_a_id == low_id, Conversation.user_b_id == high_id
        )
    )
    if conversation is None:
        conversation = Conversation(user_a_id=low_id, user_b_id=high_id)
        conversation.memberships = [
            ConversationMember(user_id=low_id),
            ConversationMember(user_id=high_id),
        ]
        db.session.add(conversation)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            conversation = db.session.scalar(
                db.select(Conversation).where(
                    Conversation.user_a_id == low_id, Conversation.user_b_id == high_id
                )
            )
    if not conversation.includes(current_user.id):
        return jsonify(error="Conversation not found."), 404
    return jsonify(conversation={"id": conversation.id, "peer": peer.public_profile()}), 200


@chat_bp.get("/api/conversations/<int:conversation_id>/messages")
@login_required
def messages(conversation_id: int):
    conversation = conversation_for_user(conversation_id)
    if conversation is None:
        return jsonify(error="Conversation not found."), 404
    before = request.args.get("before", type=int)
    query = (
        db.select(Message)
        .options(joinedload(Message.sender))
        .where(Message.conversation_id == conversation.id)
    )
    if before:
        query = query.where(Message.id < before)
    batch = db.session.scalars(query.order_by(Message.id.desc()).limit(PAGE_SIZE + 1)).all()
    has_more = len(batch) > PAGE_SIZE
    selected = list(reversed(batch[:PAGE_SIZE]))
    if not before:
        unread = db.session.scalars(
            db.select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_id != current_user.id,
                Message.read_at.is_(None),
            )
        ).all()
        for message in unread:
            message.read_at = message.created_at
        if unread:
            db.session.commit()
            receipt = {
                "conversation_id": conversation.id,
                "message_ids": [message.id for message in unread],
            }
            socketio.emit("message:read_receipt", receipt, to=f"user:{conversation.user_a_id}")
            socketio.emit("message:read_receipt", receipt, to=f"user:{conversation.user_b_id}")
    next_cursor = selected[0].id if has_more and selected else None
    return jsonify(
        messages=[message.public_message() for message in selected],
        has_more=has_more,
        next_cursor=next_cursor,
    )


@chat_bp.get("/api/calls/config")
@login_required
def call_config():
    ice_servers = [{"urls": ["stun:stun.l.google.com:19302"]}]
    turn_url = current_app.config.get("TURN_URL")
    if turn_url:
        shared_secret = current_app.config.get("TURN_SHARED_SECRET")
        if shared_secret:
            expiry = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
            turn_username = f"{expiry}:{current_user.id}"
            turn_credential = base64.b64encode(
                hmac.new(shared_secret.encode(), turn_username.encode(), hashlib.sha1).digest()
            ).decode()
        else:
            turn_username = current_app.config.get("TURN_USERNAME")
            turn_credential = current_app.config.get("TURN_CREDENTIAL")
        ice_servers.append(
            {
                "urls": [turn_url],
                "username": turn_username,
                "credential": turn_credential,
            }
        )
    return jsonify(ice_servers=ice_servers)
