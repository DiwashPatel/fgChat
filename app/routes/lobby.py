"""HTTP admission operations and authenticated application WebSockets."""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from app.meetings import meeting_manager
from app.lobby import lobby_manager, LobbyError
from app.lobby_connections import lobby_connections

router = APIRouter(prefix='/meetings/{meeting_id}', tags=['lobby'])


class AdmissionRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class GuestCredential(BaseModel):
    request_secret: str


class HostDecision(BaseModel):
    host_secret: str
    approve: bool


def require_open(meeting_id):
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, 'Meeting not found')
    if meeting['status'] != 'created':
        raise HTTPException(409, 'Meeting is no longer open')


def require_host(meeting_id, secret):
    if not meeting_manager.is_host(meeting_id, secret):
        raise HTTPException(403, 'Host credential required')


@router.post('/admissions')
async def request_admission(meeting_id: str, body: AdmissionRequest):
    require_open(meeting_id)
    if not body.display_name.strip():
        raise HTTPException(422, 'Display name cannot be blank')
    result = lobby_manager.request(meeting_id, body.display_name.strip())
    await lobby_connections.host_event(meeting_id, {'type': 'lobby.changed', 'pending': lobby_manager.snapshot(meeting_id)})
    return result


@router.post('/admissions/{request_id}/status')
def admission_status(meeting_id: str, request_id: str, body: GuestCredential):
    try:
        return lobby_manager.status(meeting_id, request_id, body.request_secret)
    except LobbyError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.post('/admissions/{request_id}/cancel')
async def cancel_admission(meeting_id: str, request_id: str, body: GuestCredential):
    try:
        result = lobby_manager.cancel(meeting_id, request_id, body.request_secret)
    except LobbyError as error:
        raise HTTPException(error.status_code, str(error)) from error
    await lobby_connections.host_event(meeting_id, {'type': 'lobby.changed', 'pending': lobby_manager.snapshot(meeting_id)})
    return result


@router.post('/admissions/pending')
def pending_admissions(meeting_id: str, body: HostDecision):
    require_host(meeting_id, body.host_secret)
    return {'pending': lobby_manager.snapshot(meeting_id)}


@router.post('/admissions/{request_id}/decision')
async def decide_admission(meeting_id: str, request_id: str, body: HostDecision):
    require_open(meeting_id)
    require_host(meeting_id, body.host_secret)
    try:
        result = lobby_manager.decide(meeting_id, request_id, body.approve)
    except LobbyError as error:
        raise HTTPException(error.status_code, str(error)) from error
    await lobby_connections.guest_event(meeting_id, request_id, {'type': 'lobby.status', 'status': result['status']})
    await lobby_connections.host_event(meeting_id, {'type': 'lobby.changed', 'pending': lobby_manager.snapshot(meeting_id)})
    return result


@router.websocket('/lobby/ws')
async def lobby_socket(socket: WebSocket, meeting_id: str):
    # Authentication occurs in the first message, not the URL (avoids secret-bearing URLs).
    await socket.accept()
    role = None
    request_id = None
    try:
        auth = await socket.receive_json()
        role = auth.get('role')
        if role == 'host':
            if not meeting_manager.is_host(meeting_id, auth.get('host_secret', '')):
                await socket.close(code=1008)
                return
        elif role == 'guest':
            request_id = auth.get('request_id', '')
            try:
                lobby_manager.status(meeting_id, request_id, auth.get('request_secret', ''))
            except LobbyError:
                await socket.close(code=1008)
                return
        else:
            await socket.close(code=1008)
            return
        await lobby_connections.add(role, meeting_id, socket, request_id)
        if role == 'host':
            await socket.send_json({'type': 'lobby.changed', 'pending': lobby_manager.snapshot(meeting_id)})
        else:
            result = lobby_manager.status(meeting_id, request_id, auth['request_secret'])
            await socket.send_json({'type': 'lobby.status', 'status': result['status']})
        while True:
            await socket.receive_text()  # Keep connection alive; commands use authenticated HTTP.
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if role in ('host', 'guest'):
            await lobby_connections.remove(role, meeting_id, socket, request_id)
