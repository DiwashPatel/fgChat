"""Authenticated messaging, presence, and one-to-one voice signaling."""

import json
import os
import threading
import time
import uuid
from collections import defaultdict, deque

from flask import request
from flask_login import current_user
from flask_socketio import emit, join_room, leave_room

from app.extensions import db
from app.models import Conversation, Message, User, utcnow


class RealtimeState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sid_users: dict[str, int] = {}
        self.user_sids: dict[int, set[str]] = defaultdict(set)
        self.calls: dict[str, tuple[int, int]] = {}
        self.user_calls: dict[int, str] = {}
        self.accepted_calls: set[str] = set()
        self.message_events: dict[int, deque] = defaultdict(deque)
        self.redis = None
        redis_url = os.environ.get("FGCHAT_SOCKETIO_REDIS_URL")
        if redis_url:
            from redis import Redis

            self.redis = Redis.from_url(redis_url, decode_responses=True)

    def online(self, user_id: int) -> bool:
        if self.redis:
            return bool(self.redis.scard(self._online_key(user_id)))
        with self.lock:
            return bool(self.user_sids.get(user_id))

    def add_session(self, user_id: int, sid: str) -> bool:
        if self.redis:
            key = self._online_key(user_id)
            was_online = bool(self.redis.scard(key))
            pipe = self.redis.pipeline()
            pipe.sadd(key, sid)
            pipe.expire(key, 90)
            pipe.execute()
            with self.lock:
                self.sid_users[sid] = user_id
            return was_online
        with self.lock:
            was_online = bool(self.user_sids[user_id])
            self.user_sids[user_id].add(sid)
            self.sid_users[sid] = user_id
            return was_online

    def touch_session(self, user_id: int, call_id: str | None = None) -> None:
        if self.redis:
            self.redis.expire(self._online_key(user_id), 90)
            if call_id:
                pair = self.get_call(call_id)
                if pair and user_id in pair:
                    self.redis.expire(self._call_key(call_id), 90)
                    for member_id in pair:
                        self.redis.expire(self._user_call_key(member_id), 90)

    def remove_session(self, sid: str) -> tuple[int | None, bool]:
        with self.lock:
            user_id = self.sid_users.pop(sid, None)
            if user_id is None:
                return None, False
            if self.redis:
                key = self._online_key(user_id)
                self.redis.srem(key, sid)
                count = self.redis.scard(key)
                if count:
                    self.redis.expire(key, 90)
                else:
                    self.redis.delete(key)
                return user_id, count == 0
            sessions = self.user_sids.get(user_id, set())
            sessions.discard(sid)
            if sessions:
                return user_id, False
            self.user_sids.pop(user_id, None)
            return user_id, True

    def allow_message(self, user_id: int) -> bool:
        now = time.time()
        if self.redis:
            key = f"fgchat:message_rate:{user_id}"
            script = """
            local now = tonumber(ARGV[1])
            redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - 60)
            if redis.call('ZCARD', KEYS[1]) >= 60 then return 0 end
            redis.call('ZADD', KEYS[1], now, ARGV[2])
            redis.call('EXPIRE', KEYS[1], 120)
            return 1
            """
            return bool(self.redis.eval(script, 1, key, now, uuid.uuid4().hex))
        with self.lock:
            events = self.message_events[user_id]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= 60:
                return False
            events.append(now)
            return True

    def reserve_call(self, call_id: str, caller_id: int, peer_id: int) -> bool:
        if self.redis:
            script = """
            if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('EXISTS', KEYS[2]) == 1 then
                return 0
            end
            redis.call('SET', KEYS[1], ARGV[1], 'EX', 90)
            redis.call('SET', KEYS[2], ARGV[1], 'EX', 90)
            redis.call('SET', KEYS[3], ARGV[2], 'EX', 90)
            return 1
            """
            return bool(
                self.redis.eval(
                    script,
                    3,
                    self._user_call_key(caller_id),
                    self._user_call_key(peer_id),
                    self._call_key(call_id),
                    call_id,
                    json.dumps([caller_id, peer_id, False]),
                )
            )
        with self.lock:
            if caller_id in self.user_calls or peer_id in self.user_calls:
                return False
            self.calls[call_id] = (caller_id, peer_id)
            self.user_calls[caller_id] = call_id
            self.user_calls[peer_id] = call_id
            return True

    def accept_call(self, call_id: str, user_id: int) -> bool:
        if self.redis:
            script = """
            local value = redis.call('GET', KEYS[1])
            if not value then return 0 end
            local call = cjson.decode(value)
            if call[2] ~= tonumber(ARGV[1]) or call[3] then return 0 end
            call[3] = true
            redis.call('SET', KEYS[1], cjson.encode(call), 'EX', 90)
            return 1
            """
            return bool(self.redis.eval(script, 1, self._call_key(call_id), user_id))
        with self.lock:
            pair = self.calls.get(call_id)
            if not pair or pair[1] != user_id or call_id in self.accepted_calls:
                return False
            self.accepted_calls.add(call_id)
            return True

    def get_call(self, call_id: str) -> tuple[int, int] | None:
        if self.redis:
            result = self.redis.get(self._call_key(call_id))
            return tuple(json.loads(result)[:2]) if result else None
        with self.lock:
            return self.calls.get(call_id)

    def end_call(self, call_id: str) -> tuple[int, int] | None:
        if self.redis:
            script = """
            local pair = redis.call('GET', KEYS[1])
            if not pair then return false end
            local ids = cjson.decode(pair)
            local first_key = ARGV[1] .. ids[1]
            local second_key = ARGV[1] .. ids[2]
            if redis.call('GET', first_key) == ARGV[2] then redis.call('DEL', first_key) end
            if redis.call('GET', second_key) == ARGV[2] then redis.call('DEL', second_key) end
            redis.call('DEL', KEYS[1])
            return cjson.encode({ids[1], ids[2]})
            """
            result = self.redis.eval(
                script, 1, self._call_key(call_id), "fgchat:user_call:", call_id
            )
            return tuple(json.loads(result)) if result else None
        with self.lock:
            pair = self.calls.pop(call_id, None)
            self.accepted_calls.discard(call_id)
            if pair:
                for user_id in pair:
                    if self.user_calls.get(user_id) == call_id:
                        self.user_calls.pop(user_id, None)
            return pair

    def end_calls_for_user(self, user_id: int) -> list[tuple[str, tuple[int, int]]]:
        if self.redis:
            call_id = self.redis.get(self._user_call_key(user_id))
            if not call_id:
                return []
            pair = self.end_call(call_id)
            return [(call_id, pair)] if pair else []
        with self.lock:
            call_ids = [call_id for call_id, pair in self.calls.items() if user_id in pair]
        result = []
        for call_id in call_ids:
            pair = self.end_call(call_id)
            if pair:
                result.append((call_id, pair))
        return result

    @staticmethod
    def _online_key(user_id: int) -> str:
        return f"fgchat:online:{user_id}"

    @staticmethod
    def _user_call_key(user_id: int) -> str:
        return f"fgchat:user_call:{user_id}"

    @staticmethod
    def _call_key(call_id: str) -> str:
        return f"fgchat:call:{call_id}"


