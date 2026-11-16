from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
import secrets
from fastapi import WebSocket, WebSocketDisconnect, WebSocketException, status
from fastapi.templating import Jinja2Templates
import base64
import hashlib
import hmac
import time
import secrets
import os 
from fastapi.staticfiles import StaticFiles
import httpx

TURN_SHARED_SECRET = os.environ["TURN_SHARED_SECRET"]
TURN_CREDENTIAL_LIFETIME = 3600
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
BASE_URL = f"https://voice.newnet.dev"
# BASE_URL = f"http://127.0.0.1/8000"
MEETING_BASE = BASE_URL + "/" + "meetings"

templates = Jinja2Templates(directory="templates")

db = {} # meeting link to people connected.

@app.get("/")
def get_homepage():
    return FileResponse(f"index.html")

@app.post("/create_meeting")
def create_meeting_link(request: Request):

    while True:
        token = secrets.token_urlsafe(16)
        if token not in db:
            break
    db[token] = []
    meeting_link = str(
        request.url_for(
            "get_meeting_page",
            meeting_id=token
        )
    )

    return meeting_link

@app.get("/meetings/{meeting_id}")
def get_meeting_page(request: Request, meeting_id: str):
    if meeting_id not in db:
        raise HTTPException(
            status_code=404,
            detail="Meeting Link not Found"
        )

    return templates.TemplateResponse(
        request=request,
        name="meetingPage.html",
        context={"meeting_id": meeting_id}
    )


def create_turn_credentials(shared_secret: str):
    expiration = int(time.time()) + TURN_CREDENTIAL_LIFETIME # 10 minutes.

    participant_id = secrets.token_urlsafe(12)
    username = f"{expiration}:{participant_id}"

    digest = hmac.new(
        shared_secret.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha1
    ).digest()

    password = base64.b64encode(digest).decode("ascii")

    return {
        "username": username,
        "credential": password
    }


@app.get("/meetings/{meeting_id}/turn-credentials")
async def get_turn_credentials(meeting_id: str):

    if meeting_id not in db:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found"
        )

    # 1. Generate credentials for our own coturn server.
    own_credentials = create_turn_credentials(TURN_SHARED_SECRET)

    own_turn_server = {
        "urls": [
            "turn:voice.newnet.dev:3478?transport=udp"
        ],
        "username": own_credentials["username"],
        "credential": own_credentials["credential"]
    }

    # 2. Request temporary credentials from Turnix.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://turnix.io/api/v1/credentials/ice",
                headers={
                    "Authorization": (
                        f"Bearer {os.environ['TURNIX_API_TOKEN']}"
                    )
                },
                json={"ttl": 3600}
            )

            response.raise_for_status()
            provider_data = response.json()

            turnix_servers = provider_data["iceServers"]

    except (httpx.HTTPError, ValueError, KeyError):
        # If Turnix is unavailable, our own coturn remains usable.
        turnix_servers = []

    # 3. Combine all available ICE servers.
    ice_servers = [
        {
            "urls": ["stun:stun.l.google.com:19302"]
        }
    ]

    # Turnix servers can do all.
    ice_servers.extend(turnix_servers)

    # Our for only audio call..
    ice_servers.append(own_turn_server)

    return {
        "iceServers": ice_servers
    }


"""
accept meeting. If there are two people, send them ready, and start the SDP offer thing to create a 
webRTC connection...

it's like the client..registers its websocket to our server. we put it in thelist, and whenveer, the no.of such
sockets reach 2, we message them ready and then they start the sdp thing..session description protocol.

so, this call needs a websocket param and the emeting id param.
"""

def _is_valid(meeting_id: str):
    return True

@app.websocket("/ws/{meeting_id}")
async def register_socket(ws: WebSocket, meeting_id: str):
    # check if meeting_id is valid. i.e if present in the db. if not, return message

    # if present: 
    # add the given ws to the sockets list mapped by the meeting id. (accept the web socket first)
    # if one socket, send waiting.
    # if two sockets, send both of them as ready. but send the first one as caller, the 2nd one as reciever. (none)
    # the first sends the sdp offer, the 2nd receives it.
    # now, we need some ways to transfer the sdp offers..so, we need the sockets open.

    if (not _is_valid(meeting_id)) or (not meeting_id in db) or (len(db[meeting_id]) >= 2):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid Meeting Id")

    users = db[meeting_id]
    
    await ws.accept()

    users.append(ws)

    if len(users) == 1:
        await ws.send_json(
            {
                "type": "waiting"
            }
        )

    # We can't just return because after the fn is returned, the socket closes, but we want the socket alive so that we can recieve messages.

    if len(users) == 2:
        await users[0].send_json(
            {
                "type": "ready",
                "caller": True
            }
        )

        await users[1].send_json(
            {
                "type": "ready",
                "caller": False
            }
        )

    # Note: both clients will reach this endpoint and run the coroutine. so, we've two coroutines: one for each with each having different local variables.
    # But both co-routines have the shared state. and we can then receive and send the message to others.
    # if we use users[0] and users[1], both coroutines will read from the same first socket. since both fns execute the same code.

    try:
        while True:
            # Each handler recieves the messge from its socket and forwards to the other socket except self.
            # This way, we dont' have to wait for one client infinityely. for eg: if we do await users[0].receive_text(), it will wait in both coroutines.
            # none iwll progress. 
            
            # WHY NOT `users[0].receive_text()` THEN `users[1].receive_text()`?
            #
            # 1. CONCURRENT SOCKET READ CRASH (Two coroutines reading one socket):
            #    - FastAPI spawns a separate `register_socket` task for each client.
            #    - If both tasks run `await users[0].receive_text()`, two tasks try to read
            #      from User 0's socket at the exact same time, while nobody reads User 1.
            #    - Example: User 0 sends an SDP offer -> both coroutines race to grab it,
            #      throwing a Starlette/FastAPI runtime error ("cannot call recv while another coroutine is already waiting").
            #
            # 2. DEADLOCK / HEAD-OF-LINE BLOCKING (Strict turn-taking vs. async WebRTC):
            #    - Sequential `await users[0]` -> `await users[1]` forces a rigid 1-to-1 ping-pong order.
            #    - WebRTC does NOT take turns; browsers fire bursts of ICE candidates asynchronously.
            #    - Example: User 0 sends 1 Offer + 5 ICE candidates. Then User 1 sends 1 Answer + 5 ICE candidates.
            #      After forwarding User 1's Answer, the loop wraps around and freezes at `await users[0].receive_text()`.
            #      User 0 has nothing left to send, so User 1's 5 ICE candidates sit unread forever -> connection fails.
            #
            # 3. BROKEN DISCONNECT CLEANUP:
            #    - Example: If User 1 closes their browser tab while the loop is paused at `await users[0].receive_text()`,
            #      User 1's disconnect is never detected until User 0 sends another message.
            #
            # SOLUTION: Each coroutine only awaits its OWN `ws` (`await ws.receive_text()`) and relays to the other.


            message = await ws.receive_text()
            for user in users:
                if user is not ws:
                    await user.send_text(message)
    except WebSocketDisconnect:
        print("Client disconnected")

    finally:
        if ws in users:
            users.remove(ws)

        for user in users:
            try:
                await user.send_json({"type": "peer_left"})
            except Exception:
                pass

        
    