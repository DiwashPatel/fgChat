"""Exercise real WebCrypto and persisted non-exportable browser identities."""

import copy
import json
import re

import pytest
from playwright.sync_api import expect
from test_browser_chat import send

pytestmark = pytest.mark.browser


def conversation_id(page):
    return page.evaluate(
        "async () => (await (await fetch('/api/conversations')).json()).conversations[0].id"
    )


def history(page, chat_id):
    return page.evaluate(
        "async id => (await (await fetch(`/api/conversations/${id}/messages`)).json()).messages",
        chat_id,
    )


def test_wire_history_safety_codes_and_real_crypto_storage(conversation, tmp_path):
    alice, bob = conversation
    body = "Private hello 🔐 <not markup>"
    frames = []
    alice.on("websocket", lambda ws: ws.on("framesent", lambda frame: frames.append(frame)))
    # Reconnect so Playwright observes the Socket.IO transport's outbound frames.
    alice.reload()
    expect(alice.locator("#peer-name")).to_have_text("Bobby")
    expect(alice.locator("#encryption-status")).to_contain_text("New messages are end-to-end")
    send(alice, body)
    expect(bob.locator(".message-bubble")).to_have_text(body)
    chat_id = conversation_id(alice)
    [message] = history(alice, chat_id)
    assert message["body"] is None
    assert message["encryption"]["v"] == 1
    assert body not in json.dumps(message)
    send_frames = [frame for frame in frames if '"message:send"' in str(frame)]
    assert len(send_frames) == 1
    assert body not in str(send_frames[0])
    assert '"body"' not in str(send_frames[0])
    expect(alice.locator(".conversation-preview")).to_have_text("Encrypted message")

    for page in (alice, bob):
        page.get_by_role("button", name="Conversation details").click()
        expect(page.locator("#safety-code")).to_have_text(
            re.compile(r"^[0-9a-f]{4}( [0-9a-f]{4}){15}$")
        )
    assert alice.locator("#safety-code").inner_text() == bob.locator("#safety-code").inner_text()
    for page in (alice, bob):
        page.get_by_role("button", name="Close", exact=True).click()
        page.reload()
        expect(page.locator(".message-bubble")).to_have_text(body)
    # Browser key cloning and non-exportability are exercised, not a storage shim.
    key_properties = alice.evaluate("""async () => {
      const database = await new Promise((resolve, reject) => {
        const request = indexedDB.open('fgchat-e2ee-v1', 1);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      const id = (await (await fetch('/api/me')).json()).user.id;
      const identity = await new Promise((resolve, reject) => {
        const request = database.transaction('keys').objectStore('keys').get(`identity:${id}`);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      database.close();
      let exported = false;
      try { await crypto.subtle.exportKey('pkcs8', identity.privateKey); exported = true; } catch {}
      return {extractable: identity.privateKey.extractable, exported};
    }""")
    assert key_properties == {"extractable": False, "exported": False}
    alice.screenshot(path=str(tmp_path / "encrypted-chat-desktop.png"))
    alice.set_viewport_size({"width": 390, "height": 844})
    alice.screenshot(path=str(tmp_path / "encrypted-chat-mobile.png"))


def test_tampered_ciphertext_is_never_rendered(conversation):
    alice, bob = conversation
    body = "Must not display after corruption"
    send(alice, body)
    expect(bob.locator(".message-bubble")).to_have_text(body)
    chat_id = conversation_id(bob)

    def corrupt(route):
        response = route.fetch()
        payload = response.json()
        for message in payload["messages"]:
            envelope = message["encryption"]
            envelope["ciphertext"] = ("A" if envelope["ciphertext"][0] != "A" else "B") + envelope[
                "ciphertext"
            ][1:]
        route.fulfill(response=response, json=payload)

    bob.route(f"**/api/conversations/{chat_id}/messages", corrupt)
    bob.reload()
    expect(bob.locator(".message-bubble")).to_have_text(
        "Encrypted message unavailable or unauthenticated."
    )
    expect(bob.locator(".message-bubble")).not_to_contain_text(body)


