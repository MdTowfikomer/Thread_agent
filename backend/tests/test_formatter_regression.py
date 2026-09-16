import pytest
from app.channels.formatter import convert_markdown_to_telegram_html, convert_markdown_to_slack_mrkdwn, format_response_for_platform
from app.core.canonical import ChannelType

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
