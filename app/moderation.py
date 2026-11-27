"""Meeting-scoped moderation policy, independent of HTTP and LiveKit SDK."""
import threading


class ModerationStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._restrictions = {}  # meeting_id -> set of participant identities

    def microphone_allowed(self, meeting_id: str, participant_id: str) -> bool:
        with self._lock:
            return participant_id not in self._restrictions.get(meeting_id, set())

    def set_microphone_allowed(self, meeting_id: str, participant_id: str, allowed: bool):
        with self._lock:
            restricted = self._restrictions.setdefault(meeting_id, set())
            if allowed:
                restricted.discard(participant_id)
            else:
                restricted.add(participant_id)

    def clear_participant(self, meeting_id: str, participant_id: str):
        with self._lock:
            self._restrictions.get(meeting_id, set()).discard(participant_id)

    def clear_meeting(self, meeting_id: str):
        with self._lock:
            self._restrictions.pop(meeting_id, None)


moderation_store = ModerationStore()
