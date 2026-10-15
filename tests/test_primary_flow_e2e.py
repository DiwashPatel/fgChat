"""Exercise the main user journey across HTTP, Socket.IO, and persistence."""

import threading
from concurrent.futures import ThreadPoolExecutor

from app import create_app
from app.extensions import db, socketio


def test_two_users_can_chat_and_find_the_message_after_signing_in_again():
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()

    alice = app.test_client()
    bob = app.test_client()
    sockets = []
    try:
        for client, username, display_name in (
            (alice, "alice", "Alice"),
            (bob, "bobby", "Bobby"),
        ):
            response = client.post(
                "/auth/register",
                data={
                    "username": username,
                    "display_name": display_name,
                    "password": "correct-horse-battery",
                    "confirm_password": "correct-horse-battery",
                },
            )
            assert response.status_code == 302
            assert response.location.endswith("/chat")
            assert client.get("/chat").status_code == 200

        search = alice.get("/api/users?q=bob")
        assert search.status_code == 200
        [peer] = search.json["users"]
        assert peer["username"] == "bobby"

        created = alice.post("/api/conversations", json={"user_id": peer["id"]})
        assert created.status_code == 200
        conversation_id = created.json["conversation"]["id"]

        alice_socket = socketio.test_client(app, flask_test_client=alice)
        bob_socket = socketio.test_client(app, flask_test_client=bob)
        sockets.extend((alice_socket, bob_socket))
        assert alice_socket.is_connected() and bob_socket.is_connected()

        alice_socket.emit(
            "message:send", {"conversation_id": conversation_id, "body": "Hello, Bobby!"}
        )
        alice_events = alice_socket.get_received()
        bob_events = bob_socket.get_received()
        sent = next(event["args"][0] for event in alice_events if event["name"] == "message:new")
        delivered = next(event["args"][0] for event in bob_events if event["name"] == "message:new")
        assert delivered["id"] == sent["id"]
        assert delivered["body"] == "Hello, Bobby!"

        inbox = bob.get("/api/conversations").json["conversations"]
        assert inbox[0]["id"] == conversation_id
        assert inbox[0]["unread_count"] == 1

        history = bob.get(f"/api/conversations/{conversation_id}/messages")
        assert history.status_code == 200
        assert [message["id"] for message in history.json["messages"]] == [sent["id"]]
        assert any(
            event["name"] == "message:read_receipt"
            and sent["id"] in event["args"][0]["message_ids"]
            for event in alice_socket.get_received()
        )
        assert bob.get("/api/conversations").json["conversations"][0]["unread_count"] == 0

        bob_socket.disconnect()
        assert bob.post("/auth/logout").status_code == 302
        assert bob.get("/api/conversations").status_code == 401
        login = bob.post(
            "/auth/login", data={"username": "bobby", "password": "correct-horse-battery"}
        )
        assert login.status_code == 302
        assert login.location.endswith("/chat")
        restored = bob.get(f"/api/conversations/{conversation_id}/messages")
        assert restored.status_code == 200
        assert [message["body"] for message in restored.json["messages"]] == ["Hello, Bobby!"]
    finally:
        for client in sockets:
            if client.is_connected():
                client.disconnect()
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_two_connected_users_can_send_messages_concurrently(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'chat.sqlite3'}",
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()

    alice = app.test_client()
    bob = app.test_client()
    sockets = []
    try:
        for client, username in ((alice, "alice"), (bob, "bobby")):
            response = client.post(
                "/auth/register",
                data={
                    "username": username,
                    "display_name": username.title(),
                    "password": "correct-horse-battery",
                    "confirm_password": "correct-horse-battery",
                },
            )
            assert response.status_code == 302

        alice_id = alice.get("/api/me").json["user"]["id"]
        bob_id = bob.get("/api/me").json["user"]["id"]
        created = alice.post("/api/conversations", json={"user_id": bob_id})
        assert created.status_code == 200
        conversation_id = created.json["conversation"]["id"]

        alice_socket = socketio.test_client(app, flask_test_client=alice)
        bob_socket = socketio.test_client(app, flask_test_client=bob)
        sockets.extend((alice_socket, bob_socket))
        assert alice_socket.is_connected() and bob_socket.is_connected()
        alice_socket.get_received()
        bob_socket.get_received()

        start = threading.Barrier(3)

        def send(client, body):
            start.wait(timeout=5)
            client.emit("message:send", {"conversation_id": conversation_id, "body": body})

        with ThreadPoolExecutor(max_workers=2) as executor:
            alice_send = executor.submit(send, alice_socket, "Hello from Alice")
            bob_send = executor.submit(send, bob_socket, "Hello from Bobby")
            start.wait(timeout=5)
            alice_send.result(timeout=5)
            bob_send.result(timeout=5)

        expected = {"Hello from Alice": alice_id, "Hello from Bobby": bob_id}
        for client in (alice_socket, bob_socket):
            messages = [
                event["args"][0]
                for event in client.get_received()
                if event["name"] == "message:new"
            ]
            assert {message["body"]: message["sender_id"] for message in messages} == expected
            assert len({message["id"] for message in messages}) == 2

        history = alice.get(f"/api/conversations/{conversation_id}/messages")
        assert history.status_code == 200
        saved = {message["body"]: message["sender_id"] for message in history.json["messages"]}
        assert saved == expected
        assert len(history.json["messages"]) == 2
    finally:
        for client in sockets:
            if client.is_connected():
                client.disconnect()
        with app.app_context():
            db.session.remove()
            db.drop_all()
