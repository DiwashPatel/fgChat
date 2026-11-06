"""Group delivery, membership checks, and independent unread counts."""

import pytest

from app import create_app
from app.extensions import db, socketio
from app.models import Conversation, User


@pytest.fixture
def group_users():
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
        db.session.add_all(
            [
                User(id=index, username=name.lower(), display_name=name)
                for index, name in enumerate(("Alice", "Bobby", "Charlie", "Outsider"), 1)
            ]
        )
        db.session.commit()
    clients = []
    for user_id in range(1, 5):
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        clients.append(client)
    yield app, clients
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_group_creation_delivery_reading_and_access(group_users):
    app, clients = group_users
    alice, bob, charlie, outsider = clients
    sockets = [socketio.test_client(app, flask_test_client=client) for client in clients]
    try:
        for socket in sockets:
            socket.get_received()
        response = alice.post(
            "/api/groups", json={"name": " Study group ", "member_ids": [2, 3, 2]}
        )
        assert response.status_code == 201
        group = response.json["conversation"]
        assert group["name"] == "Study group"
        assert group["is_group"] is True
        assert group["peer"] is None
        assert {member["id"] for member in group["members"]} == {1, 2, 3}
        data = {"conversation_id": group["id"]}
        history_url = f"/api/conversations/{group['id']}/messages"
        for socket in sockets[:3]:
            assert [event["name"] for event in socket.get_received()] == ["conversation:created"]
        assert sockets[3].get_received() == []

        for sender, body in ((0, "Hello group"), (2, "Hello from Charlie")):
            sockets[sender].emit("message:send", {**data, "body": body})
            for socket in sockets[:3]:
                events = socket.get_received()
                assert [event["name"] for event in events] == ["message:new"]
                assert events[0]["args"][0]["body"] == body
            assert sockets[3].get_received() == []

        def unread(client):
            return client.get("/api/conversations").json["conversations"][0]["unread_count"]

        assert [unread(client) for client in clients[:3]] == [1, 2, 1]
        assert len(bob.get(history_url).json["messages"]) == 2
        assert [unread(client) for client in clients[:3]] == [1, 0, 1]
        sockets[2].emit("message:read", data)
        assert [unread(client) for client in clients[:3]] == [1, 0, 0]
        assert all(not socket.get_received() for socket in sockets)

        sockets[2].emit("typing:set", {**data, "typing": True})
        for socket in sockets[:2]:
            [event] = socket.get_received()
            assert event["name"] == "typing:changed"
            assert event["args"][0]["user_id"] == 3
        assert sockets[2].get_received() == []
        assert sockets[3].get_received() == []
        assert outsider.get("/api/conversations").json["conversations"] == []
        assert outsider.get(history_url).status_code == 404
        sockets[3].emit("conversation:join", data)
        socketio.emit("test:private", {}, to=f"conversation:{group['id']}")
        assert sockets[3].get_received() == []
        sockets[3].emit("message:send", {**data, "body": "No access"})
        sockets[3].emit("message:read", data)
        sockets[3].emit("typing:set", {**data, "typing": True})
        assert [event["name"] for event in sockets[3].get_received()] == ["app:error"]
        assert all(not socket.get_received() for socket in sockets[:3])
        assert len(charlie.get(history_url).json["messages"]) == 2

        # Groups do not consume the unique direct-chat pair.
        direct = alice.post("/api/conversations", json={"user_id": 2})
        assert direct.status_code == 200
        assert direct.json["conversation"]["id"] != group["id"]
    finally:
        for socket in sockets:
            socket.disconnect()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"name": "Study", "member_ids": "2,3"},
        {"name": " ", "member_ids": [2, 3]},
        {"name": "x" * 81, "member_ids": [2, 3]},
        {"name": "Study", "member_ids": [2, 2, 1]},
        {"name": "Study", "member_ids": [2, True]},
        {"name": "Study", "member_ids": [2, "3"]},
        {"name": "Study", "member_ids": [2, 999]},
    ],
)
def test_invalid_groups_are_not_created(group_users, payload):
    app, clients = group_users
    response = clients[0].post("/api/groups", json=payload)
    assert response.status_code in (400, 404)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Conversation.id))) == 0
