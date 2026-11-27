"""Authenticated host moderation endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from livekit import api

from app.meetings import meeting_manager
from app.moderation import MEDIA_CAPABILITIES, moderation_store
from app.livekit_service import (
    list_livekit_participants, update_participant_media_policy,
    remove_livekit_participant,
)

router = APIRouter(prefix="/meetings/{meeting_id}/moderation", tags=["moderation"])


class HostAction(BaseModel):
    host_secret: str


class MeetingMediaPolicy(HostAction):
    microphone: bool
    camera: bool
    screen_share: bool


class ParticipantMediaPolicy(HostAction):
    capability: str
    allowed: bool | None


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
    defaults = meeting_manager.get_media_policy(meeting_id)
    try:
        users = await list_livekit_participants(meeting_id)
    except api.TwirpError as exc:
        if exc.code == "not_found":
            return {"participants": []}
        raise HTTPException(502, "Unable to retrieve participants") from exc
    return {
        "meeting_policy": defaults,
        "participants": [
            {
                "id": participant.identity,
                "name": participant.name or "Participant",
                "media_policy": moderation_store.effective_policy(
                    meeting_id, participant.identity, defaults,
                ),
                "overrides": moderation_store.participant_overrides(
                    meeting_id, participant.identity,
                ),
            }
            for participant in users
            if participant.identity != host_identities.get(meeting_id)
        ],
    }


@router.post("/policy")
async def update_meeting_policy(meeting_id: str, body: MeetingMediaPolicy):
    require_host(meeting_id, body.host_secret)
    async with moderation_store.policy_lock(meeting_id):
        previous = meeting_manager.get_media_policy(meeting_id)
        next_policy = {
            "microphone": body.microphone,
            "camera": body.camera,
            "screen_share": body.screen_share,
        }
        try:
            users = await list_livekit_participants(meeting_id)
        except api.TwirpError as exc:
            raise HTTPException(502, "LiveKit could not update permissions") from exc

        updated = []
        try:
            for participant in users:
                if participant.identity == host_identities.get(meeting_id):
                    continue
                identity = participant.identity
                previous_effective = moderation_store.effective_policy(
                    meeting_id, identity, previous,
                )
                next_effective = moderation_store.effective_policy(
                    meeting_id, identity, next_policy,
                )
                await update_participant_media_policy(meeting_id, identity, next_effective)
                updated.append((identity, previous_effective))
        except api.TwirpError as exc:
            rollback_failed = False
            for identity, previous_effective in reversed(updated):
                try:
                    await update_participant_media_policy(meeting_id, identity, previous_effective)
                except api.TwirpError:
                    rollback_failed = True
            detail = "LiveKit could not update permissions"
            if rollback_failed:
                detail += "; some participants may need a permission refresh"
            raise HTTPException(502, detail) from exc

        meeting_manager.set_media_policy(meeting_id, next_policy)
        return {"meeting_policy": next_policy}


@router.post("/participants/{participant_id}/policy")
async def update_participant_policy(
    meeting_id: str,
    participant_id: str,
    body: ParticipantMediaPolicy,
):
    require_host(meeting_id, body.host_secret)
    if body.capability not in MEDIA_CAPABILITIES:
        raise HTTPException(422, "Unsupported media capability")
    await require_guest(meeting_id, participant_id)
    async with moderation_store.policy_lock(meeting_id):
        defaults = meeting_manager.get_media_policy(meeting_id)
        overrides = moderation_store.participant_overrides(meeting_id, participant_id)
        if body.allowed is None:
            overrides.pop(body.capability, None)
        else:
            overrides[body.capability] = body.allowed
        effective = {
            capability: overrides.get(capability, defaults[capability])
            for capability in MEDIA_CAPABILITIES
        }
        try:
            await update_participant_media_policy(meeting_id, participant_id, effective)
        except api.TwirpError as exc:
            raise HTTPException(502, "LiveKit could not update permissions") from exc
        moderation_store.set_participant_policy(
            meeting_id, participant_id, body.capability, body.allowed,
        )
        return {
            "participant_id": participant_id,
            "media_policy": effective,
            "overrides": overrides,
        }


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
