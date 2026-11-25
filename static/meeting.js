
const { Room, RoomEvent, Track } = LivekitClient;

const meetingId = document.body.dataset.meetingId;

const joinPanel = document.getElementById("join-panel");
const meetingPanel = document.getElementById("meeting-panel");
const videoGrid = document.getElementById("video-grid");

const joinButton = document.getElementById("join-button");
const nameInput = document.getElementById("display-name");

const microphoneButton =
    document.getElementById("microphone-button");

const cameraButton =
    document.getElementById("camera-button");

const leaveButton =
    document.getElementById("leave-button");

const statusText =
    document.getElementById("connection-status");

let room = null;


// One video tile per participant.
const participantTiles = new Map();


function setStatus(message) {
    statusText.textContent = message;
}


function createParticipantTile(participant, isLocal = false) {
    const id = participant.identity;

    if (participantTiles.has(id)) {
        return participantTiles.get(id);
    }

    const tile = document.createElement("div");
    tile.className = "video-tile";
    tile.dataset.participantId = id;

    const mediaContainer = document.createElement("div");
    mediaContainer.className = "media-container";

    const label = document.createElement("div");
    label.className = "participant-label";

    label.textContent = isLocal
        ? `${participant.name || "You"} (You)`
        : participant.name || "Participant";

    tile.append(mediaContainer, label);
    videoGrid.appendChild(tile);

    const tileInfo = {
        tile,
        mediaContainer,
        label
    };

    participantTiles.set(id, tileInfo);

    return tileInfo;
}


function removeParticipantTile(participant) {
    const tileInfo = participantTiles.get(participant.identity);

    if (!tileInfo) {
        return;
    }

    tileInfo.tile.remove();
    participantTiles.delete(participant.identity);
}


function attachRemoteTrack(track, publication, participant) {
    const tileInfo = createParticipantTile(participant);

    const element = track.attach();

    if (track.kind === Track.Kind.Video) {
        element.className = "participant-video";
        element.autoplay = true;
        element.playsInline = true;

        // Replace any existing video element for this track.
        const existing = tileInfo.mediaContainer.querySelector(
            `[data-track-sid="${publication.trackSid}"]`
        );

        if (existing) {
            existing.remove();
        }

        element.dataset.trackSid = publication.trackSid;
        tileInfo.mediaContainer.appendChild(element);
    }

    if (track.kind === Track.Kind.Audio) {
        // Audio does not need a visible element.
        element.autoplay = true;
        element.dataset.trackSid = publication.trackSid;
        tileInfo.mediaContainer.appendChild(element);
    }
}


function detachRemoteTrack(track) {
    const elements = track.detach();

    for (const element of elements) {
        element.remove();
    }
}


function attachLocalVideo() {
    const participant = room.localParticipant;
    const tileInfo = createParticipantTile(participant, true);

    const publication = participant.getTrackPublication(
        Track.Source.Camera
    );

    const videoTrack = publication?.videoTrack;

    if (!videoTrack) {
        return;
    }

    // Avoid attaching the same local track repeatedly.
    const existing = tileInfo.mediaContainer.querySelector(
        ".participant-video"
    );

    if (existing) {
        existing.remove();
    }

    const element = videoTrack.attach();

    element.className = "participant-video";
    element.muted = true;
    element.autoplay = true;
    element.playsInline = true;

    tileInfo.mediaContainer.appendChild(element);
}


function updateControls() {
    if (!room) {
        return;
    }

    const participant = room.localParticipant;

    microphoneButton.textContent =
        participant.isMicrophoneEnabled
            ? "Mute"
            : "Unmute";

    cameraButton.textContent =
        participant.isCameraEnabled
            ? "Camera Off"
            : "Camera On";
}


