# FgChat

FgChat is a small encrypted, threaded TCP chat application built with the Python standard library. It demonstrates TLS transport security, account authentication, direct messaging, and persistent conversation history with SQLite.

## Run locally

Python 3.10+ and OpenSSL are required. No third-party Python packages are needed.

```sh
./scripts/create-dev-cert.sh
python3 server.py
```

In another terminal:

```sh
python3 client.py
```

Start a second client with a different account. Use `/to USERNAME hello` to send a direct message, `/history USERNAME` to view the latest 50 messages, and `/quit` to disconnect. Registration requires a unique username of 3–24 letters, digits, or underscores, and a password of 10–128 characters.

The server listens on `127.0.0.1:5000` by default. Configure deployment with `FGCHAT_HOST`, `FGCHAT_PORT`, `FGCHAT_DATABASE`, `FGCHAT_TLS_CERT`, and `FGCHAT_TLS_KEY`, or their corresponding server command line options. The client accepts `--host`, `--port`, and `--ca`. For a real deployment, use a DNS name, a certificate issued for that name by a trusted CA, a protected key file, and a durable database location. Do not use the generated development certificate on a public server.

## Design

- `protocol.py` implements a 4-byte length-prefixed UTF-8 JSON protocol with a 64 KiB frame limit.
- `server.py` handles clients on separate threads, requires TLS 1.2 or newer, validates requests, and routes messages to connected recipients.
- `storage.py` stores users and conversation messages in SQLite. Passwords use salted PBKDF2-HMAC-SHA256 hashes; plaintext passwords are never stored.
- `client.py` verifies the server certificate and provides an interactive terminal interface.

Messages are encrypted in transit with TLS and stored as plaintext in the local SQLite database. This is transport encryption, not end-to-end encryption: the server can read messages. An internet-facing deployment also needs operational controls such as firewalling, rate limits, backups, monitoring, and a production identity/certificate setup. The threaded server and SQLite are intended for a focused learning/demo deployment, not large-scale multi-node service.

## TCP connection and authentication

A TCP three-way handshake (SYN, SYN-ACK, ACK) establishes a transport connection to a listening port; it does not authenticate a user or prove that the caller is trusted. The operating system routes the connection to the process listening on that port. The server then performs a TLS handshake to establish encryption and authenticate the server certificate to the client. After that, the application protocol carries the login or registration request, and FgChat checks the supplied credentials against its account database. A reachable server can receive connection attempts before application login, so production systems also need connection limits and abuse controls.

TCP carries an ordered byte stream, not application packets or HTTP objects. TLS and the application protocol interpret those bytes above TCP. FgChat uses a length prefix to delimit each JSON message because TCP does not preserve send boundaries.

## Scope

The current client supports authenticated one-to-one text conversations. Group broadcast, a graphical web interface, voice/video calls, and WebRTC signaling/media are not implemented. WebRTC needs a browser or compatible media client, signaling, and usually ICE/STUN/TURN infrastructure; sending audio frames through this raw TCP chat protocol would not implement WebRTC.
