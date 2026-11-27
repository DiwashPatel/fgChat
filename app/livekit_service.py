
import os
import uuid

from livekit import api
from datetime import timedelta

LIVEKIT_API_KEY = os.getenv(
    "LIVEKIT_API_KEY",
    "devkey",
)

LIVEKIT_API_SECRET = os.getenv(
    "LIVEKIT_API_SECRET",
    "secret",
)

LIVEKIT_URL = os.getenv(
    "LIVEKIT_URL",
    "http://localhost:7880",
)


def generate_join_credentials(
    meeting_id: str,
    display_name: str,
    participant_id: str | None = None,
    allowed_sources: list[str] | None = None,
):
    participant_id = participant_id or str(uuid.uuid4())

    token = (
        api.AccessToken(
            LIVEKIT_API_KEY,
            LIVEKIT_API_SECRET,
        )
        .with_identity(participant_id)
        .with_name(display_name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=meeting_id,
                can_publish=True,
                can_subscribe=True,
                can_publish_sources=allowed_sources,
            )
        )
        .with_ttl(timedelta(seconds=300))
        .to_jwt()
    )

    return {
        "participant_id": participant_id,
        "token": token,
    }


async def delete_livekit_room(meeting_id: str):
    async with api.LiveKitAPI(
        url=LIVEKIT_URL,
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    ) as livekit:
        try:
            await livekit.room.delete_room(
                api.DeleteRoomRequest(room=meeting_id)
            )
        except api.TwirpError as error:
            # An already-absent room is effectively deleted.
            if error.code != "not_found":
                raise


async def list_livekit_participants(meeting_id: str):
    async with api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET) as client:
        response = await client.room.list_participants(api.ListParticipantsRequest(room=meeting_id))
        return response.participants


_TOKEN_SOURCES = {
    "microphone": "microphone",
    "camera": "camera",
    "screen_share": "screen_share",
    "screen_share_audio": "screen_share_audio",
}


def token_sources_for_policy(policy: dict[str, bool]) -> list[str]:
    sources = []
    for capability, source in _TOKEN_SOURCES.items():
        if capability == "screen_share_audio":
            allowed = policy["screen_share"]
        else:
            allowed = policy[capability]
        if allowed:
            sources.append(source)
    return sources


def _livekit_sources_for_policy(policy: dict[str, bool]):
    sources = []
    if policy["microphone"]:
        sources.append(api.TrackSource.MICROPHONE)
    if policy["camera"]:
        sources.append(api.TrackSource.CAMERA)
    if policy["screen_share"]:
        sources.extend((api.TrackSource.SCREEN_SHARE, api.TrackSource.SCREEN_SHARE_AUDIO))
    return sources


async def update_participant_media_policy(
    meeting_id: str,
    participant_id: str,
    policy: dict[str, bool],
):
    permission = api.ParticipantPermission(
        can_subscribe=True,
        can_publish=True,
        can_publish_data=True,
        can_publish_sources=_livekit_sources_for_policy(policy),
    )
    async with api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET) as client:
        return await client.room.update_participant(api.UpdateParticipantRequest(
            room=meeting_id, identity=participant_id, permission=permission,
        ))


async def remove_livekit_participant(meeting_id: str, participant_id: str):
    async with api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET) as client:
        return await client.room.remove_participant(api.RoomParticipantIdentity(room=meeting_id, identity=participant_id))
