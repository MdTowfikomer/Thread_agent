import re
from typing import Optional
from app.core.canonical import ChannelType

def clean_debug_headers_and_footers(text: str) -> str:
    """
    Strips internal debug headers (e.g. '**Context Update from...**')
    and debug footers (e.g. '*(Confidence: ... | Receipt ID: ...)*').
    """
    if not text:
        return ""

    # Remove '**Context Update from ...**:' headers
    text = re.sub(r"\*\*Context Update from[^*]+\*\*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Context Update from[^:\n]+:\s*", "", text, flags=re.IGNORECASE)

    # Remove '*(Confidence: ... | Receipt ID: ...)*' footers
    text = re.sub(r"\*\s*\(\s*Confidence:[^*]+\*\s*", "", text, flags=re.IGNORECASE)
    # Remove '*(Receipt ID: ... | Strategy: ...)*' footers
    text = re.sub(r"\*\s*\(\s*Receipt ID:[^*]+\*\s*", "", text, flags=re.IGNORECASE)

    # Strip leading/trailing blank lines
    return text.strip()


def convert_markdown_to_telegram_html(text: str) -> str:
    """
    Converts standard Markdown formatting to Telegram-compatible HTML tags:
      - **bold** -> <b>bold</b>
      - *italic* or _italic_ -> <i>italic</i>
      - `code` -> <code>code</code>
      - ```code block``` -> <pre>code block</pre>
    Escapes unhandled '<' and '>' characters for safety.
    """
    if not text:
        return ""

    cleaned = clean_debug_headers_and_footers(text)

    # Protect code blocks first using alphanumeric placeholders without underscores or asterisks
    code_blocks = []
    def save_code_block(match):
        code_blocks.append(match.group(1))
        return f"XCODEBLOCKX{len(code_blocks)-1}X"

    cleaned = re.sub(r"```(?:\w+)?\n?(.*?)```", save_code_block, cleaned, flags=re.DOTALL)

    # Protect inline code using alphanumeric placeholders
    inline_codes = []
    def save_inline_code(match):
        inline_codes.append(match.group(1))
        return f"XINLINECODEX{len(inline_codes)-1}X"

    cleaned = re.sub(r"`([^`]+)`", save_inline_code, cleaned)

    # Escape raw HTML characters in remaining text
    cleaned = cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Convert **bold** to <b>bold</b>
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", cleaned)

    # Convert *italic* or _italic_ to <i>italic</i>
    cleaned = re.sub(r"\*(.*?)\*", r"<i>\1</i>", cleaned)
    cleaned = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"<i>\1</i>", cleaned)

    # Restore inline code as <code>
    for i, code in enumerate(inline_codes):
        safe_code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cleaned = cleaned.replace(f"XINLINECODEX{i}X", f"<code>{safe_code}</code>")

    # Restore code blocks as <pre>
    for i, code in enumerate(code_blocks):
        safe_code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cleaned = cleaned.replace(f"XCODEBLOCKX{i}X", f"<pre>{safe_code}</pre>")

    # Safety sweep: remove any un-replaced placeholder artifacts if present
    cleaned = re.sub(r"XINLINECODEX\d+X", "", cleaned)
    cleaned = re.sub(r"XCODEBLOCKX\d+X", "", cleaned)
    cleaned = re.sub(r"___INLINE_CODE_\d+___", "", cleaned)

    return cleaned.strip()


def convert_markdown_to_slack_mrkdwn(text: str) -> str:
    """
    Converts standard Markdown formatting to Slack mrkdwn syntax:
      - **bold** -> *bold*
      - *italic* or _italic_ -> _italic_
      - `code` -> `code`
    Strips internal debug headers and footers.
    """
    if not text:
        return ""

    cleaned = clean_debug_headers_and_footers(text)

    # Protect code blocks and inline code
    code_blocks = []
    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f"XCODEBLOCKX{len(code_blocks)-1}X"

    cleaned = re.sub(r"```(?:\w+)?\n?(.*?)```", save_code_block, cleaned, flags=re.DOTALL)

    inline_codes = []
    def save_inline_code(match):
        inline_codes.append(match.group(0))
        return f"XINLINECODEX{len(inline_codes)-1}X"

    cleaned = re.sub(r"`([^`]+)`", save_inline_code, cleaned)

    # Convert **bold** -> *bold*
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"*\1*", cleaned)

    # Restore code blocks and inline code
    for i, code in enumerate(inline_codes):
        cleaned = cleaned.replace(f"XINLINECODEX{i}X", code)

    for i, code in enumerate(code_blocks):
        cleaned = cleaned.replace(f"XCODEBLOCKX{i}X", code)

    # Safety sweep
    cleaned = re.sub(r"XINLINECODEX\d+X", "", cleaned)
    cleaned = re.sub(r"XCODEBLOCKX\d+X", "", cleaned)
    cleaned = re.sub(r"___INLINE_CODE_\d+___", "", cleaned)

    return cleaned.strip()


def format_response_for_platform(text: str, platform: ChannelType) -> str:
    """
    Format synthesized ThreadAgent response for a specific delivery channel platform.
    Strips raw debug headers/footers and applies platform-native markup.
    """
    if not text:
        return ""

    if platform == ChannelType.TELEGRAM:
        return convert_markdown_to_telegram_html(text)
    elif platform == ChannelType.SLACK:
        return convert_markdown_to_slack_mrkdwn(text)
    else: # Discord or default
        cleaned = clean_debug_headers_and_footers(text)
        # Safety sweep for Discord too
        cleaned = re.sub(r"XINLINECODEX\d+X", "", cleaned)
        cleaned = re.sub(r"XCODEBLOCKX\d+X", "", cleaned)
        cleaned = re.sub(r"___INLINE_CODE_\d+___", "", cleaned)
        return cleaned.strip()
