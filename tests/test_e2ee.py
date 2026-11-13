"""Server treats encrypted direct-message contents as opaque authenticated-client data."""

import base64

import pytest
from e2ee_helpers import KEYS, enroll, envelope
from flask_migrate import downgrade, upgrade

from app import create_app
from app.chat.encryption import validate_envelope, validate_public_key
from app.extensions import db, socketio
from app.models import Message, User


@pytest.fixture
def setup():
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
            [User(id=i, username=f"user{i}", display_name=f"User {i}") for i in range(1, 4)]
        )
        db.session.commit()
    clients = [app.test_client() for _ in range(3)]
    for i, client in enumerate(clients, 1):
        with client.session_transaction() as session:
            session["_user_id"] = str(i)
            session["_fresh"] = True
    conversation = clients[0].post("/api/conversations", json={"user_id": 2}).json["conversation"]
    yield app, clients, conversation["id"]
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_key_enrollment_and_access(setup):
    app, (alice, bob, outsider), cid = setup
    assert app.test_client().get("/api/e2ee/key").status_code == 401
    assert alice.get("/api/e2ee/key").json == {"public_key": None}
    assert outsider.get(f"/api/conversations/{cid}/keys").status_code == 404
    for invalid in (
        None,
        [],
        {},
        {"public_key": "bad"},
        {"public_key": KEYS[0], "private_key": "x"},
    ):
        assert alice.post("/api/e2ee/key", json=invalid).status_code == 400
    enroll(alice, bob)
    assert alice.post("/api/e2ee/key", json={"public_key": KEYS[0]}).status_code == 200
    assert alice.post("/api/e2ee/key", json={"public_key": KEYS[1]}).status_code == 409
    assert alice.get("/api/e2ee/key").json["public_key"] == KEYS[0]
    assert alice.get(f"/api/conversations/{cid}/keys").json["keys"] == [
        {"user_id": 1, "public_key": KEYS[0]},
        {"user_id": 2, "public_key": KEYS[1]},
    ]


def test_private_envelopes_persistence_retries_and_no_plaintext(setup):
    app, (alice, bob, outsider), cid = setup
    sock = socketio.test_client(app, flask_test_client=alice)
    other = socketio.test_client(app, flask_test_client=outsider)
    try:

        def send(data):
            return sock.emit("message:send", {"conversation_id": cid, **data}, callback=True)

        assert not send({"body": "must not store this"})["ok"]
        encrypted = envelope()
        assert not send({"encryption": encrypted})["ok"]  # Peer not enrolled.
        enroll(alice, bob)
        assert not other.emit(
            "message:send", {"conversation_id": cid, "encryption": encrypted}, callback=True
        )["ok"]
        assert not send({"body": "", "encryption": encrypted})["ok"]
        result = send({"encryption": encrypted})
        assert result["ok"]
        sock.get_received()
        assert send({"encryption": encrypted}) == result
        assert sock.get_received() == []  # Retry does not redeliver.
        same_nonce = envelope()
        same_nonce["iv"] = encrypted["iv"]
        assert not send({"encryption": same_nonce})["ok"]
        reused_id = envelope()
        reused_id["message_id"] = encrypted["message_id"]
        assert not send({"encryption": reused_id})["ok"]
        with app.app_context():
            [stored] = db.session.scalars(db.select(Message)).all()
            assert stored.body == ""
            assert stored.encryption == encrypted
        [history] = bob.get(f"/api/conversations/{cid}/messages").json["messages"]
        assert history["body"] is None
        assert history["encryption"] == encrypted
        preview = bob.get("/api/conversations").json["conversations"][0]["last_message"]
        assert preview["body"] is None
        assert preview["encryption"] == encrypted
    finally:
        sock.disconnect()
        other.disconnect()


@pytest.mark.parametrize(
    "change",
    [
        {"v": True},
        {"v": 2},
        {"message_id": "not-uuid"},
        {"message_id": 1},
        {"sender_key": KEYS[1]},
        {"recipient_key": KEYS[0]},
        {"iv": "bad"},
        {"ciphertext": base64.b64encode(b"x" * 16).decode()},
        {"ciphertext": base64.b64encode(b"x" * 4017).decode()},
        {"extra": "plaintext"},
    ],
)
def test_invalid_envelopes_rejected(change):
    value = {**envelope(), **change}
    with pytest.raises(ValueError):
        validate_envelope(value, *KEYS)


