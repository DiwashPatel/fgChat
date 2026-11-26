const LK = window.LivekitClient;

export class PrejoinController {
  constructor() {
    this.videoTrack = null;
    this.audioTrack = null;
    this.cameraEnabled = true;
    this.microphoneEnabled = true;
    this.cameraId = undefined;
    this.microphoneId = undefined;
    this.preview = document.getElementById('preview-video');
    this.cameraSelect = document.getElementById('camera-select');
    this.microphoneSelect = document.getElementById('microphone-select');
    this.speakerSelect = document.getElementById('speaker-select');
    this.cameraButton = document.getElementById('prejoin-camera');
    this.microphoneButton = document.getElementById('prejoin-microphone');
    this.status = document.getElementById('prejoin-status');
    this.busy = false;
    this.initialized = false;
    this.cameraButton.addEventListener('click', () => this.toggleCamera());
    this.microphoneButton.addEventListener('click', () => this.toggleMicrophone());
    this.cameraSelect.addEventListener('change', () => this.changeCamera());
    this.microphoneSelect.addEventListener('change', () => this.changeMicrophone());
    this.speakerSelect.addEventListener('change', () => this.setSpeaker());
    this.updateButtons();
  }

  setStatus(message) { this.status.textContent = message; }
  updateButtons() {
    this.cameraButton.textContent = this.cameraEnabled ? 'Camera on' : 'Camera off';
    this.microphoneButton.textContent = this.microphoneEnabled ? 'Mic on' : 'Mic off';
    this.cameraButton.setAttribute('aria-pressed', String(this.cameraEnabled));
    this.microphoneButton.setAttribute('aria-pressed', String(this.microphoneEnabled));
    document.getElementById('preview-placeholder').hidden = !!this.videoTrack;
  }

  async initialize() {
    if (this.initialized) return;
    this.initialized = true;
    await this.refreshDevices();
    await this.acquireEnabledTracks();
  }

  async acquireEnabledTracks() {
    if (this.cameraEnabled && !this.videoTrack) {
      try {
        this.videoTrack = await LK.createLocalVideoTrack(this.cameraId ? {deviceId: this.cameraId} : {});
        this.attachPreview();
      } catch (error) {
        console.error('Camera preview failed:', error);
        this.cameraEnabled = false;
        this.setStatus('Camera unavailable. You can still join.');
      }
    }
    if (this.microphoneEnabled && !this.audioTrack) {
      try {
        this.audioTrack = await LK.createLocalAudioTrack(this.microphoneId ? {deviceId: this.microphoneId} : {});
      } catch (error) {
        console.error('Microphone preview failed:', error);
        this.microphoneEnabled = false;
        this.setStatus('Microphone unavailable. You can still join.');
      }
    }
    await this.refreshDevices();
    this.updateButtons();
  }

  attachPreview() {
    if (!this.videoTrack) return;
    this.videoTrack.attach(this.preview);
    this.preview.muted = true;
    this.preview.hidden = false;
    this.updateButtons();
  }

  async refreshDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) {
      this.setStatus('Device selection is unavailable in this browser.');
      return;
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      this.fillSelect(this.cameraSelect, devices.filter(d => d.kind === 'videoinput'), 'Camera');
      this.fillSelect(this.microphoneSelect, devices.filter(d => d.kind === 'audioinput'), 'Microphone');
      this.fillSelect(this.speakerSelect, devices.filter(d => d.kind === 'audiooutput'), 'Speaker');
      this.speakerSelect.disabled = !('setSinkId' in HTMLMediaElement.prototype) || !this.speakerSelect.options.length;
    } catch (error) {
      console.error('Device enumeration failed:', error);
    }
  }

  fillSelect(select, devices, fallback) {
    const previous = select.value;
    select.replaceChildren();
    devices.forEach((device, index) => {
      const option = document.createElement('option');
      option.value = device.deviceId;
      option.textContent = device.label || `${fallback} ${index + 1}`;
      select.append(option);
    });
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
  }

  async toggleCamera() {
    if (this.busy) return;
    this.busy = true;
    try {
      if (this.cameraEnabled) {
        this.cameraEnabled = false;
        this.videoTrack?.stop();
        this.videoTrack = null;
        this.preview.srcObject = null;
        this.preview.hidden = true;
      } else {
        this.cameraEnabled = true;
        await this.acquireEnabledTracks();
      }
    } finally { this.busy = false; this.updateButtons(); }
  }

  async toggleMicrophone() {
    if (this.busy) return;
    this.busy = true;
    try {
      if (this.microphoneEnabled) {
        this.microphoneEnabled = false;
        this.audioTrack?.stop();
        this.audioTrack = null;
      } else {
        this.microphoneEnabled = true;
        await this.acquireEnabledTracks();
      }
    } finally { this.busy = false; this.updateButtons(); }
  }

  async changeCamera() {
    this.cameraId = this.cameraSelect.value || undefined;
    if (!this.cameraEnabled) return;
    this.videoTrack?.stop();
    this.videoTrack = null;
    this.preview.srcObject = null;
    await this.acquireEnabledTracks();
  }

  async changeMicrophone() {
    this.microphoneId = this.microphoneSelect.value || undefined;
    if (!this.microphoneEnabled) return;
    this.audioTrack?.stop();
    this.audioTrack = null;
    await this.acquireEnabledTracks();
  }

  setSpeaker() {
    // The selected output is applied to remote audio elements after joining.
    this.setStatus('Speaker preference selected.');
  }

  takeTracks() {
    const result = {
      videoTrack: this.cameraEnabled ? this.videoTrack : null,
      audioTrack: this.microphoneEnabled ? this.audioTrack : null,
      speakerId: this.speakerSelect.value || null
    };
    this.videoTrack = null;
    this.audioTrack = null;
    this.preview.srcObject = null;
    this.preview.hidden = true;
    return result;
  }

  async restore() {
    this.dispose();
    await this.acquireEnabledTracks();
  }

  dispose() {
    this.videoTrack?.stop();
    this.audioTrack?.stop();
    this.videoTrack = null;
    this.audioTrack = null;
    this.preview.srcObject = null;
    this.preview.hidden = true;
    this.updateButtons();
  }
}
