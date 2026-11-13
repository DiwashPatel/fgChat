# One-to-one message encryption (v1)

## Scope and setup

New one-to-one text messages are encrypted in the browser before being sent through
Socket.IO. The server rejects plaintext sends in private conversations and stores
only an opaque encrypted envelope with an empty body. Browser history responses and
conversation previews contain ciphertext, not decrypted text. Sidebar previews say
“Encrypted message.” Group messages and existing pre-upgrade messages remain
plaintext and are explicitly labeled. This does not retroactively encrypt existing
data or backups. Voice calls retain their existing WebRTC transport security.

Each person must enable encryption in a supported, secure-context browser
(HTTPS in deployment, localhost for development). The setup dialog explains the
storage limitations before enrollment. “Not now” leaves groups available but
blocks private sends. The retry control can resume setup or recheck a peer's key.

**Keep the original browser profile and its site data.** The first enrolled browser
holds the account's sole non-exportable private key in IndexedDB. There is no key
backup, export, transfer, reset, recovery, or multi-device support. Signing out does
not erase the key. Clearing site data, using an ephemeral/private browsing profile,
losing the device, or changing the site's origin can permanently remove access to
both past and future encrypted private messages for that account. A new browser
cannot replace an enrolled public key. This intentionally fails closed instead of
silently creating a new identity or falling back to plaintext.

## Cryptographic construction

- A non-exportable WebCrypto ECDH P-256 private identity key is generated locally.
  Only the 65-byte uncompressed public point is enrolled on the server.
- The two identity keys derive a shared ECDH secret. HKDF-SHA-256 derives a
  non-exportable AES-256-GCM key using a domain-separated salt and context
  containing the conversation ID and sorted user IDs/public keys.
- Every message uses a fresh random 96-bit GCM IV and UUIDv4 client message ID.
  GCM has a 128-bit tag. Additional authenticated data binds the protocol domain,
  conversation, sender ID, client message ID, sender key, and recipient key.
- The server validates canonical base64, P-256 points, exact versioned envelope
  fields, lengths, key ownership, membership, and client IDs. Private plaintext
  fields are rejected. Ciphertext includes the authentication tag and is limited
  to the encrypted form of a 1–4,000 UTF-8-byte message.
- Database uniqueness prevents a nonce from being reused within a conversation
  and prevents a sender's client message ID from being reused. Identical retries
  acknowledge the original record rather than creating duplicates. The browser
  keeps the original envelope after an uncertain acknowledgement and retains the
  draft until acknowledgement. Rendered history also deduplicates encrypted IDs.

## Authentication and trust

Peer keys are pinned atomically in IndexedDB on first use (TOFU). A later key
change blocks sending and decryption. Conversation details displays the same
SHA-256 safety code on both endpoints. **Compare the entire code through another
trusted channel before relying on the other person's identity.** A compromised
server can substitute keys at first contact unless that comparison is performed.
Pins only detect changes after the first successful key retrieval.

AES-GCM detects modified content or authenticated context and the client never
renders unauthenticated decrypted text. Server-controlled display names, record
IDs, timestamps, read receipts, presence, typing, delivery, ordering, and message
omission are not cryptographically authenticated. The two-check receipt is labeled
“Opened”: it means the conversation history was opened, even if that browser lacks
a key or a message fails authentication. It does not confirm successful decryption. Envelope deduplication does not
prove completeness or freshness of a conversation.

## Important limitations

This is a small, versioned browser encryption feature, not the Signal protocol or
an independently audited secure messenger. It uses static ECDH and has **no forward
secrecy, post-compromise security, ratchet, key rotation, or deniable authentication**.
Compromise of a private identity key exposes that identity's conversations,
including captured past ciphertext. A conversation's symmetric key is known to
both participants, so encryption does not provide third-party proof of authorship.

The server still sees account identities, public keys, conversation membership,
message size/timing, and other metadata. HTTPS is required. The application server
serves the JavaScript, so a malicious deployment, XSS, compromised browser,
extension, operating system, or device can read plaintext or invoke even a
non-exportable private key. Non-exportable does not mean protected from code
running with the site's authority. Secure dependencies, code delivery, CSP,
endpoint security, database controls, and encrypted backups remain necessary.

## Migration and verification

The Alembic upgrade adds nullable key/envelope columns and uniqueness constraints,
preserving existing messages. Upgraded clients distinguish legacy plaintext from
encrypted messages. Do not roll back application code alone: old servers do not
enforce encrypted private sends. The schema downgrade refuses to discard enrolled
keys or encrypted messages; no destructive purge is provided.

Run:

```sh
.venv/bin/python -m pytest -m 'not browser'
.venv/bin/ruff check app migrations run.py gunicorn.conf.py tests
node --check app/static/js/chat.js
node --check app/static/js/e2ee.js
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/playwright-browsers"
.venv/bin/python -m pytest tests/browser --tracing retain-on-failure --screenshot only-on-failure
```

Browser tests exercise real WebCrypto, IndexedDB persistence/non-exportability,
bidirectional live messages, reload/sign-in history, ciphertext-only API/wire
payloads, matching safety codes, tamper detection, changed-key pinning, missing-key
failure, and ordinary group chat, receipts, reconnection, composing, and calls.
Server tests cover authorization, CSRF, key validation/immutability, wire-shape
validation, replay idempotency, nonce reuse, and migration safety. Chromium is the
automated browser target; Safari/Firefox and real multi-network voice connectivity
still require separate compatibility testing. This is not an independent security
audit.
