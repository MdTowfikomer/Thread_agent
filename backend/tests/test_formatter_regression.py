import pytest
from types import SimpleNamespace
from app.channels.formatter import convert_markdown_to_telegram_html, convert_markdown_to_slack_mrkdwn, format_response_for_platform
from app.core.canonical import ChannelType
from app.channels.outbound import ChannelMessageDeliveryService

def test_formatter_no_placeholder_leak():
    sample_text = (
        "Here are the details for `!events` and `!faq` commands:\n\n"
        "Check out `!github` for the repo.\n"
        "Here is some code:\n"
        "```python\n"
        "def hello_world():\n"
        "    print('Hello_World_Test')\n"
        "```\n\n"
        "*(Confidence: 0.95 | Receipt ID: rec_12345)*"
    )

    # 1. Telegram
    html = convert_markdown_to_telegram_html(sample_text)
    assert "XINLINECODEX" not in html
    assert "XCODEBLOCKX" not in html
    assert "___INLINE_CODE_" not in html
    assert "Confidence:" not in html
    assert "<code>!events</code>" in html
    assert "<pre>" in html

    # 2. Slack
    mrkdwn = convert_markdown_to_slack_mrkdwn(sample_text)
    assert "XINLINECODEX" not in mrkdwn
    assert "XCODEBLOCKX" not in mrkdwn
    assert "___INLINE_CODE_" not in mrkdwn
    assert "Confidence:" not in mrkdwn
    assert "`!events`" in mrkdwn

    # 3. Discord
    discord_out = format_response_for_platform(sample_text, ChannelType.DISCORD)
    assert "XINLINECODEX" not in discord_out
    assert "XCODEBLOCKX" not in discord_out
    assert "___INLINE_CODE_" not in discord_out
    assert "Confidence:" not in discord_out


def test_prepared_telegram_message_is_formatted_exactly_once(monkeypatch):
    class FakeAuditStore:
        def claim(self, *_args, **_kwargs):
            return True, None

        def finish(self, *_args, **_kwargs):
            return None

    sent = {}

    class FakeAdapter:
        def send(self, _destination, text, _key):
            sent["text"] = text
            return "42"

    service = ChannelMessageDeliveryService(audit_store=FakeAuditStore())
    service.adapters[ChannelType.TELEGRAM] = FakeAdapter()
    monkeypatch.setattr(service, "_resolve_destination", lambda *_args: {"chat_id": "123"})

    source = "* **Date & Time:** Saturday at 3:00 PM"
    service.send_prepared_message(
        principal=SimpleNamespace(organization_id="gdg_mcet", user_id="demo_judge"),
        platform=ChannelType.TELEGRAM,
        destination_id="123",
        text=source,
        idempotency_key="telegram-format-once",
    )

    assert sent["text"] == source


def test_telegram_event_list_renders_as_bullets_and_html():
    formatted = convert_markdown_to_telegram_html(
        "* **Date & Time:** Saturday at 3:00 PM\n* **Location:** Lab 2"
    )

    assert formatted == "• <b>Date &amp; Time:</b> Saturday at 3:00 PM\n• <b>Location:</b> Lab 2"
    assert "\\*" not in formatted
    assert "&lt;b&gt;" not in formatted
