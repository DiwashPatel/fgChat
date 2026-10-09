import unittest

from app import create_app
from app.extensions import db, socketio
from app.models import Message, User


class ChatFlowTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "RATELIMIT_ENABLED": False,
            }
        )
        with self.app.app_context():
            db.create_all()
        self.alice_http = self.app.test_client()
        self.bob_http = self.app.test_client()
        self.alice_id = self.register(self.alice_http, "alice", "Alice")
        self.bob_id = self.register(self.bob_http, "bobby", "Bobby")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def register(self, client, username, display_name):
        response = client.post(
            "/auth/register",
            data={
                "username": username,
                "display_name": display_name,
                "email": "",
                "password": "correct-horse-battery",
                "confirm_password": "correct-horse-battery",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.scalar(db.select(User).where(User.username == username))
            return user.id

    def test_public_landing_auth_pages_and_vendored_realtime_client(self):
        anonymous = self.app.test_client()
        landing = anonymous.get("/")
        self.assertEqual(landing.status_code, 302)
        login_page = anonymous.get("/auth/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn(b"Welcome back", login_page.data)
        self.assertIn(b"csrf_token", login_page.data)
        self.assertIn(b"static/favicon.svg", login_page.data)
        socket_client = self.app.test_client().get("/static/vendor/socket.io.min.js")
        self.assertEqual(socket_client.status_code, 200)
        self.assertIn(b"Socket.IO v4.8.1", socket_client.data[:200])
        self.assertEqual(anonymous.get("/api/me").status_code, 401)

    def test_history_cursor_loads_older_messages_in_order(self):
        conversation = self.alice_http.post(
            "/api/conversations", json={"user_id": self.bob_id}
        ).json["conversation"]
        with self.app.app_context():
            db.session.add_all(
                [
                    Message(
                        conversation_id=conversation["id"],
                        sender_id=self.alice_id,
                        body=f"Message {index}",
                    )
                    for index in range(55)
                ]
            )
            db.session.commit()
        recent = self.bob_http.get(f"/api/conversations/{conversation['id']}/messages")
        self.assertEqual(len(recent.json["messages"]), 50)
        self.assertTrue(recent.json["has_more"])
        self.assertEqual(recent.json["messages"][0]["body"], "Message 5")
        older = self.bob_http.get(
            f"/api/conversations/{conversation['id']}/messages?before={recent.json['next_cursor']}"
        )
        self.assertEqual(
            [message["body"] for message in older.json["messages"]],
            [f"Message {index}" for index in range(5)],
        )
        self.assertFalse(older.json["has_more"])

    def test_authentication_and_conversation_api(self):
        duplicate = self.app.test_client().post(
            "/auth/register",
            data={
                "username": "ALICE",
                "display_name": "Another Alice",
                "email": "",
                "password": "correct-horse-battery",
                "confirm_password": "correct-horse-battery",
            },
        )
        self.assertEqual(duplicate.status_code, 409)
        response = self.alice_http.get("/api/me")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.json["user"]["username"], "alice")
        search = self.alice_http.get("/api/users?q=bob")
        self.assertEqual([user["id"] for user in search.json["users"]], [self.bob_id])
        created = self.alice_http.post("/api/conversations", json={"user_id": self.bob_id})
        self.assertEqual(created.status_code, 200)
        conversation_id = created.json["conversation"]["id"]
        repeated = self.alice_http.post("/api/conversations", json={"user_id": self.bob_id})
        self.assertEqual(repeated.json["conversation"]["id"], conversation_id)
        self.assertEqual(
            self.bob_http.get(f"/api/conversations/{conversation_id}/messages").status_code, 200
        )

    def test_realtime_message_history_receipts_and_authorization(self):
        conversation = self.alice_http.post(
            "/api/conversations", json={"user_id": self.bob_id}
        ).json["conversation"]
        alice_socket = socketio.test_client(self.app, flask_test_client=self.alice_http)
        bob_socket = socketio.test_client(self.app, flask_test_client=self.bob_http)
        self.assertTrue(alice_socket.is_connected())
        self.assertTrue(bob_socket.is_connected())
        alice_socket.emit("conversation:join", {"conversation_id": conversation["id"]})
        alice_socket.emit(
            "message:send", {"conversation_id": conversation["id"], "body": "Hello, Bobby!"}
        )
        alice_events = alice_socket.get_received()
        bob_events = bob_socket.get_received()
        sent = next(event["args"][0] for event in alice_events if event["name"] == "message:new")
        received = next(event["args"][0] for event in bob_events if event["name"] == "message:new")
        self.assertEqual(sent["id"], received["id"])
        self.assertEqual(received["body"], "Hello, Bobby!")
        inbox = self.bob_http.get("/api/conversations")
        self.assertEqual(inbox.json["conversations"][0]["unread_count"], 1)
        history = self.bob_http.get(f"/api/conversations/{conversation['id']}/messages")
        self.assertEqual(history.json["messages"][0]["body"], "Hello, Bobby!")
        self.assertIsNotNone(history.json["messages"][0]["read_at"])
        inbox = self.bob_http.get("/api/conversations")
        self.assertEqual(inbox.json["conversations"][0]["unread_count"], 0)
        receipt_events = alice_socket.get_received()
        self.assertTrue(any(event["name"] == "message:read_receipt" for event in receipt_events))
        alice_socket.disconnect()
        bob_socket.disconnect()

    def test_turn_credentials_are_short_lived_and_account_scoped(self):
        self.app.config["TURN_URL"] = "turn:turn.example.net:3478"
        self.app.config["TURN_SHARED_SECRET"] = "turn-test-secret"
        response = self.alice_http.get("/api/calls/config")
        self.assertEqual(response.status_code, 200)
        server = response.json["ice_servers"][1]
        expiry, account_id = server["username"].split(":")
        self.assertEqual(int(account_id), self.alice_id)
        self.assertGreater(int(expiry), 0)
        self.assertTrue(server["credential"])

    def test_authenticated_voice_signaling_is_routed_between_call_members(self):
        alice_socket = socketio.test_client(self.app, flask_test_client=self.alice_http)
        bob_socket = socketio.test_client(self.app, flask_test_client=self.bob_http)
        alice_socket.emit("call:start", {"peer_id": self.bob_id})
        alice_events = alice_socket.get_received()
        bob_events = bob_socket.get_received()
        outgoing = next(
            event["args"][0] for event in alice_events if event["name"] == "call:outgoing"
        )
        incoming = next(
            event["args"][0] for event in bob_events if event["name"] == "call:incoming"
        )
        self.assertEqual(outgoing["call_id"], incoming["call_id"])
        bob_socket.emit("call:accept", {"call_id": incoming["call_id"]})
        self.assertTrue(
            any(event["name"] == "call:accepted" for event in alice_socket.get_received())
        )
        bob_socket.emit("call:accept", {"call_id": incoming["call_id"]})
        self.assertTrue(any(event["name"] == "app:error" for event in bob_socket.get_received()))
        alice_socket.emit(
            "call:signal",
            {
                "call_id": incoming["call_id"],
                "payload": {"description": {"type": "offer", "sdp": "sample"}},
            },
        )
        relayed = bob_socket.get_received()
        self.assertTrue(any(event["name"] == "call:signal" for event in relayed))
        alice_socket.emit("call:end", {"call_id": incoming["call_id"]})
        self.assertTrue(any(event["name"] == "call:ended" for event in bob_socket.get_received()))
        alice_socket.disconnect()
        bob_socket.disconnect()

    def test_socket_authentication_and_unrelated_conversation_access(self):
        outsider_http = self.app.test_client()
        self.register(outsider_http, "charlie", "Charlie")
        conversation = self.alice_http.post(
            "/api/conversations", json={"user_id": self.bob_id}
        ).json["conversation"]
        outsider_socket = socketio.test_client(self.app, flask_test_client=outsider_http)
        outsider_socket.emit(
            "message:send", {"conversation_id": conversation["id"], "body": "No access"}
        )
        events = outsider_socket.get_received()
        self.assertTrue(any(event["name"] == "app:error" for event in events))
        self.assertEqual(
            self.alice_http.get(f"/api/conversations/{conversation['id']}/messages").json[
                "messages"
            ],
            [],
        )
        outsider_socket.disconnect()


if __name__ == "__main__":
    unittest.main()
