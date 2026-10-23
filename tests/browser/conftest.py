"""Real HTTP/WebSocket server and isolated browser identities for each test."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect

SERVER = """
import sys
from pathlib import Path
from flask_migrate import upgrade
from werkzeug.serving import make_server
from app import create_app

app = create_app({
    'SECRET_KEY': 'browser-test-only-secret',
    'SQLALCHEMY_DATABASE_URI': sys.argv[1],
    'RATELIMIT_ENABLED': False,
    'SESSION_COOKIE_SECURE': False,
    'SOCKETIO_MESSAGE_QUEUE': '',
    'SOCKETIO_ASYNC_MODE': 'threading',
})
with app.app_context():
    upgrade()
server = make_server('127.0.0.1', 0, app, threaded=True)
Path(sys.argv[2]).write_text(f'http://127.0.0.1:{server.server_port}')
server.serve_forever()
"""


@pytest.fixture
def live_url(tmp_path):
    """Apply real migrations to a disposable DB; never read the developer's .env."""
    ready = tmp_path / "ready"
    log_path = tmp_path / "server.log"
    env = {key: value for key, value in os.environ.items() if not key.startswith("FGCHAT_")}
    env["RATELIMIT_STORAGE_URI"] = "memory://"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", SERVER, f"sqlite:///{tmp_path / 'chat.sqlite3'}", str(ready)],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail(f"Browser test server did not start:\n{log_path.read_text()}")
                time.sleep(0.05)
            yield ready.read_text()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
def users(new_context, live_url):
    """Register through the UI, with separate cookies and browser storage."""
    pages = []
    for username, name in (("alice", "Alice"), ("bobby", "Bobby")):
        context = new_context()
        # Fonts are decorative; tests must not depend on third-party network access.
        context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
        context.route("https://fonts.gstatic.com/**", lambda route: route.abort())
        page = context.new_page()
        page.goto(f"{live_url}/auth/register")
        page.get_by_label("Your name", exact=True).fill(name)
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).fill("correct-horse-battery")
        page.get_by_label("Confirm password", exact=True).fill("correct-horse-battery")
        page.get_by_role("button", name="Create account").click()
        expect(page).to_have_url(f"{live_url}/chat")
        expect(page.locator("#profile-name")).to_have_text(name)
        expect(page.locator("#conversation-list")).to_contain_text(
            "Your conversations will show up here"
        )
        pages.append(page)
    return tuple(pages)


@pytest.fixture
def start_chat():
    def start(page, username, name):
        page.get_by_role("button", name="Start a new conversation").click()
        page.get_by_placeholder("Try a name or @username").fill(username)
        page.locator("#search-results .person-result").filter(has_text=name).get_by_role(
            "button", name="Message", exact=True
        ).click()
        expect(page.locator("#peer-name")).to_have_text(name)

    return start


@pytest.fixture
def conversation(users, start_chat):
    alice, bob = users
    start_chat(alice, "bobby", "Bobby")
    start_chat(bob, "alice", "Alice")
    # Presence changes also prove both sockets are connected.
    expect(bob.locator("#peer-status")).to_have_text("Online now")
    expect(alice.locator("#peer-status")).to_have_text("Online now")
    return alice, bob
