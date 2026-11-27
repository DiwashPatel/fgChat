const {Room, RoomEvent, Track} = window.LivekitClient;

export class MeetingRoom {
  constructor({meetingId, onStatus, onDisconnected, speakerId, mediaPolicy}) {
    this.meetingId = meetingId;
    this.onStatus = onStatus;
    this.onDisconnected = onDisconnected;
    this.speakerId = speakerId;
    this.mediaPolicy = mediaPolicy || {microphone: true, camera: true, screen_share: true};
    this.room = new Room({adaptiveStream: true, dynacast: true});
    this.tiles = new Map();
    this.shares = new Map();
    this.activeShareId = null;
    this.intentionalDisconnect = false;
    this.grid = document.getElementById('video-grid');
    this.presentation = document.getElementById('presentation-area');
    this.presentationContainer = document.getElementById('presentation-video-container');
    this.presenterName = document.getElementById('presenter-name');
    this.registerEvents();
  }

  registerEvents() {
    const r = this.room;
    r.on(RoomEvent.ParticipantConnected, p => this.createTile(p));
    r.on(RoomEvent.ParticipantDisconnected, p => {
      this.removeTile(p);
      for (const [id, share] of this.shares) {
        if (share.participant.identity === p.identity) this.removeShare(id);
      }
    });
    r.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
      this.attachRemote(track, publication, participant);
    });
    r.on(RoomEvent.TrackUnsubscribed, (track, publication, participant) => {
      if (publication.source === Track.Source.ScreenShare) this.removeShare(`${participant.identity}:${publication.trackSid}`);
      else track.detach().forEach(element => element.remove());
    });
    r.on(RoomEvent.LocalTrackPublished, publication => {
      if (publication.source === Track.Source.ScreenShare && publication.videoTrack) {
        this.addShare(publication.videoTrack, publication, r.localParticipant);
      }
      this.updateControls();
    });
    r.on(RoomEvent.LocalTrackUnpublished, publication => {
      if (publication.source === Track.Source.ScreenShare) this.removeShare(`${r.localParticipant.identity}:${publication.trackSid}`);
      this.updateControls();
    });
    r.on(RoomEvent.Disconnected, () => {
      this.cleanupUI();
      this.onDisconnected(this.intentionalDisconnect);
    });
    r.on(RoomEvent.AudioPlaybackStatusChanged, () => {
      if (!r.canPlaybackAudio) this.onStatus('Audio playback is blocked. Click Enable audio.');
    });
    r.on(RoomEvent.ParticipantPermissionsChanged, (_previousPermissions, participant) => {
      if (participant !== r.localParticipant) return;

      const permission = participant.permissions;
      const sources = permission?.canPublishSources;
      const canPublish = source => permission?.canPublish !== false &&
        (!sources || sources.includes(source));
      this.mediaPolicy = {
        microphone: canPublish(Track.Source.Microphone),
        camera: canPublish(Track.Source.Camera),
        screen_share: canPublish(Track.Source.ScreenShare) && canPublish(Track.Source.ScreenShareAudio),
      };

      // Apply revocations through the SDK so local tracks and controls agree
      // with LiveKit. Permission restoration only enables the user's controls;
      // it never turns a microphone or camera on without their action.
      const updates = [];
      if (!this.mediaPolicy.microphone && participant.isMicrophoneEnabled) {
        updates.push(participant.setMicrophoneEnabled(false));
      }
      if (!this.mediaPolicy.camera && participant.isCameraEnabled) {
        updates.push(participant.setCameraEnabled(false));
      }
      if (!this.mediaPolicy.screen_share && participant.isScreenShareEnabled) {
        updates.push(participant.setScreenShareEnabled(false));
      }
      Promise.allSettled(updates).then(results => {
        const failed = results.find(result => result.status === 'rejected');
        if (failed) this.onStatus(`Media permission update failed: ${failed.reason?.message || 'Unknown error'}`);
        this.attachLocalCamera();
        this.updateControls();
      });
    });
  }

  createTile(participant, local = false) {
    if (this.tiles.has(participant.identity)) return this.tiles.get(participant.identity);
    const tile = document.createElement('article');
    tile.className = 'video-tile';
    const media = document.createElement('div');
    media.className = 'media-container';
    const label = document.createElement('span');
    label.className = 'participant-label';
    label.textContent = `${participant.name || 'Participant'}${local ? ' (You)' : ''}`;
    tile.append(media, label);
    this.grid.append(tile);
    const info = {tile, media};
    this.tiles.set(participant.identity, info);
    return info;
  }

  removeTile(participant) {
    this.tiles.get(participant.identity)?.tile.remove();
    this.tiles.delete(participant.identity);
  }

  async applySpeaker(element) {
    if (element instanceof HTMLAudioElement && this.speakerId && typeof element.setSinkId === 'function') {
      try { await element.setSinkId(this.speakerId); }
      catch (error) { console.warn('Audio output selection failed:', error); }
    }
  }

  attachRemote(track, publication, participant) {
    if (publication.source === Track.Source.ScreenShare) {
      this.addShare(track, publication, participant);
      return;
    }
    const info = this.createTile(participant);
    const existing = info.media.querySelector(`[data-track-sid="${publication.trackSid}"]`);
    if (existing) return;
    const element = track.attach();
    element.dataset.trackSid = publication.trackSid;
    if (track.kind === Track.Kind.Video) {
      element.className = 'participant-video';
      element.playsInline = true;
    } else {
      element.autoplay = true;
      this.applySpeaker(element);
    }
    info.media.append(element);
  }

  attachLocalCamera() {
    const p = this.room.localParticipant;
    const info = this.createTile(p, true);
    const publication = p.getTrackPublication(Track.Source.Camera);
    const track = publication?.videoTrack;
    info.media.querySelectorAll('video').forEach(video => video.remove());
    if (!track) return;
    const video = track.attach();
    video.className = 'participant-video';
    video.muted = true;
    video.playsInline = true;
    info.media.append(video);
  }

  addShare(track, publication, participant) {
    const id = `${participant.identity}:${publication.trackSid}`;
    if (this.shares.has(id)) return;
    this.shares.set(id, {track, publication, participant});
    this.showShare(id);
  }

  showShare(id) {
    const share = this.shares.get(id);
    if (!share) return;
    if (this.activeShareId) {
      const previous = this.shares.get(this.activeShareId);
      if (previous?.element) {
        previous.track.detach(previous.element);
        previous.element.remove();
        previous.element = null;
      }
    }
    const element = share.track.attach();
    element.className = 'presentation-video';
    element.playsInline = true;
    element.muted = share.participant.isLocal;
    this.presentationContainer.replaceChildren(element);
    share.element = element;
    this.activeShareId = id;
    this.presenterName.textContent = `${share.participant.name || 'Participant'} is presenting`;
    this.presentation.hidden = false;
  }

  removeShare(id) {
    const share = this.shares.get(id);
    if (!share) return;
    if (share.element) {
      share.track.detach(share.element);
      share.element.remove();
    }
    this.shares.delete(id);
    if (this.activeShareId === id) {
      this.activeShareId = null;
      const next = this.shares.keys().next().value;
      if (next) this.showShare(next);
      else this.presentation.hidden = true;
    }
  }

  hidePresentation() {
    if (!this.activeShareId) return;
    const share = this.shares.get(this.activeShareId);
    if (share?.element) {
      share.track.detach(share.element);
      share.element.remove();
      share.element = null;
    }
    this.activeShareId = null;
    this.presentation.hidden = true;
  }

  reopenPresentation() {
    const id = this.shares.keys().next().value;
    if (id) this.showShare(id);
  }

  updateControls() {
    const p = this.room.localParticipant;
    const mic = document.getElementById('microphone-button');
    const camera = document.getElementById('camera-button');
    const screen = document.getElementById('screen-share-button');
    mic.textContent = this.mediaPolicy.microphone ? p.isMicrophoneEnabled ? 'Mute' : 'Unmute' : 'Mic restricted';
    camera.textContent = this.mediaPolicy.camera ? p.isCameraEnabled ? 'Camera off' : 'Camera on' : 'Camera restricted';
    screen.textContent = this.mediaPolicy.screen_share ? p.isScreenShareEnabled ? 'Stop sharing' : 'Share screen' : 'Sharing restricted';
    mic.disabled = !this.mediaPolicy.microphone;
    camera.disabled = !this.mediaPolicy.camera;
    screen.disabled = !this.mediaPolicy.screen_share;
    document.getElementById('show-presentation-button').hidden = this.shares.size === 0;
  }

  async connect(url, token, tracks) {
    await this.room.connect(url, token);
    this.createTile(this.room.localParticipant, true);
    for (const participant of this.room.remoteParticipants.values()) {
      this.createTile(participant);
      for (const publication of participant.trackPublications.values()) {
        if (publication.isSubscribed && publication.track) this.attachRemote(publication.track, publication, participant);
      }
    }
    // The preview tracks are transferred to LiveKit, not captured a second time.
    if (tracks.audioTrack && this.mediaPolicy.microphone) {
      await this.room.localParticipant.publishTrack(tracks.audioTrack, {source: Track.Source.Microphone});
    } else tracks.audioTrack?.stop();
    if (tracks.videoTrack && this.mediaPolicy.camera) {
      await this.room.localParticipant.publishTrack(tracks.videoTrack, {source: Track.Source.Camera});
    } else tracks.videoTrack?.stop();
    this.attachLocalCamera();
    this.updateControls();
    if (!this.room.canPlaybackAudio) {
      try { await this.room.startAudio(); }
      catch (error) { this.onStatus('Click Enable audio to hear participants.'); }
    }
  }

  cleanupUI() {
    for (const info of this.tiles.values()) info.tile.remove();
    this.tiles.clear();
    for (const share of this.shares.values()) {
      if (share.element) share.track.detach(share.element);
    }
    this.shares.clear();
    this.activeShareId = null;
    this.presentationContainer.replaceChildren();
    this.presentation.hidden = true;
    document.getElementById('show-presentation-button').hidden = true;
  }

  async disconnect() {
    this.intentionalDisconnect = true;
    await this.room.disconnect();
    this.cleanupUI();
  }
}
