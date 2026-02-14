"""Content moderation for messages and images.

Pluggable moderation system. The default implementation provides basic
keyword filtering. External moderation APIs can be plugged in by
replacing the `moderate_content` and `moderate_image` functions.
"""

from __future__ import annotations

import re

# Words/patterns that trigger content filtering
# This is a basic blocklist — replace with a proper moderation API for production
_BLOCKED_PATTERNS: list[re.Pattern] = []

# Flag to enable/disable moderation (useful for testing)
_enabled = True


class ModerationError(Exception):
    """Raised when content fails moderation."""
    pass


def configure_moderation(
    enabled: bool = True,
    blocked_words: list[str] | None = None,
) -> None:
    """Configure the moderation system."""
    global _enabled, _BLOCKED_PATTERNS
    _enabled = enabled
    if blocked_words:
        _BLOCKED_PATTERNS = [
            re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE)
            for w in blocked_words
        ]


def moderate_content(content: str) -> str:
    """Check text content against moderation rules.

    Returns the content (possibly filtered) if it passes.
    Raises ModerationError if it should be blocked.
    """
    if not _enabled:
        return content

    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(content):
            raise ModerationError(
                "Message blocked by content filter. "
                "Please keep content appropriate for all audiences."
            )

    return content


def moderate_image(image_url: str) -> str:
    """Check an image URL against moderation rules.

    This is a placeholder for external image moderation APIs.
    In production, this would call a service like AWS Rekognition,
    Google Cloud Vision, or similar to check for NSFW content.

    Returns the URL if it passes, raises ModerationError if blocked.
    """
    if not _enabled:
        return image_url

    # Require HTTPS — block plain HTTP (MITM risk) and data URIs (bomb risk)
    if not image_url.startswith("https://"):
        raise ModerationError("Image URLs must use HTTPS")

    # Block internal/private network URLs (SSRF prevention)
    from urllib.parse import urlparse

    parsed = urlparse(image_url)
    hostname = parsed.hostname or ""
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if hostname in blocked_hosts:
        raise ModerationError("Image URLs cannot reference local addresses")
    # Block RFC 1918 private ranges and link-local
    if hostname.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.",
                           "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
                           "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
                           "172.29.", "172.30.", "172.31.", "169.254.")):
        raise ModerationError("Image URLs cannot reference private network addresses")

    # Placeholder: in production, call an external moderation API here
    # Example integration points:
    # - AWS Rekognition DetectModerationLabels
    # - Google Cloud Vision SafeSearch
    # - Azure Content Moderator
    # - OpenAI moderation endpoint

    return image_url