def test_public_key_curve_validation():
    assert validate_public_key(KEYS[0]) == KEYS[0]
    for value in (None, {}, "", KEYS[0] + "=", base64.b64encode(b"\x04" + b"\0" * 64).decode()):
        with pytest.raises(ValueError):
            validate_public_key(value)


def test_group_plaintext_stays_separate(setup):
    app, (alice, bob, outsider), _ = setup
    group = alice.post("/api/groups", json={"name": "Group", "member_ids": [2, 3]}).json[
        "conversation"
    ]
    cid = group["id"]
    assert alice.get(f"/api/conversations/{cid}/keys").status_code == 400
    sock = socketio.test_client(app, flask_test_client=alice)
    try:
        assert not sock.emit(
            "message:send",
            {"conversation_id": cid, "body": "hi", "encryption": envelope()},
            callback=True,
        )["ok"]
        assert sock.emit("message:send", {"conversation_id": cid, "body": "hi"}, callback=True)[
            "ok"
        ]
        [message] = bob.get(f"/api/conversations/{cid}/messages").json["messages"]
        assert message["body"] == "hi"
        assert message["encryption"] is None
    finally:
        sock.disconnect()


def test_encryption_migration_preserves_legacy_and_blocks_loss(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "RATELIMIT_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'migration.sqlite3'}",
        }
    )
    with app.app_context():
        upgrade(revision="d8b731c94a02")
        db.session.execute(
            db.text("""INSERT INTO users
            (id, username, display_name, auth_provider, created_at)
            VALUES (1, 'alice', 'Alice', 'password', CURRENT_TIMESTAMP),
                   (2, 'bobby', 'Bobby', 'password', CURRENT_TIMESTAMP)""")
        )
        db.session.execute(
            db.text("""INSERT INTO conversations
            (id, user_a_id, user_b_id, created_at) VALUES (1, 1, 2, CURRENT_TIMESTAMP)""")
        )
        db.session.execute(
            db.text("""INSERT INTO messages
            (id, conversation_id, sender_id, body, created_at)
            VALUES (1, 1, 1, 'legacy', CURRENT_TIMESTAMP)""")
        )
        db.session.commit()
        upgrade()
        assert db.session.get(Message, 1).body == "legacy"
        assert db.session.get(Message, 1).encryption is None
        db.session.remove()
        downgrade(revision="d8b731c94a02")
        assert db.session.scalar(db.text("SELECT body FROM messages WHERE id=1")) == "legacy"
        indexes = (
            db.session.execute(db.text("SELECT name FROM sqlite_master WHERE type='index'"))
            .scalars()
            .all()
        )
        assert "uq_users_username_lower" in indexes
        assert "uq_users_email_lower" in indexes
        db.session.remove()
        upgrade()
        db.session.get(User, 1).e2ee_public_key = KEYS[0]
        db.session.commit()
        db.session.remove()
        with pytest.raises(SystemExit) as blocked:
            downgrade(revision="d8b731c94a02")
        assert blocked.value.code == 1
        db.session.remove()
        assert db.session.get(User, 1).e2ee_public_key == KEYS[0]
        # Also refuse ciphertext loss even if account keys were removed manually.
        db.session.get(User, 1).e2ee_public_key = None
        encrypted = envelope()
        db.session.add(
            Message(
                conversation_id=1,
                sender_id=1,
                body="",
                encryption=encrypted,
                client_message_id=encrypted["message_id"],
                encryption_iv=encrypted["iv"],
            )
        )
        db.session.commit()
        db.session.remove()
        with pytest.raises(SystemExit) as blocked:
            downgrade(revision="d8b731c94a02")
        assert blocked.value.code == 1
        db.session.remove()
        assert db.session.scalar(db.select(db.func.count(Message.id))) == 2
        db.session.remove()
        db.engine.dispose()


def test_key_enrollment_requires_csrf(setup):
    app, (alice, _, _), _ = setup
    app.config["WTF_CSRF_ENABLED"] = True
    assert alice.post("/api/e2ee/key", json={"public_key": KEYS[0]}).status_code == 400
    assert alice.get("/api/e2ee/key").json["public_key"] is None
