/** Application-level lobby transport. No LiveKit or DOM media operations here. */
export class LobbyClient {
  constructor(meetingId, onEvent) {
    this.meetingId = meetingId;
    this.onEvent = onEvent;
    this.socket = null;
    this.closed = false;
    this.pollTimer = null;
  }

  endpoint(path) {
    return `/meetings/${encodeURIComponent(this.meetingId)}${path}`;
  }

  async post(path, data) {
    const response = await fetch(this.endpoint(path), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `Request failed (${response.status})`);
    return result;
  }

  connect(role, credentials) {
    this.close();
    this.closed = false;
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${location.host}${this.endpoint('/lobby/ws')}`);
    this.socket = socket;
    socket.addEventListener('open', () => socket.send(JSON.stringify({role, ...credentials})));
    socket.addEventListener('message', event => {
      try { this.onEvent(JSON.parse(event.data)); }
      catch (error) { console.error('Lobby event error:', error); }
    });
    socket.addEventListener('close', () => {
      if (!this.closed && this.socket === socket) this.onEvent({type: 'lobby.socket_closed'});
    });
  }

  startPolling(callback, interval = 3000) {
    this.stopPolling();
    this.pollTimer = setInterval(() => callback().catch(console.error), interval);
  }

  stopPolling() {
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  close() {
    this.closed = true;
    this.stopPolling();
    if (this.socket) this.socket.close();
    this.socket = null;
  }
}
