export function registerMediaControls(getMeetingRoom, onStatus) {
  const mic = document.getElementById('microphone-button');
  const camera = document.getElementById('camera-button');
  const screen = document.getElementById('screen-share-button');
  const hide = document.getElementById('close-presentation-button');
  const show = document.getElementById('show-presentation-button');

  async function operate(button, action) {
    const meeting = getMeetingRoom();
    if (!meeting) return;
    button.disabled = true;
    try {
      await action(meeting);
      meeting.updateControls();
    } catch (error) {
      console.error('Media operation failed:', error);
      onStatus(`${error.name || 'Error'}: ${error.message || 'Media operation failed'}`);
    } finally { button.disabled = false; }
  }

  mic.addEventListener('click', () => operate(mic, async meeting => {
    const p = meeting.room.localParticipant;
    await p.setMicrophoneEnabled(!p.isMicrophoneEnabled);
  }));
  camera.addEventListener('click', () => operate(camera, async meeting => {
    const p = meeting.room.localParticipant;
    await p.setCameraEnabled(!p.isCameraEnabled);
    meeting.attachLocalCamera();
  }));
  screen.addEventListener('click', () => operate(screen, async meeting => {
    const p = meeting.room.localParticipant;
    await p.setScreenShareEnabled(!p.isScreenShareEnabled);
  }));
  hide.addEventListener('click', () => getMeetingRoom()?.hidePresentation());
  show.addEventListener('click', () => getMeetingRoom()?.reopenPresentation());
}
