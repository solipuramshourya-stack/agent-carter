# logic/llm_ops.py
import os
import json
import re
import html
from openai import OpenAI
import streamlit as st


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
# ENV + CLIENT
# ----------------------------------------------------
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing.")

client = OpenAI(api_key=OPENAI_API_KEY)

OPENAI_MODEL = "gpt-4o-mini"



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

WRITE OUTREACH FROM Agent Carter → TO THIS PERSON.

EMAIL RULES:
- Do NOT use the candidate name in greeting.
- Start email with "Hi there,".
- Use clear paragraph breaks (\\n\\n).
- End with:
  Best regards,
  

RETURN JSON ONLY:
{{
  "reason": ["bullet 1", "bullet 2", "bullet 3"],
  "drafted_dm": "Short LinkedIn DM",
  "email_subject": "Short subject",
  "email_body": "120-word email body"
}}
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content
    data = _safe_json_parse(raw)

    return {
        "reason": data.get("reason", []),
        "drafted_dm": data.get("drafted_dm", ""),
        "email_subject": data.get("email_subject", ""),
        "email_body": data.get("email_body", ""),
    }


# ----------------------------------------------------
# 2) Conversational Refinement Chat (with Tone)
# ----------------------------------------------------
def chat_refine(user_request: str, context: dict):

    # 🔒 SANITIZE user request and context inputs
    safe_request = sanitize_text(user_request)
    safe_dm = sanitize_text(context.get("dm", ""))
    safe_email_body = sanitize_text(context.get("email_body", ""))

    tone = sanitize_text(context.get("tone", "Professional"))
    name = sanitize_text(context.get("name", ""))
    headline = sanitize_text(context.get("headline", ""))
    linkedin = sanitize_text(context.get("linkedin", ""))

    prompt = f"""
You are Agent Carter, an AI assistant helping refine networking messages.

TONE REQUESTED: {tone}

CANDIDATE CONTEXT:
Name: {name}
Headline: {headline}
LinkedIn: {linkedin}

CURRENT DM:
{safe_dm}

CURRENT EMAIL BODY:
{safe_email_body}

USER REQUEST:
{safe_request}

INSTRUCTIONS:
- Return ONLY the rewritten content (no explanation).
- Do NOT add "Agent Carter says".
- Respect the tone.
- Keep email paragraphing clean with \\n\\n.
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()
