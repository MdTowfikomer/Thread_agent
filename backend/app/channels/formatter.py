import json
import re
from typing import Any, Optional
from app.core.canonical import ChannelType


def coerce_model_text(value: Any) -> str:
    """
    Safely extract plain text from strings, lists, and provider content dictionaries.
    Handles Gemini, LiteLLM, OpenAI, and LangChain model output structures:
      - "Hello from Thread."
      - [{"type": "text", "text": "Hello from Thread."}]
      - [{"text": "Hello from Thread."}]
      - {"type": "text", "text": "Hello from Thread."}
      - ["Hello", "world"]
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [coerce_model_text(item) for item in value]
        return " ".join([p for p in parts if p]).strip()
    if isinstance(value, dict):
        if "text" in value and isinstance(value["text"], str):
            return value["text"]
        if "content" in value:
            return coerce_model_text(value["content"])
        if "text" in value:
            return coerce_model_text(value["text"])
        return json.dumps(value) if value else ""
    return str(value)


def clean_debug_headers_and_footers(text: Any) -> str:
    """
    Strips internal debug headers (e.g. '**Context Update from...**')
    and debug footers (e.g. '*(Confidence: ... | Receipt ID: ...)*').
    Defensively accepts Any and coerces structured content to plain text.
    """
    text_str = coerce_model_text(text)
    if not text_str:
        return ""

    # Remove '**Context Update from ...**:' headers
    text_str = re.sub(r"\*\*Context Update from[^*]+\*\*:\s*", "", text_str, flags=re.IGNORECASE)
    text_str = re.sub(r"Context Update from[^:\n]+:\s*", "", text_str, flags=re.IGNORECASE)
    text_str = re.sub(r"^Based on verified (?:organizational )?records (?:in|for) [^:\n]+:\s*", "", text_str, flags=re.IGNORECASE)


    # Remove '*(Confidence: ... | Receipt ID: ...)*' footers
    text_str = re.sub(r"\*\s*\(\s*Confidence:[^*]+\*\s*", "", text_str, flags=re.IGNORECASE)
    # Remove '*(Receipt ID: ... | Strategy: ...)*' footers
    text_str = re.sub(r"\*\s*\(\s*Receipt ID:[^*]+\*\s*", "", text_str, flags=re.IGNORECASE)

    # Strip leading/trailing blank lines
    return text_str.strip()


def convert_markdown_to_telegram_html(text: Any) -> str:
    """
    Converts standard Markdown formatting to Telegram-compatible HTML tags:
      - **bold** -> <b>bold</b>
      - *italic* or _italic_ -> <i>italic</i>
      - `code` -> <code>code</code>
      - ```code block``` -> <pre>code block</pre>
    Escapes unhandled '<' and '>' characters for safety.
    Defensively accepts Any and coerces structured content to plain text.
    """
    text_str = coerce_model_text(text)
    if not text_str:
        return ""

    cleaned = clean_debug_headers_and_footers(text_str)

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

    # Markdown list markers are not italic delimiters. Convert them before
    # applying inline emphasis so Telegram receives readable bullets.
    cleaned = re.sub(r"(?m)^\s*[-*]\s+", "• ", cleaned)

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


def convert_markdown_to_slack_mrkdwn(text: Any) -> str:
    """
    Converts standard Markdown formatting to Slack mrkdwn syntax:
      - **bold** -> *bold*
      - *italic* or _italic_ -> _italic_
      - `code` -> `code`
    Strips internal debug headers and footers.
    Defensively accepts Any and coerces structured content to plain text.
    """
    text_str = coerce_model_text(text)
    if not text_str:
        return ""

    cleaned = clean_debug_headers_and_footers(text_str)

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


def format_response_for_platform(text: Any, platform: ChannelType) -> str:
    """
    Format synthesized ThreadAgent response for a specific delivery channel platform.
    Strips raw debug headers/footers and applies platform-native markup.
    Defensively accepts Any and coerces structured content to plain text.
    """
    text_str = coerce_model_text(text)
    if not text_str:
        return ""

    if platform == ChannelType.TELEGRAM:
        return convert_markdown_to_telegram_html(text_str)
    elif platform == ChannelType.SLACK:
        return convert_markdown_to_slack_mrkdwn(text_str)
    else: # Discord or default
        cleaned = clean_debug_headers_and_footers(text_str)
        # Safety sweep for Discord too
        cleaned = re.sub(r"XINLINECODEX\d+X", "", cleaned)
        cleaned = re.sub(r"XCODEBLOCKX\d+X", "", cleaned)
        cleaned = re.sub(r"___INLINE_CODE_\d+___", "", cleaned)
        return cleaned.strip()
