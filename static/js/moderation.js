/** Host-only UI; backend always verifies the host credential. */
export class ModerationPanel {
  constructor(meetingId, hostSecret, onError) {
    this.meetingId = meetingId;
    this.hostSecret = hostSecret;
    this.onError = onError;
    this.panel = document.getElementById('moderation-panel');
    this.list = document.getElementById('moderation-participants');
    this.timer = null;
    document.getElementById('refresh-moderation').addEventListener('click', () => this.refresh());
  }

  async post(path, body) {
    const response = await fetch(`/meetings/${encodeURIComponent(this.meetingId)}/moderation${path}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({host_secret: this.hostSecret, ...body}),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `Moderation request failed (${response.status})`);
    }
    return response.json();
  }

  async refresh() {
    if (this.panel.hidden) return;
    try {
      const result = await this.post('/participants', {});
      this.render(result.participants);
    } catch (error) { this.onError(error.message); }
  }

  render(participants) {
    this.list.replaceChildren();
    if (!participants.length) {
      const empty = document.createElement('p');
      empty.textContent = 'No other participants connected.';
      this.list.append(empty);
    }
    for (const participant of participants) {
      const row = document.createElement('div');
      row.className = 'pending-request';
      const name = document.createElement('strong');
      name.textContent = participant.name;
      const actions = document.createElement('div');
      actions.className = 'pending-request-actions';
      const mic = document.createElement('button');
      mic.textContent = participant.microphone_allowed ? 'Restrict mic' : 'Allow mic';
      const remove = document.createElement('button');
      remove.textContent = 'Remove';
      remove.className = 'deny-button';
      mic.addEventListener('click', () => this.perform(row, `/participants/${encodeURIComponent(participant.id)}/microphone`, {allowed: !participant.microphone_allowed}));
      remove.addEventListener('click', () => {
        if (window.confirm(`Remove ${participant.name} from this meeting?`)) {
          this.perform(row, `/participants/${encodeURIComponent(participant.id)}/remove`, {});
        }
      });
      actions.append(mic, remove);
      row.append(name, actions);
      this.list.append(row);
    }
  }

  async perform(row, path, body) {
    row.querySelectorAll('button').forEach(button => button.disabled = true);
    try { await this.post(path, body); }
    catch (error) { this.onError(error.message); }
    await this.refresh();
  }

  start() {
    if (!this.hostSecret) return;
    this.panel.hidden = false;
    this.refresh();
    if (!this.timer) this.timer = setInterval(() => this.refresh(), 4000);
  }

  stop() {
    this.panel.hidden = true;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
