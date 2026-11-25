
import os
import uuid

from livekit import api


LIVEKIT_API_KEY = os.environ.get(
    "LIVEKIT_API_KEY",
    "devkey",
)

LIVEKIT_API_SECRET = os.environ.get(
    "LIVEKIT_API_SECRET",
    "secret",
)


def generate_join_credentials(
    meeting_id: str,
    display_name: str,
):
    participant_id = str(uuid.uuid4())

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
        .to_jwt()
    )

    return {
        "participant_id": participant_id,
        "token": token,
    }