def test_missing_key_in_second_browser_fails_closed(conversation, new_context, live_url):
    alice, bob = conversation
    send(alice, "Browser-bound secret")
    expect(bob.locator(".message-bubble")).to_have_text("Browser-bound secret")
    context = new_context()
    page = context.new_page()
    page.goto(f"{live_url}/auth/login")
    page.get_by_label("Username", exact=True).fill("bobby")
    page.get_by_label("Password", exact=True).fill("correct-horse-battery")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator("#encryption-status")).to_contain_text(
        "This browser does not have your encryption key"
    )
    expect(page.locator("#send-button")).to_be_disabled()
    expect(page.locator(".message-bubble")).to_have_text(
        "Encrypted message unavailable in this browser."
    )
    page.get_by_role("textbox", name="Message", exact=True).fill("No plaintext fallback")
    page.get_by_role("textbox", name="Message", exact=True).press("Enter")
    expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value(
        "No plaintext fallback"
    )
    assert len(history(alice, conversation_id(alice))) == 1


def test_changed_pinned_peer_key_blocks_sending_and_decryption(conversation):
    alice, bob = conversation
    send(alice, "Pin the original identity")
    expect(bob.locator(".message-bubble")).to_have_text("Pin the original identity")
    chat_id = conversation_id(alice)
    replacement = alice.evaluate("""async () => {
      const pair = await crypto.subtle.generateKey(
        {name: 'ECDH', namedCurve: 'P-256'}, false, ['deriveBits']);
      const bytes = await crypto.subtle.exportKey('raw', pair.publicKey);
      return btoa(String.fromCharCode(...new Uint8Array(bytes)));
    }""")

    def replace(route):
        response = route.fetch()
        payload = copy.deepcopy(response.json())
        payload["keys"][1]["public_key"] = replacement
        route.fulfill(response=response, json=payload)

    alice.route(f"**/api/conversations/{chat_id}/keys", replace)
    alice.reload()
    expect(alice.locator("#encryption-status")).to_contain_text("encryption key has changed")
    expect(alice.locator(".message-bubble")).to_have_text(
        "Encrypted message unavailable or unauthenticated."
    )
    draft = alice.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Blocked, not downgraded")
    alice.get_by_role("button", name="Send message", exact=True).click()
    expect(alice.locator("#toast-stack")).to_contain_text("encryption key has changed")
    expect(draft).to_have_value("Blocked, not downgraded")
    assert len(history(bob, chat_id)) == 1


def test_declining_enrollment_keeps_private_draft_and_allows_later_setup(
    new_context, live_url, users, start_chat
):
    alice, _ = users
    page = new_context().new_page()
    page.goto(f"{live_url}/auth/register")
    page.get_by_label("Your name", exact=True).fill("Dana")
    page.get_by_label("Username", exact=True).fill("dana")
    page.get_by_label("Password", exact=True).fill("correct-horse-battery")
    page.get_by_label("Confirm password", exact=True).fill("correct-horse-battery")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("dialog", name="Set up encrypted private chat")).to_contain_text(
        "no backup, recovery, key reset, or multi-device support"
    )
    page.get_by_role("button", name="Not now").click()
    expect(page.locator("#conversation-list")).to_contain_text(
        "Your conversations will show up here"
    )
    start_chat(page, "alice", "Alice")
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Enable first, then send")
    draft.press("Enter")
    expect(draft).to_have_value("Enable first, then send")
    expect(page.locator("#send-button")).to_be_disabled()
    page.get_by_role("button", name="Retry encryption").click()
    page.get_by_role("button", name="Enable on this browser").click()
    expect(page.locator("#encryption-status")).to_contain_text("New messages are end-to-end")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.locator(".message-bubble")).to_have_text("Enable first, then send")
    alice.get_by_role("button", name="Open conversation with Dana").click()
    expect(alice.locator(".message-bubble")).to_have_text("Enable first, then send")
