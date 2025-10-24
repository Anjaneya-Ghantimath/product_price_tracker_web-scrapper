"""Input validators and sanitizers."""

from __future__ import annotations

import re
from typing import Optional


URL_REGEX = re.compile(r"^https?://[\w\.-]+(?:/[\w\-./?%&=]*)?$")


def is_valid_url(url: str) -> bool:
    """Validate URL to avoid SQLi/XSS vectors."""
    if not url or len(url) > 2048:
        return False
    return bool(URL_REGEX.match(url))


def sanitize_text(value: Optional[str], max_len: int = 256) -> Optional[str]:
    if value is None:
        return None
    clean = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", value)
    return clean[:max_len]


