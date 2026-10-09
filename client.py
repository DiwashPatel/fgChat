"""Interactive TLS client for FgChat direct conversations."""

import argparse
import getpass
import socket
import ssl
import threading
from datetime import datetime
from pathlib import Path

from protocol import ProtocolError, receive_message, send_message


def show_event(event: dict) -> None:
    kind = event.get("type")
    if kind == "message":
        timestamp = datetime.fromtimestamp(event["created_at"]).strftime("%H:%M")
        print(f"\n[{timestamp}] {event['sender']} → {event['recipient']}: {event['body']}\n> ", end="", flush=True)
    elif kind == "history":
        messages = event.get("messages", [])
        print(f"\nConversation with {event['with']} ({len(messages)} recent messages)")
        for message in messages:
            timestamp = datetime.fromtimestamp(message["created_at"]).strftime("%Y-%m-%d %H:%M")
            print(f"  {timestamp}  {message['sender']}: {message['body']}")
        print("> ", end="", flush=True)
    elif kind == "error":
        print(f"\nError: {event.get('message', 'Request failed')}\n> ", end="", flush=True)


def receive_loop(client: ssl.SSLSocket) -> None:
    try:
        while True:
            event = receive_message(client)
            if event is None:
                break
            show_event(event)
    except (OSError, ProtocolError) as exc:
        print(f"\nConnection closed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect to an FgChat server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--ca", type=Path, default=Path("certs/server.crt"), help="Certificate to trust")
    args = parser.parse_args()
    action = input("Register or login? [register/login] ").strip().lower()
    if action not in ("register", "login"):
        print("Choose register or login.")
        return
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(args.ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        with socket.create_connection((args.host, args.port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=args.host) as client:
                send_message(client, {"action": action, "username": username, "password": password})
                response = receive_message(client)
                if response is None or response.get("type") != "ready":
                    print(response.get("message", "Server closed the connection.") if response else "Server closed the connection.")
                    return
                print(f"Connected securely as {response['username']}.")
                print("Commands: /to USER MESSAGE, /history USER, /quit")
                threading.Thread(target=receive_loop, args=(client,), daemon=True).start()
                while True:
                    line = input("> ").strip()
                    if line.lower() in ("/quit", "/exit"):
                        break
                    if line.startswith("/history "):
                        peer = line.split(maxsplit=1)[1]
                        send_message(client, {"action": "history", "with": peer})
                    elif line.startswith("/to "):
                        parts = line.split(maxsplit=2)
                        if len(parts) != 3:
                            print("Usage: /to USER MESSAGE")
                            continue
                        send_message(client, {"action": "send", "to": parts[1], "text": parts[2]})
                    else:
                        print("Use /to USER MESSAGE, /history USER, or /quit.")
    except FileNotFoundError:
        print(f"Trusted certificate not found: {args.ca}")
    except (OSError, ssl.SSLError) as exc:
        print(f"Could not connect securely to {args.host}:{args.port}: {exc}")


if __name__ == "__main__":
    main()
