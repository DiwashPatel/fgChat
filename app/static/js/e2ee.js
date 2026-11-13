/* Browser-only direct-message encryption. See docs/e2ee.md for the threat model. */
(() => {
  "use strict";

  const DOMAIN = "fgchat:dm:v1";
  const encoder = new TextEncoder();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const ENVELOPE_FIELDS = "ciphertext,iv,message_id,recipient_key,sender_key,v";
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const missingKey = "This browser does not have your encryption key. Use the browser where you first enabled encrypted chat. Clearing site data loses access to encrypted messages.";

  const encode = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes)));
  function decode(value, minimum, maximum = minimum) {
    if (typeof value !== "string" || value.length > Math.ceil(maximum / 3) * 4) throw new Error("Invalid encrypted message encoding.");
    let bytes;
    try { bytes = Uint8Array.from(atob(value), (character) => character.charCodeAt(0)); }
    catch { throw new Error("Invalid encrypted message encoding."); }
    if (bytes.length < minimum || bytes.length > maximum || encode(bytes) !== value) throw new Error("Invalid encrypted message encoding.");
    return bytes;
  }
  const positiveId = (id) => Number.isSafeInteger(id) && id > 0;
  async function publicKey(value) {
    const bytes = decode(value, 65);
    if (bytes[0] !== 4) throw new Error("Invalid encryption public key.");
    return crypto.subtle.importKey("raw", bytes, { name: "ECDH", namedCurve: "P-256" }, false, []);
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const operation = indexedDB.open("fgchat-e2ee-v1", 1);
      operation.onupgradeneeded = () => operation.result.createObjectStore("keys");
      operation.onerror = () => reject(new Error("Encrypted chat needs browser storage. Allow site storage and try again."));
      operation.onblocked = () => reject(new Error("Close other FgChat tabs and try encrypted chat again."));
      operation.onsuccess = () => {
        const database = operation.result;
        database.onversionchange = () => database.close();
        resolve(database);
      };
    });
  }

  // Atomic read-or-add prevents competing tabs from replacing an identity or a pin.
  function stored(database, key, candidate) {
    return new Promise((resolve, reject) => {
      let result;
      const transaction = database.transaction("keys", candidate === undefined ? "readonly" : "readwrite");
      const records = transaction.objectStore("keys");
      const read = records.get(key);
      read.onsuccess = () => {
        result = read.result;
        if (result === undefined && candidate !== undefined) {
          result = candidate;
          records.add(candidate, key);
        }
      };
      transaction.oncomplete = () => resolve(result);
      transaction.onabort = transaction.onerror = () => reject(new Error("Could not save your encryption keys. Encrypted messages were not sent."));
    });
  }

  async function validateIdentity(identity) {
    const key = identity?.privateKey;
    if (!key || key.type !== "private" || key.extractable || key.algorithm?.name !== "ECDH" || key.algorithm?.namedCurve !== "P-256" || !key.usages.includes("deriveBits")) throw new Error(missingKey);
    const published = await publicKey(identity.publicKey);
    // Check that the stored public and private keys really belong together.
    const probe = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
    const first = await crypto.subtle.deriveBits({ name: "ECDH", public: published }, probe.privateKey, 256);
    const second = await crypto.subtle.deriveBits({ name: "ECDH", public: probe.publicKey }, key, 256);
    if (encode(first) !== encode(second)) throw new Error("Stored encryption keys do not match. Encrypted chat is blocked.");
  }

  class Client {
    constructor(userId, request, database, identity) {
      this.userId = userId;
      this.request = request;
      this.database = database;
      this.identity = identity;
      this.derivedKeys = new Map();
      this.preparing = new Map();
    }

    static async create({ userId, request }) {
      if (!window.isSecureContext || !window.crypto?.subtle) throw new Error("Encrypted chat requires HTTPS or localhost and a browser with Web Crypto support.");
      if (!positiveId(userId) || typeof request !== "function") throw new Error("Sign in before enabling encrypted chat.");
      const database = await openDatabase();
      try {
        const remote = await request("/api/e2ee/key");
        if (remote.public_key !== null && typeof remote.public_key !== "string") throw new Error("Invalid encryption key response.");
        let identity = await stored(database, `identity:${userId}`);
        if (!identity) {
          if (remote.public_key !== null) throw new Error(missingKey);
          const pair = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
          const candidate = { privateKey: pair.privateKey, publicKey: encode(await crypto.subtle.exportKey("raw", pair.publicKey)) };
          identity = await stored(database, `identity:${userId}`, candidate);
        }
        await validateIdentity(identity);
        if (remote.public_key !== null && remote.public_key !== identity.publicKey) throw new Error("Your account encryption key differs from this browser's key. Encrypted chat is blocked.");
        if (remote.public_key === null) {
          await request("/api/e2ee/key", { method: "POST", body: JSON.stringify({ public_key: identity.publicKey }) });
        }
        return new Client(userId, request, database, identity);
      } catch (error) {
        database.close();
        throw error;
      }
    }

    validateConversation(conversation) {
      if (!conversation || conversation.is_group || !positiveId(conversation.id) || !positiveId(conversation.peer?.id) || conversation.peer.id === this.userId) throw new Error("Encryption is only available for one-to-one conversations.");
    }

    async prepare(conversation) {
      this.validateConversation(conversation);
      const token = `${conversation.id}:${conversation.peer.id}`;
      if (this.preparing.has(token)) return this.preparing.get(token);
      const pending = this.loadKeys(conversation);
      this.preparing.set(token, pending);
      try { return await pending; }
      finally { this.preparing.delete(token); }
    }

    async loadKeys(conversation) {
      const response = await this.request(`/api/conversations/${conversation.id}/keys`);
      const keys = response.keys;
      if (!Array.isArray(keys) || keys.length !== 2 || new Set(keys.map((item) => item.user_id)).size !== 2) throw new Error("Invalid conversation encryption keys.");
      const own = keys.find((item) => item.user_id === this.userId);
      const peer = keys.find((item) => item.user_id === conversation.peer.id);
      if (!own || !peer || own.public_key !== this.identity.publicKey) throw new Error("Your encryption key could not be verified. Encrypted chat is blocked.");
      if (peer.public_key === null) throw new Error("This person must open FgChat in a supported browser before you can send encrypted messages.");
      const peerKey = await publicKey(peer.public_key);
      const pin = await stored(this.database, `pin:${this.userId}:${peer.user_id}`, peer.public_key);
      if (pin !== peer.public_key) throw new Error("This person's encryption key has changed. Sending and decrypting are blocked. Verify their identity through another trusted channel.");
      const pairs = [[this.userId, this.identity.publicKey], [peer.user_id, peer.public_key]].sort((a, b) => a[0] - b[0]);
      const info = JSON.stringify([DOMAIN, conversation.id, ...pairs]);
      let key = this.derivedKeys.get(info);
      if (!key) {
        const secret = await crypto.subtle.deriveBits({ name: "ECDH", public: peerKey }, this.identity.privateKey, 256);
        const input = await crypto.subtle.importKey("raw", secret, "HKDF", false, ["deriveKey"]);
        key = await crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: await crypto.subtle.digest("SHA-256", encoder.encode(DOMAIN)), info: encoder.encode(info) }, input, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
        this.derivedKeys.set(info, key);
      }
      return { key, peerKey: peer.public_key, pairs };
    }

    aad(conversation, senderId, envelope) {
      return encoder.encode(JSON.stringify([DOMAIN, conversation.id, senderId, envelope.message_id, envelope.sender_key, envelope.recipient_key]));
    }

    async encrypt(conversation, body) {
      if (typeof body !== "string") throw new Error("Write a message before sending.");
      const bytes = encoder.encode(body);
      if (bytes.length < 1 || bytes.length > 4000) throw new Error("Messages must contain 1–4000 UTF-8 bytes.");
      const prepared = await this.prepare(conversation);
      const envelope = { v: 1, sender_key: this.identity.publicKey, recipient_key: prepared.peerKey, message_id: crypto.randomUUID(), iv: encode(crypto.getRandomValues(new Uint8Array(12))) };
      envelope.ciphertext = encode(await crypto.subtle.encrypt({ name: "AES-GCM", iv: decode(envelope.iv, 12), additionalData: this.aad(conversation, this.userId, envelope), tagLength: 128 }, prepared.key, bytes));
      return envelope;
    }

    async decrypt(conversation, message) {
      this.validateConversation(conversation);
      const envelope = message?.encryption;
      if (!envelope || typeof envelope !== "object" || Array.isArray(envelope) || Object.keys(envelope).sort().join(",") !== ENVELOPE_FIELDS || envelope.v !== 1 || typeof envelope.message_id !== "string" || !uuidPattern.test(envelope.message_id)) throw new Error("Invalid encrypted message.");
      if (message.conversation_id !== conversation.id || ![this.userId, conversation.peer.id].includes(message.sender_id)) throw new Error("Encrypted message belongs to a different conversation.");
      const iv = decode(envelope.iv, 12);
      const ciphertext = decode(envelope.ciphertext, 17, 4016);
      const prepared = await this.prepare(conversation);
      const mine = message.sender_id === this.userId;
      if (envelope.sender_key !== (mine ? this.identity.publicKey : prepared.peerKey) || envelope.recipient_key !== (mine ? prepared.peerKey : this.identity.publicKey)) throw new Error("Encrypted message keys do not match this conversation.");
      try {
        const bytes = await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: this.aad(conversation, message.sender_id, envelope), tagLength: 128 }, prepared.key, ciphertext);
        return decoder.decode(bytes);
      } catch {
        throw new Error("This encrypted message could not be authenticated. Its contents were not displayed.");
      }
    }

    async safetyCode(conversation) {
      const { pairs } = await this.prepare(conversation);
      const digest = await crypto.subtle.digest("SHA-256", encoder.encode(JSON.stringify(["fgchat:safety:v1", ...pairs])));
      return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("").match(/.{4}/g).join(" ");
    }
  }

  window.FgE2EE = Client;
})();