function registerRoomEvents(currentRoom) {
    currentRoom.on(
        RoomEvent.ParticipantConnected,
        (participant) => {
            createParticipantTile(participant);
        }
    );

    currentRoom.on(
        RoomEvent.ParticipantDisconnected,
        (participant) => {
            removeParticipantTile(participant);
        }
    );

    currentRoom.on(
        RoomEvent.TrackSubscribed,
        (track, publication, participant) => {
            attachRemoteTrack(track, publication, participant);
        }
    );

    currentRoom.on(
        RoomEvent.TrackUnsubscribed,
        (track) => {
            detachRemoteTrack(track);
        }
    );

    currentRoom.on(
        RoomEvent.Disconnected,
        async () => {
            resetMeetingUI();

            try {
                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(meetingId)}`,
                    { cache: "no-store" }
                );

                if (response.ok) {
                    const meeting = await response.json();

                    if (meeting.status === "ended") {
                        joinButton.disabled = true;
                        setStatus("Meeting ended by host");
                        return;
                    }
                }

                setStatus("Disconnected");

            } catch (error) {
                console.error(error);
                setStatus("Disconnected");
            }
        }
    );

    currentRoom.on(
        RoomEvent.AudioPlaybackStatusChanged,
        () => {
            if (!currentRoom.canPlaybackAudio) {
                setStatus("Click to enable meeting audio");
            }
        }
    );
}


async function joinMeeting() {
    const displayName = nameInput.value.trim();

    if (!displayName) {
        setStatus("Please enter your name");
        return;
    }

    joinButton.disabled = true;
    setStatus("Joining meeting...");

    let newRoom = null;

    try {
        // Step 1: Request credentials from FastAPI.
        const response = await fetch(
            `/meetings/${encodeURIComponent(meetingId)}/join`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    display_name: displayName
                })
            }
        );

        if (!response.ok) {
            throw new Error("Unable to join meeting");
        }

        const credentials = await response.json();

        // Step 2: Create a LiveKit room.
        newRoom = new Room({
            adaptiveStream: true,
            dynacast: true
        });

        room = newRoom;

        // Register listeners before connecting.
        registerRoomEvents(newRoom);

        // Step 3: Connect directly to the SFU.
        await newRoom.connect(
            credentials.server_url,
            credentials.token
        );

        // Step 4: Display our own participant tile.
        createParticipantTile(newRoom.localParticipant, true);

        // Display participants already connected.
        for (const participant of newRoom.remoteParticipants.values()) {
            createParticipantTile(participant);

            // Handle tracks already subscribed.
            for (const publication of participant.trackPublications.values()) {
                if (publication.isSubscribed && publication.track) {
                    attachRemoteTrack(
                        publication.track,
                        publication,
                        participant
                    );
                }
            }
        }

        // Step 5: Publish microphone and camera.
        await newRoom.localParticipant.enableCameraAndMicrophone();

        attachLocalVideo();
        updateControls();

        joinPanel.hidden = true;
        meetingPanel.hidden = false;

        setStatus("Connected");

        // Browser autoplay policies may block remote audio.
        if (!newRoom.canPlaybackAudio) {
            try {
                await newRoom.startAudio();
            } catch (error) {
                console.warn("Audio playback requires user interaction", error);
                setStatus("Click to enable meeting audio");
            }
        }

    } catch (error) {
        console.error("Join failed:", error);

        if (newRoom) {
            await newRoom.disconnect();
        }

        room = null;
        resetMeetingUI();
        setStatus(error.message);
    } finally {
        joinButton.disabled = false;
    }
}


function resetMeetingUI() {
    for (const tileInfo of participantTiles.values()) {
        tileInfo.tile.remove();
    }

    participantTiles.clear();

    room = null;

    joinPanel.hidden = false;
    meetingPanel.hidden = true;
}


joinButton.onclick = joinMeeting;


microphoneButton.onclick = async () => {
    if (!room) {
        return;
    }

    microphoneButton.disabled = true;

    try {
        const participant = room.localParticipant;

        await participant.setMicrophoneEnabled(
            !participant.isMicrophoneEnabled
        );

        updateControls();
    } catch (error) {
        console.error(error);
        setStatus("Unable to change microphone");
    } finally {
        microphoneButton.disabled = false;
    }
};


cameraButton.onclick = async () => {
    if (!room) {
        return;
    }

    cameraButton.disabled = true;

    try {
        const participant = room.localParticipant;

        await participant.setCameraEnabled(
            !participant.isCameraEnabled
        );

        if (participant.isCameraEnabled) {
            attachLocalVideo();
        }

        updateControls();
    } catch (error) {
        console.error(error);
        setStatus("Unable to change camera");
    } finally {
        cameraButton.disabled = false;
    }
};


leaveButton.onclick = async () => {
    if (!room) {
        return;
    }

    const currentRoom = room;

    leaveButton.disabled = true;

    try {
        await currentRoom.disconnect();
        resetMeetingUI();
        setStatus("You left the meeting");
    } finally {
        leaveButton.disabled = false;
    }
};


window.addEventListener("pagehide", () => {
    if (room) {
        room.disconnect();
    }
});


// HOST CONTROLS

const endMeetingButton =
    document.getElementById("end-meeting-button");

const hostSecret = sessionStorage.getItem(
    `fgchat_host_${meetingId}`
);

// Only show the control when this tab has host credentials.
if (hostSecret) {
    endMeetingButton.hidden = false;
}


endMeetingButton.onclick = async () => {
    if (!hostSecret) {
        return;
}

const confirmed = window.confirm(
    "End this meeting for everyone?"
);

if (!confirmed) {
    return;
}

endMeetingButton.disabled = true;
setStatus("Ending meeting...");

try {
    const response = await fetch(
        `/meetings/${encodeURIComponent(meetingId)}/end`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                host_secret: hostSecret
            })
        }
    );

    if (!response.ok) {
        const error = await response.json();

        throw new Error(
            error.detail || "Failed to end meeting"
        );
    }

    // LiveKit also disconnects all connected participants.
    if (room) {
        await room.disconnect();
    }

    resetMeetingUI();
    joinButton.disabled = true;

    setStatus("Meeting ended for everyone");

    sessionStorage.removeItem(
        `fgchat_host_${meetingId}`
    );

    endMeetingButton.hidden = true;

} catch (error) {
    console.error(error);
    setStatus(error.message);

} finally {
    endMeetingButton.disabled = false;
}
};
