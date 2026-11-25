import secrets

class MeetingManager:

    def __init__(self):
        self.meetings = {}

    def create_meeting(self):
        meeting_id = secrets.token_urlsafe(16)

        while meeting_id in self.meetings:
            meeting_id = secrets.token_urlsafe(16)

        self.meetings[meeting_id] = {
            "id": meeting_id,
            "status": "created",
        }

        return self.meetings[meeting_id]

    def get_meeting(self, meeting_id: str):
        return self.meetings.get(meeting_id)


meeting_manager = MeetingManager()