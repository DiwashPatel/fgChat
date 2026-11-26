import {PrejoinController} from './prejoin.js';
import {MeetingRoom} from './livekit-room.js';
import {registerMediaControls} from './media.js';

const meetingId = document.body.dataset.meetingId;
const joinPanel = document.getElementById('join-panel');
const meetingPanel = document.getElementById('meeting-panel');
const joinButton = document.getElementById('join-button');
const leaveButton = document.getElementById('leave-button');
const endButton = document.getElementById('end-meeting-button');
const statusText = document.getElementById('connection-status');
const nameInput = document.getElementById('display-name');
const hostSecret = sessionStorage.getItem(`fgchat_host_${meetingId}`);
const prejoin = new PrejoinController();
let meeting = null;
let joining = false;
let leaving = false;
let ended = false;
let operationVersion = 0;

function setStatus(message) { statusText.textContent = message; }
function showPrejoin() { joinPanel.hidden = false; meetingPanel.hidden = true; }
function showMeeting() { joinPanel.hidden = true; meetingPanel.hidden = false; }

async function checkEnded() {
  try {
    const response = await fetch(`/api/meetings/${encodeURIComponent(meetingId)}`, {cache: 'no-store'});
    if (response.ok) {
      const info = await response.json();
      if (info.status === 'ended') {
        ended = true;
        joinButton.disabled = true;
        prejoin.dispose();
        setStatus('Meeting ended by host');
        return true;
      }
    }
  } catch (error) { console.warn('Unable to retrieve meeting status:', error); }
  return false;
}

async function restorePrejoin() {
  showPrejoin();
  if (!ended) await prejoin.restore();
}

async function onRoomDisconnected(disconnectedRoom, intentional) {
  if (meeting !== disconnectedRoom) return;
  meeting = null;
  if (leaving || intentional) return;
  const version = ++operationVersion;
  if (await checkEnded()) { showPrejoin(); return; }
  if (version !== operationVersion) return;
  setStatus('Connection lost. You can rejoin.');
  await restorePrejoin();
}

async function joinMeeting() {
  if (joining || leaving || meeting || ended) return;
  const name = nameInput.value.trim();
  if (!name) { setStatus('Enter your name to join.'); nameInput.focus(); return; }
  joining = true;
  joinButton.disabled = true;
  const version = ++operationVersion;
  let candidate = null;
  let tracks = null;
  try {
    setStatus('Connecting to meeting...');
    const response = await fetch(`/meetings/${encodeURIComponent(meetingId)}/join`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({display_name: name})
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Join rejected (${response.status})`);
    }
    const credentials = await response.json();
    candidate = new MeetingRoom({
      meetingId,
      onStatus: setStatus,
      speakerId: prejoin.speakerSelect.value || null,
      onDisconnected: intentional => onRoomDisconnected(candidate, intentional)
    });
    meeting = candidate;
    tracks = prejoin.takeTracks();
    await candidate.connect(credentials.server_url, credentials.token, tracks);
    if (version !== operationVersion || ended) throw new Error('Join cancelled');
    showMeeting();
    setStatus('Connected');
  } catch (error) {
    console.error('Join failed:', error);
    if (candidate) {
      candidate.intentionalDisconnect = true;
      await candidate.disconnect().catch(console.error);
    }
    if (meeting === candidate) meeting = null;
    if (tracks) {
      tracks.audioTrack?.stop();
      tracks.videoTrack?.stop();
    }
    if (!ended) {
      setStatus(error.message);
      await restorePrejoin();
    }
  } finally {
    joining = false;
    joinButton.disabled = ended;
  }
}

async function leaveMeeting() {
  if (!meeting || leaving) return;
  leaving = true;
  ++operationVersion;
  const current = meeting;
  leaveButton.disabled = true;
  try {
    await current.disconnect();
    if (meeting === current) meeting = null;
    setStatus('You left the meeting');
    await restorePrejoin();
  } finally { leaving = false; leaveButton.disabled = false; }
}

async function endMeeting() {
  if (!hostSecret || ended || !window.confirm('End this meeting for everyone?')) return;
  endButton.disabled = true;
  setStatus('Ending meeting...');
  try {
    const response = await fetch(`/meetings/${encodeURIComponent(meetingId)}/end`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({host_secret: hostSecret})
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Unable to end meeting');
    }
    ended = true;
    ++operationVersion;
    if (meeting) {
      const current = meeting;
      await current.disconnect();
      if (meeting === current) meeting = null;
    }
    prejoin.dispose();
    showPrejoin();
    joinButton.disabled = true;
    endButton.hidden = true;
    sessionStorage.removeItem(`fgchat_host_${meetingId}`);
    setStatus('Meeting ended for everyone');
  } catch (error) {
    console.error('End meeting failed:', error);
    setStatus(error.message);
  } finally { endButton.disabled = false; }
}

registerMediaControls(() => meeting, setStatus);
joinButton.addEventListener('click', joinMeeting);
leaveButton.addEventListener('click', leaveMeeting);
endButton.addEventListener('click', endMeeting);
endButton.hidden = !hostSecret;
nameInput.addEventListener('keydown', event => {
  if (event.key === 'Enter') joinMeeting();
});
document.getElementById('enable-audio-button').addEventListener('click', async () => {
  if (!meeting) return;
  try { await meeting.room.startAudio(); setStatus('Audio enabled'); }
  catch (error) { setStatus(`Audio unavailable: ${error.message}`); }
});
window.addEventListener('pagehide', () => {
  prejoin.dispose();
  if (meeting) meeting.room.disconnect();
});
prejoin.initialize().catch(error => console.error('Prejoin initialization failed:', error));
checkEnded();
