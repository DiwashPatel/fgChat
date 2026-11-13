# FgChat

A responsive, browser-based chat application built using Codex. FgChat pairs a Flask application with a realtime Socket.IO layer, SQLAlchemy persistence, and browser WebRTC voice calling.

## Run it locally

Requirements: Python 3.12+ and internet access for the first virtual-environment dependency install. Setup and runtime dependencies stay inside `.venv/`. No system Python packages or global settings are changed.

```sh
./scripts/setup.sh
./scripts/dev.sh
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), create an account, and choose **Enable on this browser** after reading the key-storage warning. Then open another browser profile, create a second account, and enable encryption there too. Search for the other username to begin a private conversation. Messages update live and remain available after sign-in. Use the phone icon in a conversation to place or answer a one-to-one voice call. Browsers ask for microphone permission when a call is accepted.

To start a group, click **＋**, check **Create a group chat**, enter a name, and search for at least two other people. Click **Add** beside each person, then **Create group**. Everyone selected sees the group immediately. The conversation details button shows its members.

The setup script creates the project-local `.venv/` and an ignored `.env` containing random app and database secrets. `scripts/dev.sh` applies database migrations before starting the server. The default database is SQLite at `instance/fgchat.sqlite3`; the existing socket prototype database is kept separate.

## Features

- Account registration, sign-in, sign-out, password hashing with scrypt, CSRF protection, HttpOnly/SameSite session cookies with secure-cookie support, and rate limits on account forms.
- Search registered users and create one-to-one conversations or named group chats. Conversation membership is checked on every history and realtime operation.
- Groups include sender names, typing indicators, persistent history, and separate unread counts for each member. Membership is fixed at creation; no roles, invitations, or member-management workflow.
- End-to-end encryption for new one-to-one text messages using browser WebCrypto (P-256 ECDH, HKDF-SHA-256, AES-256-GCM), non-exportable browser-held private keys, pinned peer identities, and comparable safety codes. No plaintext fallback for private sends.
- Persistent text history with cursor-based loading, unread counts, typing indicators, online presence, and one-to-one opened receipts (opening history does not prove successful decryption).
- Browser voice calls through WebRTC with Socket.IO signaling, ICE server configuration, microphone mute, and call controls. Call audio is negotiated directly between browsers; the Flask service does not relay audio.
- PostgreSQL support, Alembic migrations, optional Redis-backed Socket.IO fanout, distributed presence and call state, Redis-backed rate limiting, and a container setup.
- Account records separate provider identity (`auth_provider` and `provider_subject`) from the local password flow so an OAuth provider can be added without changing conversation ownership.

## Verify changes

The setup script installs the development tools in `.venv/`. Run the application tests, Python lint checks, and browser client syntax check from the project root:

```sh
.venv/bin/python -m pytest
.venv/bin/ruff check app migrations run.py gunicorn.conf.py tests
node --check app/static/js/chat.js
node --check app/static/js/e2ee.js
```

### Real browser tests

The Playwright tests in `tests/browser/` launch a real local HTTP/WebSocket server and
independent browser sessions (three for the group chat test). Each test uses a temporary SQLite database created
through the migrations; your local accounts, database, and `.env` are not used. CSRF
protection stays enabled. External font requests are blocked so the suite does not
depend on Google Fonts.

Install Chromium once after setup, keeping its download inside the project:

```sh
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/playwright-browsers"
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests/browser --tracing retain-on-failure --screenshot only-on-failure
```

Set the same `PLAYWRIGHT_BROWSERS_PATH` in each new shell before running browser tests.
Add `--headed` to watch the tests. Failure screenshots and traces appear in the ignored
`test-results/` directory. Open a trace with
`.venv/bin/python -m playwright show-trace path/to/trace.zip`.

Coverage includes live messages and read receipts, persisted history after signing
out and back in, unread badges, typing indicators, safe rendering of HTML-like text,
mobile back navigation, multiline composing, draft preservation during a connection
loss and sending after reconnect, declining calls, and actual browser microphone denial.
Group coverage includes creating a group on mobile, selecting/removing members before creation, live delivery to three people, sender names, typing, unread badges, and history after reload.
The microphone-denial case uses Chromium's permission API; successful WebRTC audio
and TURN connectivity across networks still need separate coverage.

Run the server-side tests without launching a browser with:

```sh
.venv/bin/python -m pytest -m "not browser"
```

## Run with containers

Docker Compose starts the web service, PostgreSQL, and Redis. Create local environment values, then launch the stack:

```sh
./scripts/create-compose-env.sh
docker compose up --build
```

The web container listens on port 8000 at loopback. Put it behind a TLS reverse proxy before exposing it publicly. Compose enables secure cookies by default; use `FGCHAT_COOKIE_SECURE=0` for local plain-HTTP container testing only.

For a direct Linux deployment, install `requirements.txt` in a virtual environment, set the environment described in `.env.example`, run `flask --app run db upgrade`, then start `gunicorn --config gunicorn.conf.py run:app`. Gunicorn uses its threaded worker with the WebSocket-capable `simple-websocket` transport. One worker is configured by default. To run multiple instances, set `FGCHAT_SOCKETIO_REDIS_URL` to a shared Redis URL and use a load balancer that keeps each Socket.IO connection on the same instance. Set `FGCHAT_PROXY_FIX_HOPS` to the number of trusted reverse-proxy hops if rate limits need the original client IP; only trust headers from proxies you control. Use PostgreSQL for shared durable application data.

## Voice calling setup

Local calls can connect through the configured public STUN server when the two networks allow direct peer connectivity. For calls across restrictive NATs and enterprise firewalls, provide a TURN service:

- `FGCHAT_TURN_URL` should be a `turn:` or `turns:` URL.
- For coturn REST authentication, set `FGCHAT_TURN_SHARED_SECRET`. FgChat creates short-lived, account-scoped ICE credentials.
- Static `FGCHAT_TURN_USERNAME` and `FGCHAT_TURN_CREDENTIAL` are available for small private installations, but short-lived TURN credentials are preferred for public services.

Browsers require a secure context for microphone access. `localhost` is secure for local development; deployed sites must use HTTPS. Configure DNS, TLS termination, TURN capacity, and firewall rules for the networks where users will call.

## Architecture

```text
app/
  auth/       Registration and session routes
  chat/       Conversation APIs, authorization, and realtime signaling
  static/     Responsive interface, browser client, and Socket.IO client
  templates/  Sign-in, registration, and chat views
  models.py   User, conversation, and message records
