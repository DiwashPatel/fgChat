
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.meetings import meeting_manager
from app.livekit_service import (
    generate_join_credentials,
    delete_livekit_room,
)


BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="fgChat")

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates"
)


class JoinRequest(BaseModel):
    display_name: str = Field(
        min_length=1,
        max_length=100,
    )


class EndMeetingRequest(BaseModel):
    host_secret: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
    )


@app.post("/meetings")
def create_meeting(request: Request):
    result = meeting_manager.create_meeting()

    meeting_url = str(
        request.url_for(
            "get_meeting_page",
            meeting_id=result["meeting_id"],
        )
    )

    return {
        "meeting_id": result["meeting_id"],
        "meeting_url": meeting_url,
        "host_secret": result["host_secret"],
    }


@app.get(
    "/meetings/{meeting_id}",
    response_class=HTMLResponse,
)
def get_meeting_page(
    request: Request,
    meeting_id: str,
):
    meeting = meeting_manager.get_meeting(meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    return templates.TemplateResponse(
        request=request,
        name="meeting.html",
        context={"meeting_id": meeting_id},
    )


@app.get("/api/meetings/{meeting_id}")
def get_meeting_info(meeting_id: str):
    meeting = meeting_manager.get_meeting(meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    return meeting


@app.post("/meetings/{meeting_id}/join")
def join_meeting(
    meeting_id: str,
    request: JoinRequest,
):
    meeting = meeting_manager.get_meeting(meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    if meeting["status"] != "created":
        raise HTTPException(
            status_code=409,
            detail="Meeting is no longer accepting participants",
        )

    credentials = generate_join_credentials(
        meeting_id=meeting_id,
        display_name=request.display_name,
    )

    return {
        "meeting_id": meeting_id,
        "participant_id": credentials["participant_id"],
        "token": credentials["token"],
        "server_url": "ws://localhost:7880",
    }


@app.post("/meetings/{meeting_id}/end")
async def end_meeting(
    meeting_id: str,
    request: EndMeetingRequest,
):
    meeting = meeting_manager.get_meeting(meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    if not meeting_manager.is_host(
        meeting_id,
        request.host_secret,
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the host can end this meeting",
        )

    if meeting["status"] == "ended":
        return {"status": "ended"}

    if not meeting_manager.begin_ending(meeting_id):
        raise HTTPException(
            status_code=409,
            detail="Meeting termination is already in progress",
        )

    try:
        await delete_livekit_room(meeting_id)

    except Exception:
        meeting_manager.cancel_ending(meeting_id)

        raise HTTPException(
            status_code=502,
            detail="Unable to terminate LiveKit room",
        )

    meeting_manager.finish_ending(meeting_id)

    return {"status": "ended"}
