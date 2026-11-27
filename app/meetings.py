import hashlib
import hmac
import secrets
import threading


class MeetingManager:

    def __init__(self):
        self.meetings = {}
        self.lock = threading.RLock() # can be thought of as Recursive Lock..(ReEntrant). Same lock can be reused again and again. it keeps a count...(analogy) 1 -> 2 -> 3..when done: 2 -> 1 -> 0 Free..

    def create_meeting(self, media_policy=None):
        meeting_id = secrets.token_urlsafe(16)
        host_secret = secrets.token_urlsafe(32)

        with self.lock:
            while meeting_id in self.meetings:
                meeting_id = secrets.token_urlsafe(16)

            self.meetings[meeting_id] = {
                "id": meeting_id,
                "status": "created",
                "media_policy": {
                    "microphone": True,
                    "camera": True,
                    "screen_share": True,
                    **(media_policy or {}),
                },
                "host_secret_hash": self._hash_secret(
                    host_secret
                ),
            }

        return {
            "meeting_id": meeting_id,
            "host_secret": host_secret,
        }

    def get_meeting(self, meeting_id: str):
        with self.lock:
            meeting = self.meetings.get(meeting_id)

            if meeting is None:
                return None

            return {
                "id": meeting["id"],
                "status": meeting["status"],
                "media_policy": dict(meeting["media_policy"]),
            }

    def set_media_policy(self, meeting_id: str, media_policy: dict[str, bool]):
        with self.lock:
            meeting = self.meetings[meeting_id]
            meeting["media_policy"] = dict(media_policy)

    def get_media_policy(self, meeting_id: str):
        with self.lock:
            meeting = self.meetings.get(meeting_id)
            return dict(meeting["media_policy"]) if meeting else None

    def is_host(self, meeting_id: str, host_secret: str):
        with self.lock:
            meeting = self.meetings.get(meeting_id)

            if meeting is None:
                return False

            supplied_hash = self._hash_secret(host_secret)

            return hmac.compare_digest(
                meeting["host_secret_hash"],
                supplied_hash,
            )

    # note: 3 states: created -> ending -> ended
    # ending is an intermediate state while fastAPI is requestign livekit to terminate the room.
    # if the livekit fails, we restore the previous state so the host can retry.
    # created means open to joining.


    def begin_ending(self, meeting_id: str):
        with self.lock:
            meeting = self.meetings[meeting_id]

            if meeting["status"] == "ended":
                return False

            if meeting["status"] == "ending":
                return False

            meeting["status"] = "ending"
            return True

    def finish_ending(self, meeting_id: str):
        with self.lock:
            self.meetings[meeting_id]["status"] = "ended"

    def cancel_ending(self, meeting_id: str):
        with self.lock:
            meeting = self.meetings[meeting_id]

            if meeting["status"] == "ending":
                meeting["status"] = "created"

    # Static Methods don't have self keyword as param. We can do like ClassnName.fn() or obj.fnName()
    @staticmethod
    def _hash_secret(secret: str):
        return hashlib.sha256(
            secret.encode("utf-8")
        ).hexdigest()


meeting_manager = MeetingManager()
