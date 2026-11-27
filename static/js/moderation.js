/** Host-only media controls; the backend verifies every requested change. */
const CAPABILITIES = [
  ['microphone', 'Microphone'],
  ['camera', 'Camera'],
  ['screen_share', 'Screen sharing'],
];

export class ModerationPanel {
  constructor(meetingId, hostSecret, onError) {
    this.meetingId = meetingId;
    this.hostSecret = hostSecret;
    this.onError = onError;
    this.panel = document.getElementById('moderation-panel');
    this.list = document.getElementById('moderation-participants');
    this.policyInputs = [...document.querySelectorAll('[data-meeting-capability]')];
    this.timer = null;
    this.refreshing = false;
    document.getElementById('refresh-moderation').addEventListener('click', () => this.refresh());
    this.policyInputs.forEach(input => input.addEventListener('change', () => this.updateMeetingPolicy()));
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
    if (this.panel.hidden || this.refreshing) return;
    this.refreshing = true;
    try {
      const result = await this.post('/participants', {});
      this.renderMeetingPolicy(result.meeting_policy);
      this.render(result.participants, result.meeting_policy);
    } catch (error) { this.onError(error.message); }
    finally { this.refreshing = false; }
  }

  renderMeetingPolicy(policy) {
    for (const input of this.policyInputs) {
      input.checked = policy[input.dataset.meetingCapability];
    }
  }

  async updateMeetingPolicy() {
    this.policyInputs.forEach(input => { input.disabled = true; });
    const policy = Object.fromEntries(this.policyInputs.map(input => [
      input.dataset.meetingCapability, input.checked,
    ]));
    try {
      const result = await this.post('/policy', policy);
      this.renderMeetingPolicy(result.meeting_policy);
      await this.refresh();
    } catch (error) {
      this.onError(error.message);
      await this.refresh();
    } finally { this.policyInputs.forEach(input => { input.disabled = false; }); }
  }

  render(participants, meetingPolicy) {
    this.list.replaceChildren();
    if (!participants.length) {
      const empty = document.createElement('p');
      empty.textContent = 'No other participants connected.';
      this.list.append(empty);
    }
    for (const participant of participants) {
      const row = document.createElement('div');
      row.className = 'pending-request participant-policy-row';
      const name = document.createElement('strong');
      name.textContent = participant.name;
      const actions = document.createElement('div');
      actions.className = 'participant-policy-actions';
      for (const [capability, label] of CAPABILITIES) {
        const select = document.createElement('select');
        select.setAttribute('aria-label', `${label} permission for ${participant.name}`);
        const defaultState = meetingPolicy[capability] ? 'allowed' : 'blocked';
        for (const [value, text] of [['inherit', `Default: ${defaultState}`], ['true', `Allow ${label.toLowerCase()}`], ['false', `Block ${label.toLowerCase()}`]]) {
          const option = document.createElement('option');
          option.value = value;
          option.textContent = text;
          select.append(option);
        }
        const override = participant.overrides[capability];
        select.value = override === undefined ? 'inherit' : String(override);
        select.addEventListener('change', () => {
          const allowed = select.value === 'inherit' ? null : select.value === 'true';
          this.perform(
            row,
            `/participants/${encodeURIComponent(participant.id)}/policy`,
            {capability, allowed},
          );
        });
        actions.append(select);
      }
      const remove = document.createElement('button');
      remove.textContent = 'Remove';
      remove.className = 'deny-button';
      remove.addEventListener('click', () => {
        if (window.confirm(`Remove ${participant.name} from this meeting?`)) {
          this.perform(row, `/participants/${encodeURIComponent(participant.id)}/remove`, {});
        }
      });
      actions.append(remove);
      row.append(name, actions);
      this.list.append(row);
    }
  }

  async perform(row, path, body) {
    row.querySelectorAll('button, select').forEach(control => { control.disabled = true; });
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
