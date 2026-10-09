# FgChat

A responsive, browser-based chat application built using Codex. FgChat pairs a Flask application with a realtime Socket.IO layer, SQLAlchemy persistence, and browser WebRTC voice calling.

## Run it locally

Requirements: Python 3.12+ and internet access for the first virtual-environment dependency install. Setup and runtime dependencies stay inside `.venv/`. No system Python packages or global settings are changed.

```sh
./scripts/setup.sh
./scripts/dev.sh
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), create an account, then open another browser profile and create a second account. Search for the other username to begin a private conversation. Messages update live and remain available after sign-in. Use the phone icon in a conversation to place or answer a one-to-one voice call. Browsers ask for microphone permission when a call is accepted.

The setup script creates the project-local `.venv/` and an ignored `.env` containing random app and database secrets. `scripts/dev.sh` applies database migrations before starting the server. The default database is SQLite at `instance/fgchat.sqlite3`; the existing socket prototype database is kept separate.

## Features

- Account registration, sign-in, sign-out, password hashing with scrypt, CSRF protection, HttpOnly/SameSite session cookies with secure-cookie support, and rate limits on account forms.
- Search registered users and create one-to-one conversations. Conversation membership is checked on every history and realtime operation.
- Persistent text history with cursor-based loading, unread counts, typing indicators, online presence, and read receipts.
- Browser voice calls through WebRTC with Socket.IO signaling, ICE server configuration, microphone mute, and call controls. Call audio is negotiated directly between browsers; the Flask service does not relay audio.
- PostgreSQL support, Alembic migrations, optional Redis-backed Socket.IO fanout, distributed presence and call state, Redis-backed rate limiting, and a container setup.
- Account records separate provider identity (`auth_provider` and `provider_subject`) from the local password flow so an OAuth provider can be added without changing conversation ownership.

## Verify changes

The setup script installs the development tools in `.venv/`. Run the application tests, Python lint checks, and browser client syntax check from the project root:

```sh
.venv/bin/python -m pytest
.venv/bin/ruff check app migrations run.py gunicorn.conf.py tests
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

Messages are encrypted in transit when the application is served over HTTPS/WSS, and WebRTC media uses browser-managed DTLS-SRTP. Message bodies are stored as plaintext in the database, so this is not end-to-end encrypted chat. Configure encrypted database volumes, backups, access controls, and TLS in deployment. Voice call success depends on browser permissions, ICE connectivity, and TURN availability; calls should be exercised on the intended network before launch.

The current app is one-to-one text and voice. Group conversations, file sharing, message moderation/block rules, Google sign-in, and video calls are not included. The schema and route boundaries keep identity, messaging, and delivery policy separate so those features can be added without coupling passwords to conversations.

The browser Socket.IO client is vendored from Socket.IO 4.8.1 under its MIT license.
