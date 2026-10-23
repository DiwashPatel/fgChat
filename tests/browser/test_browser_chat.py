"""Exercise browser rendering, real Socket.IO delivery, and persisted history."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def send(page, body):
    page.get_by_role("textbox", name="Message", exact=True).fill(body)
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.locator(".message-bubble").filter(has_text=body)).to_have_count(1)


def test_live_messages_receipts_and_history_after_signing_in_again(conversation, live_url):
    alice, bob = conversation
    send(alice, "Hello from Alice")
    expect(bob.locator(".message-bubble")).to_have_text(["Hello from Alice"])
    expect(alice.locator(".read-mark")).to_have_attribute("aria-label", "Read")
    send(bob, "Hello back from Bobby")
    expect(alice.locator(".message-bubble")).to_have_text(
        ["Hello from Alice", "Hello back from Bobby"]
    )
    expect(bob.locator(".read-mark")).to_have_attribute("aria-label", "Read")

    bob.get_by_role("button", name="Open account menu").click()
    bob.get_by_role("button", name="Sign out").click()
    expect(bob).to_have_url(f"{live_url}/auth/login")
    bob.goto(f"{live_url}/chat")
    expect(bob).to_have_url(f"{live_url}/auth/login")
    bob.get_by_label("Username", exact=True).fill("bobby")
    bob.get_by_label("Password", exact=True).fill("correct-horse-battery")
    bob.get_by_role("button", name="Sign in").click()
    bob.get_by_role("button", name="Open conversation with Alice").click()
    expect(bob.locator(".message-bubble")).to_have_text(
        ["Hello from Alice", "Hello back from Bobby"]
    )


def test_unread_badge_clears_when_conversation_is_opened(users, start_chat):
    alice, bob = users
    start_chat(alice, "bobby", "Bobby")
    expect(alice.locator("#peer-status")).to_have_text("Online now")
    expect(bob.locator("#empty-state")).to_be_visible()
    send(alice, "Waiting in your inbox")
    row = bob.get_by_role("button", name="Open conversation with Alice")
    expect(row.locator(".unread-badge")).to_have_text("1")
    expect(alice.locator(".read-mark")).to_have_attribute("aria-label", "Sent")
    row.click()
    expect(bob.locator(".message-bubble")).to_have_text("Waiting in your inbox")
    expect(row.locator(".unread-badge")).to_have_count(0)
    expect(alice.locator(".read-mark")).to_have_attribute("aria-label", "Read")


def test_typing_and_html_like_text_are_rendered_safely(conversation):
    alice, bob = conversation
    body = '<img src=x onerror="window.injected=true"> & hello'
    alice.get_by_role("textbox", name="Message", exact=True).fill(body)
    expect(bob.locator("#typing-indicator")).to_be_visible()
    alice.get_by_role("button", name="Send message", exact=True).click()
    expect(bob.locator(".message-bubble")).to_have_text(body)
    expect(bob.locator(".message-bubble img")).to_have_count(0)
    assert bob.evaluate("window.injected === undefined")
    expect(bob.locator("#typing-indicator")).to_be_hidden()


def test_mobile_back_navigation_and_multiline_composer(conversation):
    alice, bob = conversation
    alice.set_viewport_size({"width": 390, "height": 844})
    expect(alice.locator("#sidebar")).not_to_be_in_viewport()
    alice.get_by_role("button", name="Back to conversations").click()
    expect(alice.get_by_role("button", name="Open conversation with Bobby")).to_be_visible()
    alice.get_by_role("button", name="Open conversation with Bobby").click()
    message = alice.get_by_role("textbox", name="Message", exact=True)
    message.fill("First line")
    message.press("Shift+Enter")
    message.press("End")
    message.type("Second line")
    expect(message).to_have_value("First line\nSecond line")
    expect(bob.locator(".message-bubble")).to_have_count(0)
    message.press("Enter")
    expect(bob.locator(".message-bubble")).to_have_text("First line\nSecond line")
    expect(message).to_have_value("")


def test_disconnected_send_preserves_draft_and_reconnects(conversation):
    alice, bob = conversation
    bob.context.set_offline(True)
    try:
        expect(alice.locator("#peer-status")).to_have_text("Around somewhere", timeout=15000)
        draft = bob.get_by_role("textbox", name="Message", exact=True)
        draft.fill("Keep this draft")
        bob.get_by_role("button", name="Send message", exact=True).click()
        expect(bob.locator("#toast-stack")).to_contain_text("Reconnecting before sending")
        expect(draft).to_have_value("Keep this draft")
        expect(alice.locator(".message-bubble")).to_have_count(0)
    finally:
        bob.context.set_offline(False)
    expect(alice.locator("#peer-status")).to_have_text("Online now", timeout=15000)
    bob.get_by_role("button", name="Send message", exact=True).click()
    expect(alice.locator(".message-bubble")).to_have_text("Keep this draft")
    expect(bob.locator(".message-bubble")).to_have_text("Keep this draft")


@pytest.mark.parametrize(
    "action",
    [
        "decline",
        pytest.param("deny_microphone", marks=pytest.mark.only_browser("chromium")),
    ],
)
def test_voice_call_can_be_declined_or_microphone_denied(conversation, action):
    alice, bob = conversation
    if action == "deny_microphone":
        # Chromium's actual permission decision; do not replace getUserMedia.
        session = bob.context.new_cdp_session(bob)
        context_id = session.send("Target.getTargetInfo")["targetInfo"]["browserContextId"]
        session.send(
            "Browser.setPermission",
            {
                "permission": {"name": "microphone"},
                "setting": "denied",
                "origin": bob.url.split("/chat")[0],
                "browserContextId": context_id,
            },
        )
        assert (
            bob.evaluate(
                "async () => (await navigator.permissions.query({name: 'microphone'})).state"
            )
            == "denied"
        )
    alice.get_by_role("button", name="Start voice call").click()
    expect(bob.get_by_role("dialog", name="Voice call")).to_be_visible()
    expect(bob.locator("#call-name")).to_have_text("Alice")
    if action == "decline":
        bob.get_by_role("button", name="Decline call").click()
    else:
        bob.get_by_role("button", name="Accept call").click()
        expect(bob.locator("#call-status")).to_have_text("Microphone unavailable")
    expect(alice.locator("#call-status")).to_have_text("Call declined")
    expect(alice.get_by_role("dialog", name="Voice call")).to_be_hidden()
    expect(bob.get_by_role("dialog", name="Voice call")).to_be_hidden()
    send(bob, "Still able to chat")
    expect(alice.locator(".message-bubble")).to_have_text("Still able to chat")
