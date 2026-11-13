(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const app = $("#app");
  const csrfToken = $("meta[name='csrf-token']")?.content || "";
  const state = {
    me: null,
    e2ee: null,
    e2eeError: "Encryption is getting ready.",
    sending: false,
    retrySend: null,
    conversations: [],
    active: null,
    activeMessages: [],
    olderCursor: null,
    socket: null,
    typingTimeout: null,
    searchTimeout: null,
    peerOnline: false,
    groupMembers: new Map(),
    typingUsers: new Map(),
    pc: null,
    localStream: null,
    call: null,
    pendingCandidates: [],
    callTimer: null,
    callTimeout: null,
    callStartedAt: null,
    seenMessageIds: new Set(),
    seenEncryptedMessageIds: new Set(),
    iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
  };

  async function request(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
    headers.set("X-CSRFToken", csrfToken);
    const response = await fetch(url, { ...options, headers, credentials: "same-origin" });
    if (response.status === 401) {
      window.location.assign("/auth/login");
      throw new Error("Please sign in again.");
    }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Something went wrong. Please try again.");
    return payload;
  }

  function toast(message, type = "") {
    const item = document.createElement("div");
    item.className = `toast ${type ? `toast-${type}` : ""}`;
    item.textContent = message;
    $("#toast-stack").append(item);
    window.setTimeout(() => item.remove(), 3800);
  }

  function avatarColor(user) {
    const value = user?.id || 0;
    return (value % 5) + 1;
  }

  function setAvatar(element, user) {
    element.textContent = (user?.display_name || user?.username || "?").trim().charAt(0).toUpperCase();
    element.dataset.color = avatarColor(user);
  }

  function displayTime(value, full = false) {
    if (!value) return "";
    const date = new Date(value);
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }
    if (!full && date.getFullYear() === today.getFullYear()) {
      return date.toLocaleDateString([], { month: "short", day: "numeric" });
    }
    return date.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
  }

  function conversationName(conversation) {
    return conversation.is_group ? conversation.name : conversation.peer.display_name;
  }

  function conversationAvatar(conversation) {
    return conversation.is_group ? { id: conversation.id, display_name: conversation.name } : conversation.peer;
  }

  function renderConversationList(filter = "") {
    const list = $("#conversation-list");
    const query = filter.toLocaleLowerCase();
    const items = state.conversations.filter((conversation) =>
      `${conversationName(conversation)} ${conversation.peer?.username || ""}`.toLocaleLowerCase().includes(query));
    $("#conversation-count").textContent = String(state.conversations.length);
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "conversation-item no-conversations";
      empty.textContent = state.conversations.length ? "No conversations match that search." : "Your conversations will show up here. Find someone new and say hello.";
      list.append(empty);
      return;
    }
    for (const conversation of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `conversation-item${state.active?.id === conversation.id ? " active" : ""}`;
      button.setAttribute("aria-label", `Open conversation with ${conversationName(conversation)}`);
      const avatar = document.createElement("span");
      avatar.className = "avatar";
      setAvatar(avatar, conversationAvatar(conversation));
      const copy = document.createElement("span");
      copy.className = "conversation-copy";
      const top = document.createElement("span");
      top.className = "conversation-topline";
      const name = document.createElement("strong");
      name.textContent = conversationName(conversation);
      const time = document.createElement("time");
      time.textContent = conversation.last_message ? displayTime(conversation.last_message.created_at) : "New";
      top.append(name, time);
      const bottom = document.createElement("span");
      bottom.className = "conversation-bottomline";
      const preview = document.createElement("span");
      preview.className = "conversation-preview";
      preview.textContent = conversation.last_message
        ? conversation.last_message.encryption ? "Encrypted message" : `${conversation.is_group ? `${conversation.last_message.sender}: ` : "Earlier unencrypted: "}${conversation.last_message.body}`
        : conversation.is_group ? `${conversation.members.length} members` : `@${conversation.peer.username}`;
      bottom.append(preview);
      if (conversation.unread_count > 0) {
        const badge = document.createElement("span");
        badge.className = "unread-badge";
        badge.textContent = conversation.unread_count > 99 ? "99+" : String(conversation.unread_count);
        bottom.append(badge);
      }
      copy.append(top, bottom);
      button.append(avatar, copy);
      button.addEventListener("click", () => openConversation(conversation.id));
      list.append(button);
    }
  }

  function setActiveConversation(conversation) {
    if (state.active && state.socket?.connected) {
      state.socket.emit("typing:set", { conversation_id: state.active.id, typing: false });
      state.socket.emit("conversation:leave", { conversation_id: state.active.id });
    }
    state.active = conversation;
    state.peerOnline = Boolean(conversation.peer?.online);
    state.typingUsers.clear();
    window.clearTimeout(state.typingTimeout);
    state.seenMessageIds.clear();
    state.seenEncryptedMessageIds.clear();
    state.activeMessages = [];
    state.olderCursor = null;
    $("#load-older").hidden = true;
    app.classList.add("chat-open");
    $("#empty-state").hidden = true;
    $("#conversation-view").hidden = false;
    $("#peer-name").textContent = conversationName(conversation);
    $("#peer-status").textContent = conversation.is_group ? `${conversation.members.length} members` : state.peerOnline ? "Online now" : "Around somewhere";
    $("#peer-status").classList.toggle("is-online", state.peerOnline);
    setAvatar($("#peer-avatar"), conversationAvatar(conversation));
    $("#voice-call-button").hidden = conversation.is_group;
    updateEncryptionNotice(conversation);
    renderConversationList($("#conversation-search").value);
  }

  async function initializeEncryption() {
    try {
      const current = await request("/api/e2ee/key");
      if (current.public_key === null) {
        const accepted = await new Promise((resolve) => {
          const dialog = $("#enrollment-dialog");
          const finish = (accepted) => { dialog.close(); resolve(accepted); };
          $("#enable-encryption").onclick = () => finish(true);
          $("#skip-encryption").onclick = () => finish(false);
          dialog.oncancel = (event) => { event.preventDefault(); finish(false); };
          dialog.showModal();
        });
        if (!accepted) throw new Error("Encryption is not enabled. Choose Retry encryption to set it up. Private messages cannot be sent without encryption.");
      }
      state.e2ee = await FgE2EE.create({ userId: state.me.id, request });
      state.e2eeError = "";
    } catch (error) {
      state.e2eeError = error.message;
    }
  }

  async function updateEncryptionNotice(conversation) {
    const status = $("#encryption-status");
    $("#retry-encryption").hidden = true;
    $("#send-button").disabled = state.sending || (!conversation.is_group && !state.e2ee);
    if (conversation.is_group) {
      status.textContent = "Group messages are not end-to-end encrypted.";
      return;
    }
    if (!state.e2ee) {
      status.textContent = `Encrypted chat unavailable: ${state.e2eeError}`;
      $("#retry-encryption").hidden = false;
      return;
    }
    status.textContent = "Checking encryption keys…";
    try {
      await state.e2ee.prepare(conversation);
      if (state.active?.id !== conversation.id) return;
      status.textContent = "New messages are end-to-end encrypted. Compare safety codes in conversation details. Keys stay in this browser; clearing site data loses access.";
    } catch (error) {
      if (state.active?.id !== conversation.id) return;
      status.textContent = error.message;
      $("#retry-encryption").hidden = false;
    }
  }

  async function showConversationDetails() {
    const conversation = state.active;
    if (!conversation) return;
    const dialog = $("#encryption-details");
    $("#safety-code").textContent = "";
    if (conversation.is_group) {
      $("#encryption-details-copy").textContent = `Members: ${conversation.members.map((user) => `${user.display_name} (@${user.username})`).join(", ")}`;
      $("#encryption-details-help").textContent = "Group messages are not end-to-end encrypted and are stored as plaintext on the server.";
    } else {
      $("#encryption-details-copy").textContent = `Safety code for you and @${conversation.peer.username}`;
      $("#encryption-details-help").textContent = "Compare this entire code through another trusted channel. Matching codes verify the keys, not the account name alone. Keys are trusted on first use and pinned in this browser. Earlier messages marked unencrypted remain plaintext. No key backup, recovery, or multi-device support is available.";
    }
    dialog.showModal();
    if (!conversation.is_group) {
      try {
        if (!state.e2ee) throw new Error(state.e2eeError);
        const code = await state.e2ee.safetyCode(conversation);
        if (dialog.open && state.active?.id === conversation.id) $("#safety-code").textContent = code;
      } catch (error) {
        if (dialog.open) $("#safety-code").textContent = error.message;
      }
    }
  }

  async function openConversation(conversationId) {
    const conversation = state.conversations.find((item) => item.id === conversationId);
    if (!conversation) return;
    setActiveConversation(conversation);
    $("#message-history").replaceChildren();
    $("#typing-indicator").hidden = true;
    if (state.socket?.connected) state.socket.emit("conversation:join", { conversation_id: conversation.id });
    try {
      const result = await request(`/api/conversations/${conversation.id}/messages`);
      if (state.active?.id !== conversation.id) return;
      state.activeMessages = result.messages;
      state.olderCursor = result.next_cursor;
      $("#load-older").hidden = !result.has_more;
      for (const message of result.messages) appendMessage(message, false, false);
      scrollToBottom();
      conversation.unread_count = 0;
      renderConversationList($("#conversation-search").value);
      state.socket?.emit("message:read", { conversation_id: conversation.id });
      $("#message-input").focus();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderDayDivider(dateValue) {
    const divider = document.createElement("div");
    divider.className = "date-divider";
    divider.textContent = new Date(dateValue).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
    $("#message-history").append(divider);
  }

  function appendMessage(message, scroll = true, addToState = true) {
    if (state.seenMessageIds.has(message.id)) return;
    const encryptedId = message.encryption ? `${message.sender_id}:${message.encryption.message_id}` : null;
    if (encryptedId && state.seenEncryptedMessageIds.has(encryptedId)) return;
    if (encryptedId) state.seenEncryptedMessageIds.add(encryptedId);
    state.seenMessageIds.add(message.id);
    if (addToState) state.activeMessages.push(message);
    const history = $("#message-history");
    const previous = history.querySelector(".message-row:last-of-type")?.dataset.day;
    const date = new Date(message.created_at);
    const day = date.toDateString();
    if (day !== previous) renderDayDivider(message.created_at);
    const mine = message.sender_id === state.me.id;
    const row = document.createElement("article");
    row.className = `message-row${mine ? " mine" : ""}`;
    row.dataset.day = day;
    if (!mine) {
      const avatar = document.createElement("span");
      avatar.className = "message-avatar";
      avatar.textContent = message.sender.charAt(0).toUpperCase();
      row.append(avatar);
    }
    const content = document.createElement("div");
    content.className = "message-content";
    if (state.active?.is_group) {
      const sender = document.createElement("strong");
      sender.className = "message-sender";
      sender.textContent = mine ? "You" : message.sender;
      content.append(sender);
    }
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    if (message.encryption) {
      bubble.textContent = "Decrypting message…";
      const conversation = state.active;
      if (!state.e2ee) {
        bubble.textContent = "Encrypted message unavailable in this browser.";
        bubble.title = state.e2eeError;
        bubble.classList.add("message-unavailable");
      } else {
        state.e2ee.decrypt(conversation, message).then((body) => {
          if (!bubble.isConnected) return;
          bubble.textContent = body;
        }).catch((error) => {
          if (!bubble.isConnected) return;
          bubble.textContent = "Encrypted message unavailable or unauthenticated.";
          bubble.title = error.message;
          bubble.classList.add("message-unavailable");
        });
      }
    } else {
      bubble.textContent = message.body;
      if (!state.active?.is_group) {
        const warning = document.createElement("span");
        warning.className = "legacy-message-label";
        warning.textContent = "Earlier message · not end-to-end encrypted";
        content.append(warning);
      }
    }
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const time = document.createElement("time");
    time.dateTime = message.created_at;
    time.textContent = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    meta.append(time);
    if (mine && !state.active?.is_group) {
      const receipt = document.createElement("span");
      receipt.className = "read-mark";
      receipt.setAttribute("aria-label", message.read_at ? "Opened" : "Sent");
      receipt.textContent = message.read_at ? "✓✓" : "✓";
      receipt.title = "Opened means the conversation was opened; successful decryption is not confirmed.";
      row.dataset.messageId = message.id;
      meta.append(receipt);
    }
    content.append(bubble, meta);
    row.append(content);
    history.append(row);
    if (scroll) scrollToBottom();
  }

  function scrollToBottom() {
    const scroll = $("#message-scroll");
    requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
  }

  async function loadOlderMessages() {
    if (!state.active || !state.olderCursor) return;
    const button = $("#load-older");
    const scroll = $("#message-scroll");
    const conversationId = state.active.id;
    const oldHeight = scroll.scrollHeight;
    const oldTop = scroll.scrollTop;
    button.disabled = true;
    try {
      const result = await request(`/api/conversations/${state.active.id}/messages?before=${state.olderCursor}`);
      if (state.active?.id !== conversationId) return;
      state.seenMessageIds.clear();
      state.seenEncryptedMessageIds.clear();
      state.activeMessages = [...result.messages, ...state.activeMessages];
      $("#message-history").replaceChildren();
      for (const message of state.activeMessages) appendMessage(message, false, false);
      state.olderCursor = result.next_cursor;
      button.hidden = !result.has_more;
      requestAnimationFrame(() => { scroll.scrollTop = oldTop + scroll.scrollHeight - oldHeight; });
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function refreshConversations() {
    const result = await request("/api/conversations");
    state.conversations = result.conversations;
    renderConversationList($("#conversation-search").value);
    if (state.active) {
      const current = state.conversations.find((item) => item.id === state.active.id);
      if (current) state.active = current;
    }
  }

  async function startConversation(user) {
    try {
      const result = await request("/api/conversations", {
        method: "POST",
        body: JSON.stringify({ user_id: user.id }),
      });
      await refreshConversations();
      closeModal();
      await openConversation(result.conversation.id);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function openModal() {
    $("#search-modal").hidden = false;
    $("#people-search").value = "";
    $("#group-mode").checked = false;
    $("#group-name").value = "";
    state.groupMembers.clear();
    updateGroupPicker();
    renderSearchPrompt("Type at least two characters to find someone.");
    window.setTimeout(() => $("#people-search").focus(), 40);
  }

  function closeModal() {
    $("#search-modal").hidden = true;
  }

  function updateGroupPicker() {
    const groupMode = $("#group-mode").checked;
    $("#group-fields").hidden = !groupMode;
    $("#create-group").hidden = !groupMode;
    $("#create-group").disabled = state.groupMembers.size < 2 || !$("#group-name").value.trim();
    const selected = $("#selected-members");
    selected.replaceChildren();
    for (const user of state.groupMembers.values()) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "person-open";
      button.textContent = `${user.display_name} ×`;
      button.setAttribute("aria-label", `Remove ${user.display_name}`);
      button.addEventListener("click", () => {
        state.groupMembers.delete(user.id);
        updateGroupPicker();
        searchPeople($("#people-search").value);
      });
      selected.append(button);
    }
  }

  async function createGroup() {
    const button = $("#create-group");
    button.disabled = true;
    try {
      const result = await request("/api/groups", {
        method: "POST",
        body: JSON.stringify({ name: $("#group-name").value, member_ids: [...state.groupMembers.keys()] }),
      });
      await refreshConversations();
      closeModal();
      await openConversation(result.conversation.id);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      updateGroupPicker();
    }
  }

  function renderSearchPrompt(text) {
    const results = $("#search-results");
    const message = document.createElement("div");
    message.className = "search-prompt";
    const icon = document.createElement("span");
    icon.className = "search-prompt-icon";
    icon.textContent = "✳";
    const label = document.createElement("span");
    label.textContent = text;
    message.append(icon, label);
    results.replaceChildren(message);
  }

  async function searchPeople(query) {
    if (query.trim().length < 2) {
      renderSearchPrompt("Type at least two characters to find someone.");
      return;
    }
    renderSearchPrompt("Looking for your people…");
    try {
      const result = await request(`/api/users?q=${encodeURIComponent(query.trim())}`);
      if (query !== $("#people-search").value) return;
      const results = $("#search-results");
      results.replaceChildren();
      if (!result.users.length) {
        renderSearchPromptIn(results, "No one by that name yet. Try another search.");
        return;
      }
      for (const user of result.users) {
        const row = document.createElement("div");
        row.className = "person-result";
        const avatar = document.createElement("span");
        avatar.className = "avatar avatar-small";
        setAvatar(avatar, user);
        const copy = document.createElement("span");
        copy.className = "person-result-copy";
        const name = document.createElement("strong");
        name.textContent = user.display_name;
        const handle = document.createElement("span");
        handle.textContent = `@${user.username}`;
        copy.append(name, handle);
        const start = document.createElement("button");
        start.className = "person-open";
        start.type = "button";
        const groupMode = $("#group-mode").checked;
        start.textContent = groupMode ? (state.groupMembers.has(user.id) ? "Added" : "Add") : "Message";
        start.disabled = groupMode && state.groupMembers.has(user.id);
        start.addEventListener("click", () => {
          if (!$("#group-mode").checked) return startConversation(user);
          state.groupMembers.set(user.id, user);
          start.textContent = "Added";
          start.disabled = true;
          updateGroupPicker();
        });
        row.append(avatar, copy, start);
        results.append(row);
      }
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderSearchPromptIn(parent, text) {
    const message = document.createElement("div");
    message.className = "search-prompt";
    const icon = document.createElement("span");
    icon.className = "search-prompt-icon";
    icon.textContent = "✳";
    const label = document.createElement("span");
    label.textContent = text;
    message.append(icon, label);
    parent.append(message);
  }

  function setupSocket() {
    state.socket = io({ transports: ["websocket", "polling"] });
    const socket = state.socket;
    socket.on("connect", () => {
      refreshConversations().then(() => {
        if (state.active) openConversation(state.active.id);
      }).catch((error) => toast(error.message, "error"));
    });
    const heartbeat = () => {
      if (socket.connected) socket.emit("presence:heartbeat", { call_id: state.call?.id || null });
    };
    window.setInterval(heartbeat, 25000);
    socket.on("connect_error", () => toast("Reconnecting to your conversations…", "error"));
    socket.on("conversation:created", () => refreshConversations().catch((error) => toast(error.message, "error")));
    socket.on("message:new", (message) => {
      const conversation = state.conversations.find((item) => item.id === message.conversation_id);
      if (!conversation) {
        refreshConversations().catch(() => {});
        return;
      }
      conversation.last_message = message;
      if (state.active?.id === message.conversation_id) {
        appendMessage(message);
        if (message.sender_id !== state.me.id) socket.emit("message:read", { conversation_id: message.conversation_id });
      } else if (message.sender_id !== state.me.id) {
        conversation.unread_count += 1;
        toast(`${conversationName(conversation)} sent you a message.`);
      }
      state.conversations.sort((a, b) => new Date(b.last_message?.created_at || 0) - new Date(a.last_message?.created_at || 0));
      renderConversationList($("#conversation-search").value);
    });
    socket.on("app:error", (event) => toast(event.message || "That didn't work. Try again.", "error"));
    socket.on("presence:changed", (event) => {
      if (state.active?.peer?.id === event.user_id) updatePeerPresence(event.online);
    });
    socket.on("typing:changed", (event) => {
      if (state.active?.id !== event.conversation_id || event.user_id === state.me.id) return;
      const member = state.active.members.find((user) => user.id === event.user_id);
      if (event.typing && member) state.typingUsers.set(event.user_id, member.display_name);
      else state.typingUsers.delete(event.user_id);
      $("#typing-indicator").hidden = state.typingUsers.size === 0;
      $("#typing-label").textContent = `${[...state.typingUsers.values()].join(", ")} ${state.typingUsers.size === 1 ? "is" : "are"} typing`;
      if (event.typing) scrollToBottom();
    });
    socket.on("message:read_receipt", (event) => {
      if (event.conversation_id !== state.active?.id) return;
      for (const id of event.message_ids) {
        const row = $(`[data-message-id="${id}"]`);
        const mark = row?.querySelector(".read-mark");
        if (mark) { mark.textContent = "✓✓"; mark.setAttribute("aria-label", "Opened"); mark.title = "The conversation was opened; successful decryption is not confirmed."; }
      }
    });
    socket.on("call:outgoing", (event) => showCall({ ...event, direction: "outgoing" }));
    socket.on("call:incoming", (event) => showCall({ call_id: event.call_id, peer: event.caller, direction: "incoming" }));
    socket.on("call:accepted", (event) => {
      if (state.call?.id === event.call_id) {
        window.clearTimeout(state.callTimeout);
        beginPeerConnection(true).catch(callFailure);
      }
    });
    socket.on("call:signal", (event) => receiveCallSignal(event).catch(callFailure));
    socket.on("call:ended", (event) => {
      if (state.call?.id === event.call_id) finishCall(event.reason === "declined" ? "Call declined" : "Call ended");
    });
  }

  function updatePeerPresence(online) {
    state.peerOnline = online;
    const status = $("#peer-status");
    status.textContent = online ? "Online now" : "Around somewhere";
    status.classList.toggle("is-online", online);
  }

  async function sendComposerMessage(event) {
    event.preventDefault();
    const input = $("#message-input");
    const draft = input.value;
    const body = draft.trim();
    const conversation = state.active;
    if (!body || !conversation || state.sending) return;
    if (!state.socket?.connected) {
      toast("Reconnecting before sending your message.", "error");
      return;
    }
    if (new TextEncoder().encode(body).length > 4000) {
      toast("This message is too long. Keep it under 4,000 UTF-8 bytes.", "error");
      return;
    }
    state.sending = true;
    $("#send-button").disabled = true;
    try {
      let payload;
      if (state.retrySend?.conversationId === conversation.id && state.retrySend.body === body) {
        payload = state.retrySend.payload;
      } else {
        if (!conversation.is_group && !state.e2ee) throw new Error(state.e2eeError);
        payload = conversation.is_group
          ? { conversation_id: conversation.id, body }
          : { conversation_id: conversation.id, encryption: await state.e2ee.encrypt(conversation, body) };
      }
      if (state.active?.id !== conversation.id) throw new Error("Conversation changed. Your draft was not sent.");
      if (!state.socket.connected) throw new Error("Reconnecting before sending your message.");
      // Retain the identical encrypted envelope on an uncertain acknowledgement so
      // retrying cannot duplicate a persisted message or reuse a nonce for new text.
      state.retrySend = conversation.is_group ? null : { conversationId: conversation.id, body, payload };
      const reply = await new Promise((resolve, reject) => {
        state.socket.timeout(10000).emit("message:send", payload, (error, result) => {
          if (error) reject(new Error("Delivery is not confirmed. Your draft is kept; retry to confirm delivery."));
          else resolve(result);
        });
      });
      if (!reply?.ok) {
        state.retrySend = null;
        throw new Error(reply?.error || "Message was not accepted. Your draft is kept.");
      }
      state.retrySend = null;
      if (state.active?.id === conversation.id) updateEncryptionNotice(conversation);
      if (state.active?.id === conversation.id && input.value === draft) {
        input.value = "";
        input.style.height = "auto";
      }
      state.socket.emit("typing:set", { conversation_id: conversation.id, typing: false });
    } catch (error) {
      toast(error.message, "error");
      if (state.active?.id === conversation.id) updateEncryptionNotice(conversation);
    } finally {
      state.sending = false;
      $("#send-button").disabled = !state.active || (!state.active.is_group && !state.e2ee);
    }
  }

  function onTyping() {
    const input = $("#message-input");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
    if (!state.active || !state.socket?.connected) return;
    state.socket.emit("typing:set", { conversation_id: state.active.id, typing: input.value.length > 0 });
    window.clearTimeout(state.typingTimeout);
    state.typingTimeout = window.setTimeout(() => {
      state.socket.emit("typing:set", { conversation_id: state.active?.id, typing: false });
    }, 1300);
  }

  async function startVoiceCall() {
    if (!state.active || state.active.is_group) return;
    try {
      const config = await request("/api/calls/config");
      state.iceServers = config.ice_servers;
      if (!state.socket?.connected) throw new Error("Reconnect to FgChat before starting a call.");
      state.socket.emit("call:start", { peer_id: state.active.peer.id });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function showCall(call) {
    state.call = { id: call.call_id, peer: call.peer, direction: call.direction };
    state.pendingCandidates = [];
    setAvatar($("#call-avatar"), call.peer);
    $("#call-avatar").classList.add("ringing");
    $("#call-name").textContent = call.peer.display_name;
    $("#call-label").textContent = call.direction === "incoming" ? "INCOMING VOICE CALL" : "VOICE CALL";
    $("#call-status").textContent = call.direction === "incoming" ? "Someone would love to talk." : "Calling…";
    $("#incoming-actions").hidden = call.direction !== "incoming";
    $("#active-call-actions").hidden = true;
    $("#call-timer").hidden = true;
    $("#call-backdrop").hidden = false;
    window.clearTimeout(state.callTimeout);
    state.callTimeout = window.setTimeout(() => {
      if (!state.call || state.call.direction === "active") return;
      state.socket.emit("call:end", { call_id: state.call.id });
      finishCall("No answer");
    }, 60000);
  }

  async function acceptCall() {
    if (!state.call) return;
    try {
      const config = await request("/api/calls/config");
      state.iceServers = config.ice_servers;
      await getMicrophone();
      window.clearTimeout(state.callTimeout);
      state.call.direction = "active";
      $("#incoming-actions").hidden = true;
      $("#active-call-actions").hidden = false;
      $("#call-avatar").classList.remove("ringing");
      $("#call-status").textContent = "Connecting securely…";
      $("#call-timer").hidden = false;
      state.socket.emit("call:accept", { call_id: state.call.id });
    } catch (error) {
      toast(error.message, "error");
      state.socket.emit("call:reject", { call_id: state.call.id });
      finishCall("Microphone unavailable");
    }
  }

  async function beginPeerConnection(isCaller) {
    await getMicrophone();
    if (!state.call) return;
    state.pc = new RTCPeerConnection({ iceServers: state.iceServers });
    for (const track of state.localStream.getTracks()) state.pc.addTrack(track, state.localStream);
    state.pc.ontrack = (event) => { $("#remote-audio").srcObject = event.streams[0]; };
    state.pc.onicecandidate = (event) => {
      if (event.candidate) state.socket.emit("call:signal", { call_id: state.call.id, payload: { candidate: event.candidate } });
    };
    state.pc.onconnectionstatechange = () => {
      if (!state.pc) return;
      if (state.pc.connectionState === "connected") callConnected();
      if (["failed", "closed"].includes(state.pc.connectionState)) finishCall("Call connection ended");
    };
    if (isCaller) {
      const offer = await state.pc.createOffer();
      await state.pc.setLocalDescription(offer);
      state.socket.emit("call:signal", { call_id: state.call.id, payload: { description: state.pc.localDescription } });
    }
  }

  async function receiveCallSignal(event) {
    if (!state.call || state.call.id !== event.call_id) return;
    if (!state.pc) await beginPeerConnection(false);
    const payload = event.payload;
    if (payload.description) {
      await state.pc.setRemoteDescription(payload.description);
      for (const candidate of state.pendingCandidates) await state.pc.addIceCandidate(candidate);
      state.pendingCandidates = [];
      if (payload.description.type === "offer") {
        const answer = await state.pc.createAnswer();
        await state.pc.setLocalDescription(answer);
        state.socket.emit("call:signal", { call_id: state.call.id, payload: { description: state.pc.localDescription } });
      }
    } else if (payload.candidate) {
      if (state.pc.remoteDescription) await state.pc.addIceCandidate(payload.candidate);
      else state.pendingCandidates.push(payload.candidate);
    }
  }

  async function getMicrophone() {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Voice calls need a secure connection and browser microphone support.");
    if (!state.localStream) state.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  }

  function callConnected() {
    $("#call-status").textContent = "You're connected. Say hello.";
    $("#call-avatar").classList.remove("ringing");
    state.callStartedAt = Date.now();
    window.clearInterval(state.callTimer);
    state.callTimer = window.setInterval(() => {
      if (!state.callStartedAt) return;
      const seconds = Math.floor((Date.now() - state.callStartedAt) / 1000);
      $("#call-timer").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    }, 1000);
  }

  function callFailure(error) {
    toast(error?.message || "The voice connection could not be established.", "error");
    if (state.call) state.socket.emit("call:end", { call_id: state.call.id });
    finishCall("Call connection ended");
  }

  function finishCall(status = "Call ended") {
    window.clearInterval(state.callTimer);
    window.clearTimeout(state.callTimeout);
    state.callTimeout = null;
    state.callTimer = null;
    state.callStartedAt = null;
    state.pendingCandidates = [];
    if (state.pc) {
      state.pc.ontrack = null;
      state.pc.onicecandidate = null;
      state.pc.close();
      state.pc = null;
    }
    if (state.localStream) {
      state.localStream.getTracks().forEach((track) => track.stop());
      state.localStream = null;
    }
    $("#remote-audio").srcObject = null;
    $("#call-status").textContent = status;
    $("#call-avatar").classList.remove("ringing");
    $("#incoming-actions").hidden = true;
    $("#active-call-actions").hidden = true;
    window.setTimeout(() => { $("#call-backdrop").hidden = true; state.call = null; }, 900);
  }

  function hangupCall() {
    if (state.call) state.socket.emit("call:end", { call_id: state.call.id });
    finishCall("Call ended");
  }

  function toggleMute() {
    if (!state.localStream) return;
    const tracks = state.localStream.getAudioTracks();
    const muted = tracks.some((track) => track.enabled);
    tracks.forEach((track) => { track.enabled = !muted; });
    $("#mute-call").classList.toggle("is-muted", muted);
    $("#mute-call").setAttribute("aria-label", muted ? "Unmute microphone" : "Mute microphone");
  }

  function setupShortcuts() {
    document.addEventListener("keydown", (event) => {
      const target = event.target;
      const inTextField = target instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(target.tagName);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openModal();
      } else if (event.key === "Escape") {
        closeModal();
        $("#account-menu").hidden = true;
      } else if (event.key === "Enter" && !event.shiftKey && target === $("#message-input")) {
        event.preventDefault();
        $("#composer").requestSubmit();
      } else if (event.key === "/" && !inTextField && !$("#search-modal").hidden) {
        event.preventDefault();
        $("#people-search").focus();
      }
    });
  }

  async function boot() {
    try {
      const result = await request("/api/me");
      state.me = result.user;
      $("#profile-name").textContent = state.me.display_name;
      $("#profile-handle").textContent = `@${state.me.username}`;
      $("#menu-name").textContent = state.me.display_name;
      $("#menu-handle").textContent = `@${state.me.username}`;
      setAvatar($("#profile-avatar"), state.me);
      setAvatar($("#menu-avatar"), state.me);
      await initializeEncryption();
      await refreshConversations();
      setupSocket();
      bindEvents();
      if (state.conversations.length) await openConversation(state.conversations[0].id);
    } catch (error) {
      if (error.message !== "Please sign in again.") toast(error.message, "error");
    }
  }

  function bindEvents() {
    $("#group-mode").addEventListener("change", () => {
      updateGroupPicker();
      searchPeople($("#people-search").value);
    });
    $("#group-name").addEventListener("input", updateGroupPicker);
    $("#create-group").addEventListener("click", createGroup);
    $("#new-chat-button").addEventListener("click", openModal);
    $("#empty-new-chat").addEventListener("click", openModal);
    $("#search-modal").addEventListener("click", (event) => { if (event.target === event.currentTarget) closeModal(); });
    $("[data-close-modal]").addEventListener("click", closeModal);
    $("#people-search").addEventListener("input", (event) => {
      window.clearTimeout(state.searchTimeout);
      state.searchTimeout = window.setTimeout(() => searchPeople(event.target.value), 180);
    });
    $("#conversation-search").addEventListener("input", (event) => renderConversationList(event.target.value));
    $("#composer").addEventListener("submit", sendComposerMessage);
    $("#load-older").addEventListener("click", loadOlderMessages);
    $("#message-input").addEventListener("input", onTyping);
    $("#voice-call-button").addEventListener("click", startVoiceCall);
    $("#accept-call").addEventListener("click", acceptCall);
    $("#decline-call").addEventListener("click", () => {
      if (state.call) state.socket.emit("call:reject", { call_id: state.call.id });
      finishCall("Call declined");
    });
    $("#hangup-call").addEventListener("click", hangupCall);
    $("#mute-call").addEventListener("click", toggleMute);
    $("#menu-button").addEventListener("click", () => { $("#account-menu").hidden = !$("#account-menu").hidden; });
    $("#back-button").addEventListener("click", () => app.classList.remove("chat-open"));
    $("#chat-more-button").addEventListener("click", showConversationDetails);
    $("#close-encryption-details").addEventListener("click", () => $("#encryption-details").close());
    $("#retry-encryption").addEventListener("click", async () => {
      $("#retry-encryption").disabled = true;
      try {
        if (!state.e2ee) await initializeEncryption();
        if (state.active) await openConversation(state.active.id);
      } finally {
        $("#retry-encryption").disabled = false;
      }
    });
    setupShortcuts();
  }

  boot();
})();
