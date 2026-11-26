"""Transient application WebSockets; these are never database records."""
import asyncio
from fastapi import WebSocket


class LobbyConnections:
    def __init__(self):
        self.hosts = {}  # meeting_id -> set[WebSocket]
        self.guests = {}  # (meeting_id, request_id) -> set[WebSocket]
        self._lock = asyncio.Lock()

    async def add(self, role, meeting_id, socket, request_id=None):
        async with self._lock:
            registry = self.hosts if role == 'host' else self.guests
            key = meeting_id if role == 'host' else (meeting_id, request_id)
            registry.setdefault(key, set()).add(socket)

    async def remove(self, role, meeting_id, socket, request_id=None):
        async with self._lock:
            registry = self.hosts if role == 'host' else self.guests
            key = meeting_id if role == 'host' else (meeting_id, request_id)
            connections = registry.get(key)
            if connections:
                connections.discard(socket)
                if not connections:
                    registry.pop(key, None)

    async def _send(self, registry, key, message):
        async with self._lock:
            sockets = list(registry.get(key, ()))
        for socket in sockets:
            try:
                await socket.send_json(message)
            except Exception:
                # Disconnect handler will remove the socket.
                pass

    async def host_event(self, meeting_id, message):
        await self._send(self.hosts, meeting_id, message)

    async def guest_event(self, meeting_id, request_id, message):
        await self._send(self.guests, (meeting_id, request_id), message)

    async def meeting_ended(self, meeting_id):
        await self.host_event(meeting_id, {'type': 'meeting.ended'})
        async with self._lock:
            keys = [key for key in self.guests if key[0] == meeting_id]
        for key in keys:
            await self._send(self.guests, key, {'type': 'meeting.ended'})


lobby_connections = LobbyConnections()
