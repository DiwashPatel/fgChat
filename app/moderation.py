"""Meeting and participant media policy overrides."""
import asyncio
import threading


MEDIA_CAPABILITIES = ("microphone", "camera", "screen_share")


class ModerationStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._policy_locks: dict[str, asyncio.Lock] = {}
        # meeting_id -> participant identity -> capability -> explicit override
        self._overrides: dict[str, dict[str, dict[str, bool]]] = {}

    def policy_lock(self, meeting_id: str) -> asyncio.Lock:
        with self._lock:
            return self._policy_locks.setdefault(meeting_id, asyncio.Lock())

    def effective_policy(
        self,
        meeting_id: str,
        participant_id: str,
        defaults: dict[str, bool],
    ) -> dict[str, bool]:
        with self._lock:
            overrides = self._overrides.get(meeting_id, {}).get(participant_id, {})
            return {
                capability: overrides.get(capability, defaults[capability])
                for capability in MEDIA_CAPABILITIES
            }

    def participant_overrides(self, meeting_id: str, participant_id: str) -> dict[str, bool]:
        with self._lock:
            return dict(self._overrides.get(meeting_id, {}).get(participant_id, {}))

    def set_participant_policy(
        self,
        meeting_id: str,
        participant_id: str,
        capability: str,
        allowed: bool | None,
    ):
        with self._lock:
            meeting_overrides = self._overrides.setdefault(meeting_id, {})
            participant_overrides = meeting_overrides.setdefault(participant_id, {})
            if allowed is None:
                participant_overrides.pop(capability, None)
                if not participant_overrides:
                    meeting_overrides.pop(participant_id, None)
                if not meeting_overrides:
                    self._overrides.pop(meeting_id, None)
            else:
                participant_overrides[capability] = allowed

    def clear_participant(self, meeting_id: str, participant_id: str):
        with self._lock:
            meeting_overrides = self._overrides.get(meeting_id)
            if meeting_overrides is not None:
                meeting_overrides.pop(participant_id, None)

    def clear_meeting(self, meeting_id: str):
        with self._lock:
            self._overrides.pop(meeting_id, None)


moderation_store = ModerationStore()
