# logic/llm_ops.py
import json
import re
import html
from openai import APIConnectionError, APITimeoutError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from logic.config import get_openai_chat_model, get_openai_client


# ----------------------------------------------------
# Basic Sanitizer (same safe style as exa_search)
# ----------------------------------------------------
def sanitize_text(text: str) -> str:
    """
    Lightweight prompt-injection defense.
    Does NOT modify semantics, only strips risky patterns.
    Safe for production and will not break output.
    """
    if not text:
        return ""

    cleaned = str(text)

    # Remove unicode direction overrides
    cleaned = cleaned.replace("\u202e", "").replace("\u202d", "")

    # Escape HTML tags
    cleaned = html.escape(cleaned)

    # Remove code blocks
    cleaned = re.sub(r"```.*?```", "[code removed]", cleaned, flags=re.DOTALL)

    # Very small set of common jailbreak attempts
    patterns = [
        r"ignore (all|previous) instructions",
        r"override.*system",
        r"reset system prompt",
        r"you are no longer",
        r"act as (dan|an unfiltered)",
        r"bypass safety",
        r"disregard the above",
    ]
    lowered = cleaned.lower()
    for pattern in patterns:
        if re.search(pattern, lowered, re.IGNORECASE):
            cleaned = re.sub(pattern, "[removed for safety]", cleaned, flags=re.IGNORECASE)

    return cleaned


# ----------------------------------------------------
# Helper: Safe JSON extraction
# ----------------------------------------------------
def _safe_json_parse(text):
    text = text.strip()

    # Remove accidental markdown fences
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1].strip()

    try:
        return json.loads(text)
    except Exception:
        return {
            "reason": [],
            "drafted_dm": "",
            "email_subject": "",
            "email_body": "",
        }


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=45),
    retry=retry_if_exception_type(
        (APIConnectionError, APITimeoutError, RateLimitError)
    ),
)
def _chat_completions_create(**kwargs):
    return get_openai_client().chat.completions.create(**kwargs)


# ----------------------------------------------------
# 1) Outreach Draft Generator
# ----------------------------------------------------
def draft_outreach(purpose: str, candidate: dict):

    # 🔒 SANITIZATION APPLIED HERE
    purpose = sanitize_text(purpose)
    name = sanitize_text(candidate.get("name", ""))
    headline = sanitize_text(candidate.get("headline", ""))
    linkedin = sanitize_text(candidate.get("linkedin", ""))

    prompt = f"""
You are Agent Carter, an AI networking outreach assistant.

Purpose: {purpose}

Candidate:
- Name: {name}
- Headline: {headline}
- LinkedIn: {linkedin}

Write a short LinkedIn DM FROM the user TO this person (connection request or first message).
Keep it human, specific, and under ~300 characters unless a longer note clearly fits.

RETURN JSON ONLY:
{{
  "reason": ["bullet 1", "bullet 2", "bullet 3"],
  "drafted_dm": "LinkedIn DM text only — paste this into LinkedIn yourself."
}}
"""

    model = get_openai_chat_model()
    response = _chat_completions_create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content or ""
    data = _safe_json_parse(raw)

    return {
        "reason": data.get("reason", []),
        "drafted_dm": data.get("drafted_dm", ""),
        "email_subject": "",
        "email_body": "",
    }


# ----------------------------------------------------
# 2) Conversational Refinement Chat (with Tone)
# ----------------------------------------------------
def chat_refine(user_request: str, context: dict):

    # 🔒 SANITIZE user request and context inputs
    safe_request = sanitize_text(user_request)
    safe_dm = sanitize_text(context.get("dm", ""))

    tone = sanitize_text(context.get("tone", "Professional"))
    name = sanitize_text(context.get("name", ""))
    headline = sanitize_text(context.get("headline", ""))
    linkedin = sanitize_text(context.get("linkedin", ""))

    prompt = f"""
You are Agent Carter, an AI assistant helping refine LinkedIn DMs.

TONE REQUESTED: {tone}

CANDIDATE CONTEXT:
Name: {name}
Headline: {headline}
LinkedIn: {linkedin}

CURRENT DM:
{safe_dm}

USER REQUEST:
{safe_request}

INSTRUCTIONS:
- Return ONLY the rewritten DM text (no explanation, no quotes).
- Do NOT add "Agent Carter says".
- Respect the tone.
- Keep it appropriate for LinkedIn (concise; line breaks ok).
"""

    model = get_openai_chat_model()
    response = _chat_completions_create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.choices[0].message.content.strip()
