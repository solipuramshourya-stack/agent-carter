# logic/safety_agent.py

import re
import html

# Injection keyword patterns
INJECTION_PATTERNS = [
    r"ignore (all|previous) instructions",
    r"reset system prompt",
    r"override.*system",
    r"please pretend",
    r"act as (DAN|an unfiltered)",
    r"you are no longer",
    r"bypass safety",
    r"disregard the above",
    r"run javascript",
    r"<script>",
]

def sanitize_input(text: str) -> str:
    """
    Removes suspicious patterns, HTML/JS, and dangerous instructions.
    Replaces them with neutral placeholders.
    """

    if not text:
        return ""

    # Remove HTML/JS tags
    cleaned = html.escape(text)

    # Normalize unicode
    cleaned = cleaned.replace("\u202e", "")   # Right-to-left override
    cleaned = cleaned.replace("\u202d", "")   # Left-to-right override

    # Remove known injection patterns
    lowered = cleaned.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            cleaned = re.sub(pattern, "[removed for safety]", cleaned, flags=re.IGNORECASE)

    # Prevent nested prompt attempts like “```json {…} ```”
    cleaned = re.sub(r"```.*?```", "[removed code block]", cleaned, flags=re.DOTALL)

    return cleaned
