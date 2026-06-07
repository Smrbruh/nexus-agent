"""
utils/helpers.py — Shared utility functions for NEXUS Agent
"""
import hashlib
import html
import re
import textwrap
import time
from datetime import datetime
from typing import Any


def truncate(text: str, max_len: int = 4000, suffix: str = "…") -> str:
    """Truncate text to max_len characters, appending suffix if truncated."""
    if len(text) <= max_len:
        return text
    # Reserve space for suffix (suffix is a 3-byte UTF-8 char, len=1)
    return text[: max_len - 1] + suffix


def sanitize_for_telegram(text: str) -> str:
    """
    Escape special Markdown V2 characters for Telegram.
    Only use with parse_mode=MarkdownV2.
    """
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", text)


def clean_html(raw: str) -> str:
    """Strip HTML tags and unescape entities."""
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def chunk_text(text: str, size: int = 4000) -> list[str]:
    """Split text into chunks of at most `size` characters."""
    return textwrap.wrap(text, size, break_long_words=False, replace_whitespace=False)


def timestamp() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.utcnow().isoformat()


def sha256(text: str) -> str:
    """Return SHA-256 hex digest of text."""
    return hashlib.sha256(text.encode()).hexdigest()


def format_tool_result(tool_name: str, result: Any) -> str:
    """Format a tool result for display in chat."""
    divider = "─" * 40
    return f"🔧 **Tool:** `{tool_name}`\n{divider}\n{result}\n{divider}"


def rate_limiter(seconds: float):
    """Simple blocking rate limiter — sleep for `seconds`."""
    time.sleep(seconds)


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from a text string."""
    pattern = r"https?://[^\s\)\]>\"']+"
    return re.findall(pattern, text)


def is_valid_ip(ip: str) -> bool:
    """Basic IPv4 validation."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def is_valid_domain(domain: str) -> bool:
    """Basic domain name validation."""
    pattern = r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
    return bool(re.match(pattern, domain))
