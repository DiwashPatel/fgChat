"""Authenticated host moderation endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from livekit import api

from app.meetings import meeting_manager
from app.moderation import moderation_store
from app.livekit_service import (
    list_livekit_participants, restrict_microphone, remove_livekit_participant,
)

router = APIRouter(prefix="/meetings/{meeting_id}/moderation", tags=["moderation"])


class HostAction(BaseModel):
    host_secret: str


class MicrophoneAction(HostAction):
    allowed: bool


def require_host(meeting_id: str, secret: str):
    meeting = meeting_manager.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    if not meeting_manager.is_host(meeting_id, secret):
        raise HTTPException(403, "Host credential required")
    if meeting["status"] != "created":
        raise HTTPException(409, "Meeting is not open")


async def require_guest(meeting_id: str, participant_id: str):
    try:
        participants = await list_livekit_participants(meeting_id)
    except api.TwirpError as exc:
        raise HTTPException(502, "Unable to retrieve LiveKit participants") from exc
    target = next((p for p in participants if p.identity == participant_id), None)
    if target is None:
        raise HTTPException(404, "Participant is not connected")
    # Host identity is not currently recorded in the meeting model; protect
    # it using a dedicated host-identity registry introduced below.
    if participant_id == host_identities.get(meeting_id):
        raise HTTPException(403, "Cannot moderate the host")
    return target


# LiveKit identity of the authenticated host, set when host obtains join credentials.
host_identities: dict[str, str] = {}


@router.post("/participants")
async def participants(meeting_id: str, body: HostAction):
    require_host(meeting_id, body.host_secret)
    try:
        users = await list_livekit_participants(meeting_id)
    except api.TwirpError as exc:
        if exc.code == "not_found":
            return {"participants": []}
        raise HTTPException(502, "Unable to retrieve participants") from exc
    return {"participants": [
        {"id": p.identity, "name": p.name or "Participant",
         "microphone_allowed": moderation_store.microphone_allowed(meeting_id, p.identity)}
        for p in users if p.identity != host_identities.get(meeting_id)
    ]}


@router.post("/participants/{participant_id}/microphone")
async def microphone(meeting_id: str, participant_id: str, body: MicrophoneAction):
    require_host(meeting_id, body.host_secret)
    await require_guest(meeting_id, participant_id)
    try:
        await restrict_microphone(meeting_id, participant_id, body.allowed)
    except api.TwirpError as exc:
        raise HTTPException(502, "LiveKit could not update permissions") from exc
    moderation_store.set_microphone_allowed(meeting_id, participant_id, body.allowed)
    return {"participant_id": participant_id, "microphone_allowed": body.allowed}


@router.post("/participants/{participant_id}/remove")
async def remove(meeting_id: str, participant_id: str, body: HostAction):
    require_host(meeting_id, body.host_secret)
    await require_guest(meeting_id, participant_id)
    try:
        await remove_livekit_participant(meeting_id, participant_id)
    except api.TwirpError as exc:
        raise HTTPException(502, "LiveKit could not remove participant") from exc
    moderation_store.clear_participant(meeting_id, participant_id)
    return {"participant_id": participant_id, "removed": True}
