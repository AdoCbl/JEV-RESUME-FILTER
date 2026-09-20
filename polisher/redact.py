"""PII redaction before sending text to any external API (Item 8).

Strips email, phone, address patterns, and URLs so that contact details never
leave the machine when ``--redact`` is passed. The redacted markers are stable so
that the writer can still produce sensible structure.
"""

from __future__ import annotations

import re

# Ordered from most specific to most general so they do not overlap.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"https?://\S+"), "[URL]"),
    (re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b"), "[PHONE]"),
    # LinkedIn / GitHub handles
    (re.compile(r"linkedin\.com/in/\S+", re.IGNORECASE), "[LINKEDIN]"),
    (re.compile(r"github\.com/\S+", re.IGNORECASE), "[GITHUB]"),
    # Simple US-style street address: number + street name + road type
    (
        re.compile(
            r"\b\d{1,5}\s+[A-Za-z0-9\s]{2,40}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard"
            r"|Dr|Drive|Ln|Lane|Ct|Court|Pl|Place|Way)\b",
            re.IGNORECASE,
        ),
        "[ADDRESS]",
    ),
]


def redact(text: str) -> str:
    """Replace recognisable PII patterns with stable placeholders."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
