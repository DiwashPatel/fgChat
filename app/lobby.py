"""Meeting admission state. Replace this store with a transactional repository later."""
import hashlib
import hmac
import secrets
import threading
import time


class LobbyError(Exception):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


class LobbyManager:
    def __init__(self):
        self._requests = {}  # meeting_id -> request_id -> admission record
        self._lock = threading.RLock()

    @staticmethod
    def _digest(secret):
        return hashlib.sha256(secret.encode()).digest()

    def request(self, meeting_id, display_name):
        request_id = secrets.token_urlsafe(16)
        secret = secrets.token_urlsafe(32)
        record = {
            'request_id': request_id,
            'meeting_id': meeting_id,
            'display_name': display_name,
            'secret_hash': self._digest(secret),
            'status': 'pending',
            'created_at': time.time(),
            'participant_id': None,
        }
        with self._lock:
            self._requests.setdefault(meeting_id, {})[request_id] = record
        return {'request_id': request_id, 'request_secret': secret, 'status': 'pending'}

    def _find(self, meeting_id, request_id):
        record = self._requests.get(meeting_id, {}).get(request_id)
        if record is None:
            raise LobbyError('Admission request not found', 404)
        return record

    def _check_secret(self, record, secret):
        if not hmac.compare_digest(record['secret_hash'], self._digest(secret)):
            raise LobbyError('Invalid admission credential', 403)

    def snapshot(self, meeting_id):
        with self._lock:
            return [self._public(r) for r in self._requests.get(meeting_id, {}).values() if r['status'] == 'pending']

    @staticmethod
    def _public(record):
        return {key: record[key] for key in ('request_id', 'display_name', 'status')}

    def status(self, meeting_id, request_id, secret):
        with self._lock:
            record = self._find(meeting_id, request_id)
            self._check_secret(record, secret)
            return self._public(record)

    def decide(self, meeting_id, request_id, approve):
        with self._lock:
            record = self._find(meeting_id, request_id)
            if record['status'] != 'pending':
                raise LobbyError('Request has already been decided')
            record['status'] = 'approved' if approve else 'denied'
            return self._public(record)

    def cancel(self, meeting_id, request_id, secret):
        with self._lock:
            record = self._find(meeting_id, request_id)
            self._check_secret(record, secret)
            if record['status'] not in ('pending', 'approved'):
                raise LobbyError('Request cannot be cancelled')
            record['status'] = 'cancelled'
            return self._public(record)

    def consume(self, meeting_id, request_id, secret, participant_id):
        """Atomic approval exchange; one request cannot mint multiple tokens."""
        with self._lock:
            record = self._find(meeting_id, request_id)
            self._check_secret(record, secret)
            if record['status'] != 'approved':
                raise LobbyError('Admission has not been approved')
            record['status'] = 'consumed'
            record['participant_id'] = participant_id
            return record['display_name']

    def close_meeting(self, meeting_id):
        with self._lock:
            for record in self._requests.get(meeting_id, {}).values():
                if record['status'] in ('pending', 'approved'):
                    record['status'] = 'cancelled'


lobby_manager = LobbyManager()