state = RealtimeState()


def register_socket_events(socketio) -> None:
    @socketio.on("connect")
    def connected(auth=None):
        if not current_user.is_authenticated:
            return False
        user_id = current_user.id
        was_online = state.add_session(user_id, request.sid)
        join_room(f"user:{user_id}")
        if not was_online:
            emit(
                "presence:changed",
                {"user_id": user_id, "online": True},
                broadcast=True,
                include_self=False,
            )

    @socketio.on("disconnect")
    def disconnected(reason=None):
        user_id, went_offline = state.remove_session(request.sid)
        if user_id is None:
            return
        if went_offline:
            emit("presence:changed", {"user_id": user_id, "online": False}, broadcast=True)
            for call_id, pair in state.end_calls_for_user(user_id):
                other_id = pair[1] if pair[0] == user_id else pair[0]
                emit(
                    "call:ended",
                    {"call_id": call_id, "reason": "disconnected"},
                    to=f"user:{other_id}",
                )

    @socketio.on("presence:heartbeat")
    def heartbeat(data=None):
        if current_user.is_authenticated:
            call_id = data.get("call_id") if isinstance(data, dict) else None
            state.touch_session(current_user.id, call_id if isinstance(call_id, str) else None)

    @socketio.on("conversation:join")
    def join_conversation(data):
        conversation_id = _positive_int(data, "conversation_id")
        if not conversation_id:
            return
        conversation = db.session.get(Conversation, conversation_id)
        if conversation and conversation.includes(current_user.id):
            join_room(f"conversation:{conversation_id}")

    @socketio.on("conversation:leave")
    def leave_conversation(data):
        conversation_id = _positive_int(data, "conversation_id")
        if conversation_id:
            leave_room(f"conversation:{conversation_id}")

    @socketio.on("message:send")
    def send_message_event(data):
        if not isinstance(data, dict):
            return _error("Invalid message.")
        conversation_id = _positive_int(data, "conversation_id")
        body = data.get("body")
        if not conversation_id or not isinstance(body, str):
            return _error("Write a message before sending.")
        body = body.strip()
        if not body or len(body.encode("utf-8")) > 4000:
            return _error("Messages must contain 1–4000 UTF-8 bytes.")
        conversation = db.session.get(Conversation, conversation_id)
        if conversation is None or not conversation.includes(current_user.id):
            return _error("Conversation not found.")
        if not state.allow_message(current_user.id):
            return _error("You're sending messages too quickly. Take a moment and try again.")
        message = Message(conversation_id=conversation.id, sender_id=current_user.id, body=body)
        db.session.add(message)
        db.session.commit()
        payload = message.public_message()
        for member_id in (conversation.user_a_id, conversation.user_b_id):
            emit("message:new", payload, to=f"user:{member_id}")

    @socketio.on("message:read")
    def mark_read(data):
        conversation_id = _positive_int(data, "conversation_id") if isinstance(data, dict) else None
        conversation = db.session.get(Conversation, conversation_id) if conversation_id else None
        if conversation is None or not conversation.includes(current_user.id):
            return
        unread = db.session.scalars(
            db.select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_id != current_user.id,
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
        emit("message:read_receipt", receipt, to=f"user:{conversation.user_a_id}")
        emit("message:read_receipt", receipt, to=f"user:{conversation.user_b_id}")

    @socketio.on("typing:set")
    def typing(data):
        conversation_id = _positive_int(data, "conversation_id") if isinstance(data, dict) else None
        conversation = db.session.get(Conversation, conversation_id) if conversation_id else None
        if conversation is None or not conversation.includes(current_user.id):
            return
        other_id = (
            conversation.user_b_id
            if current_user.id == conversation.user_a_id
            else conversation.user_a_id
        )
        emit(
            "typing:changed",
            {
                "conversation_id": conversation.id,
                "user_id": current_user.id,
                "typing": bool(data.get("typing")),
            },
            to=f"user:{other_id}",
        )

    @socketio.on("call:start")
    def call_start(data):
        peer_id = _positive_int(data, "peer_id") if isinstance(data, dict) else None
        if not peer_id or peer_id == current_user.id:
            return _error("Choose someone to call.")
        peer = db.session.get(User, peer_id)
        if peer is None:
            return _error("That user could not be found.")
        if not state.online(peer_id):
            return _error("This person is offline right now.")
        call_id = uuid.uuid4().hex
        if not state.reserve_call(call_id, current_user.id, peer_id):
            return _error("One of you is already on a call.")
        emit("call:outgoing", {"call_id": call_id, "peer": peer.public_profile()})
        emit(
            "call:incoming",
            {"call_id": call_id, "caller": current_user.public_profile()},
            to=f"user:{peer_id}",
        )

    @socketio.on("call:accept")
    def call_accept(data):
        call = _call_for_user(data, current_user.id)
        if call is None:
            return _error("This call is no longer available.")
        call_id, pair = call
        if pair[1] != current_user.id:
            return _error("Only the invited person can accept this call.")
        if not state.accept_call(call_id, current_user.id):
            return _error("This call has already been answered.")
        emit("call:accepted", {"call_id": call_id}, to=f"user:{pair[0]}")

    @socketio.on("call:reject")
    def call_reject(data):
        call = _end_call(data, current_user.id)
        if call:
            call_id, pair = call
            other_id = pair[1] if pair[0] == current_user.id else pair[0]
            emit("call:ended", {"call_id": call_id, "reason": "declined"}, to=f"user:{other_id}")

    @socketio.on("call:end")
    def call_end(data):
        call = _end_call(data, current_user.id)
        if call:
            call_id, pair = call
            other_id = pair[1] if pair[0] == current_user.id else pair[0]
            emit("call:ended", {"call_id": call_id, "reason": "ended"}, to=f"user:{other_id}")

    @socketio.on("call:signal")
    def call_signal(data):
        if not isinstance(data, dict) or not _valid_signal(data.get("payload")):
            return
        call = _call_for_user(data, current_user.id)
        if call is None:
            return
        call_id, pair = call
        other_id = pair[1] if pair[0] == current_user.id else pair[0]
        emit("call:signal", {"call_id": call_id, "payload": data["payload"]}, to=f"user:{other_id}")


def _valid_signal(payload) -> bool:
    if not isinstance(payload, dict) or len(payload) != 1:
        return False
    if isinstance(payload.get("description"), dict):
        description = payload["description"]
        return (
            description.get("type") in ("offer", "answer")
            and isinstance(description.get("sdp"), str)
            and len(description["sdp"]) <= 16_000
        )
    if isinstance(payload.get("candidate"), dict):
        candidate = payload["candidate"].get("candidate", "")
        return isinstance(candidate, str) and len(candidate) <= 4_000
    return False


def _positive_int(data: dict, key: str) -> int | None:
    try:
        value = int(data.get(key))
        return value if value > 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def _error(message: str):
    emit("app:error", {"message": message})


def _call_for_user(data: dict, user_id: int):
    if not isinstance(data, dict) or not isinstance(data.get("call_id"), str):
        return None
    call_id = data["call_id"]
    pair = state.get_call(call_id)
    return (call_id, pair) if pair and user_id in pair else None


def _end_call(data: dict, user_id: int):
    call = _call_for_user(data, user_id)
    if call:
        pair = state.end_call(call[0])
        return (call[0], pair) if pair else None
    return None
