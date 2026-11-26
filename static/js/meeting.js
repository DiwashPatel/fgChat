import {PrejoinController} from './prejoin.js';
import {MeetingRoom} from './livekit-room.js';
import {registerMediaControls} from './media.js';
import {LobbyClient} from './lobby.js';

const meetingId = document.body.dataset.meetingId;
const joinPanel = document.getElementById('join-panel');
const meetingPanel = document.getElementById('meeting-panel');
const waitingPanel = document.getElementById('waiting-panel');
const waitingStatus = document.getElementById('waiting-status');
const hostLobbyPanel = document.getElementById('host-lobby-panel');
const pendingRequests = document.getElementById('pending-requests');
const waitingCount = document.getElementById('waiting-count');
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
let admission = null;
let requesting = false;
const lobby = new LobbyClient(meetingId, handleLobbyEvent);
const hostLobby = new LobbyClient(meetingId, handleHostEvent);

function setStatus(message) { statusText.textContent = message; }
function showPrejoin() { joinPanel.hidden = false; meetingPanel.hidden = true; waitingPanel.hidden = true; }
function showWaiting() { joinPanel.hidden = true; meetingPanel.hidden = true; waitingPanel.hidden = false; }
function showMeeting() { joinPanel.hidden = true; meetingPanel.hidden = false; waitingPanel.hidden = true; hostLobbyPanel.hidden = !hostSecret; }

async function requestAdmission() {
  if (requesting || admission || joining || ended) return;
  const name = nameInput.value.trim();
  if (!name) { setStatus('Enter your name to join.'); nameInput.focus(); return; }
  requesting = true;
  joinButton.disabled = true;
  try {
    admission = await lobby.post('/admissions', {display_name: name});
    showWaiting();
    waitingStatus.textContent = 'Waiting for approval...';
    lobby.connect('guest', {request_id: admission.request_id, request_secret: admission.request_secret});
    lobby.startPolling(checkAdmission);
    await checkAdmission();
  } catch (error) {
    setStatus(error.message);
    admission = null;
    lobby.close();
    showPrejoin();
  } finally { requesting = false; joinButton.disabled = ended; }
}

async function checkAdmission() {
  if (!admission || ended) return;
  const current = admission;
  const result = await lobby.post(`/admissions/${encodeURIComponent(current.request_id)}/status`, {request_secret: current.request_secret});
  if (admission === current) await handleAdmissionStatus(result.status);
}

async function handleAdmissionStatus(status) {
  if (!admission) return;
  if (status === 'approved') {
    const approved = admission;
    admission = null;
    lobby.close();
    await joinMeeting(approved);
  } else if (status === 'denied' || status === 'cancelled') {
    admission = null;
    lobby.close();
    waitingStatus.textContent = status === 'denied' ? 'The host declined your request.' : 'Request cancelled.';
    showPrejoin();
    setStatus(waitingStatus.textContent);
  }
}

function handleLobbyEvent(event) {
  if (event.type === 'lobby.status') handleAdmissionStatus(event.status).catch(console.error);
  if (event.type === 'meeting.ended') {
    admission = null;
    lobby.close();
    ended = true;
    prejoin.dispose();
    showPrejoin();
    joinButton.disabled = true;
    setStatus('Meeting ended by host');
  }
  if (event.type === 'lobby.socket_closed' && admission) waitingStatus.textContent = 'Reconnecting status updates...';
}

function handleHostEvent(event) {
  if (event.type === 'lobby.changed') renderPending(event.pending);
}

function renderPending(requests) {
  pendingRequests.replaceChildren();
  waitingCount.textContent = `${requests.length} waiting`;
  for (const request of requests) {
    const row = document.createElement('div');
    row.className = 'pending-request';
    const name = document.createElement('strong');
    name.textContent = request.display_name;
    const actions = document.createElement('div');
    actions.className = 'pending-request-actions';
    for (const [label, approve] of [['Admit', true], ['Deny', false]]) {
      const button = document.createElement('button');
      button.textContent = label;
      button.className = approve ? 'admit-button' : 'deny-button';
      button.addEventListener('click', async () => {
        actions.querySelectorAll('button').forEach(item => item.disabled = true);
        try {
          await hostLobby.post(`/admissions/${encodeURIComponent(request.request_id)}/decision`, {host_secret: hostSecret, approve});
          await refreshPending();
        } catch (error) {
          setStatus(error.message);
          await refreshPending();
        }
      });
      actions.append(button);
    }
    row.append(name, actions);
    pendingRequests.append(row);
  }
}

async function refreshPending() {
  if (!hostSecret || ended) return;
  const result = await hostLobby.post('/admissions/pending', {host_secret: hostSecret, approve: false});
  renderPending(result.pending);
}

async function cancelWaiting() {
  const current = admission;
  admission = null;
  lobby.close();
  if (current) {
    try { await lobby.post(`/admissions/${encodeURIComponent(current.request_id)}/cancel`, {request_secret: current.request_secret}); }
    catch (error) { console.warn('Cancel admission failed:', error); }
  }
  showPrejoin();
  setStatus('Request cancelled');
}


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

async function joinMeeting(approvedAdmission = null) {
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
      body: JSON.stringify({
        display_name: name,
        ...(hostSecret ? {host_secret: hostSecret} : {
          request_id: approvedAdmission?.request_id,
          request_secret: approvedAdmission?.request_secret
        })
      })
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
    lobby.close();
    hostLobby.close();
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
joinButton.textContent = hostSecret ? 'Join now' : 'Ask to join';
joinButton.addEventListener('click', () => hostSecret ? joinMeeting() : requestAdmission());
document.getElementById('cancel-waiting-button').addEventListener('click', cancelWaiting);
leaveButton.addEventListener('click', leaveMeeting);
endButton.addEventListener('click', endMeeting);
endButton.hidden = !hostSecret;
nameInput.addEventListener('keydown', event => {
  if (event.key === 'Enter') { if (hostSecret) joinMeeting(); else requestAdmission(); }
});
document.getElementById('enable-audio-button').addEventListener('click', async () => {
  if (!meeting) return;
  try { await meeting.room.startAudio(); setStatus('Audio enabled'); }
  catch (error) { setStatus(`Audio unavailable: ${error.message}`); }
});
window.addEventListener('pagehide', () => {
  prejoin.dispose();
  lobby.close();
  hostLobby.close();
  if (meeting) meeting.room.disconnect();
});
prejoin.initialize().catch(error => console.error('Prejoin initialization failed:', error));
checkEnded();
if (hostSecret) {
  hostLobby.connect('host', {host_secret: hostSecret});
  hostLobby.startPolling(refreshPending, 4000);
  refreshPending().catch(console.error);
}