migrations/   Versioned database schema
scripts/      Local setup and container startup
```

The HTTP API handles account and conversation reads. Socket.IO handles message delivery, presence, typing, receipts, and WebRTC signaling. SQLAlchemy models are database-independent; SQLite serves local development and PostgreSQL is suitable for deployed instances. Redis coordinates Socket.IO rooms, online sessions, active calls, and request limits across service instances. Schema changes are managed through Flask-Migrate.

**New one-to-one messages are end-to-end encrypted before leaving the browser.** The server stores ciphertext and rejects plaintext private sends. Group messages and earlier messages remain plaintext and are labeled as unencrypted. **Keys are tied to the original browser profile: there is no backup, recovery, reset, or multi-device support. Clearing site data permanently loses private-chat access.** Compare safety codes in conversation details through another trusted channel to authenticate first-contact keys. This static-key design has no forward secrecy or ratchet and is not independently audited. Read the [encryption design, threat model, and limitations](docs/e2ee.md) before deployment.

HTTPS/WSS is still required, and WebRTC media uses browser-managed DTLS-SRTP. Configure encrypted database volumes, backups, access controls, and TLS in deployment. Voice call success depends on browser permissions, ICE connectivity, and TURN availability; calls should be exercised on the intended network before launch.

The app supports one-to-one text and voice plus group text chats. Group calls, group read receipts, editing group membership, file sharing, message moderation/block rules, Google sign-in, and video calls are not included. The schema and route boundaries keep identity, messaging, and delivery policy separate so those features can be added without coupling passwords to conversations.

The browser Socket.IO client is vendored from Socket.IO 4.8.1 under its MIT license.
