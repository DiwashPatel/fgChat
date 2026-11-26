
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
