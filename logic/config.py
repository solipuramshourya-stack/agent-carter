"""
Central configuration: env vars, optional Streamlit secrets, then settings.json.

Order of precedence for most values: environment → Streamlit secrets → settings_store.
Secrets (API keys) should live in env or Streamlit secrets, not committed JSON.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any, Mapping

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _streamlit_secrets() -> Mapping[str, Any] | None:
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets:
            return st.secrets
    except Exception:
        pass
    return None


def get_env_or_secret(name: str) -> str | None:
    """Single string: OS env (uppercase) then Streamlit secret of same name."""
    v = os.environ.get(name)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    sec = _streamlit_secrets()
    if sec is not None and name in sec:
        val = sec[name]
        if isinstance(val, (dict, list)):
            return json.dumps(val)
        return str(val).strip() if val is not None else None
    return None


def require_env_or_secret(name: str) -> str:
    v = get_env_or_secret(name)
    if not v:
        raise RuntimeError(
            f"{name} is not set. Use environment variable or Streamlit secrets."
        )
    return v


def get_openai_api_key() -> str:
    return require_env_or_secret("OPENAI_API_KEY")


def get_exa_api_key() -> str:
    return require_env_or_secret("EXA_API_KEY")


def get_http_timeout_seconds() -> float:
    raw = os.environ.get("HTTP_TIMEOUT_SECONDS", "60")
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 60.0


@lru_cache(maxsize=1)
def get_openai_client():
    from openai import OpenAI

    return OpenAI(
        api_key=get_openai_api_key(),
        timeout=get_http_timeout_seconds(),
        max_retries=0,
    )


def get_openai_chat_model() -> str:
    v = get_env_or_secret("OPENAI_MODEL")
    if v:
        return v
    try:
        from logic.settings_store import settings_store

        m = settings_store.get("openai_model")
        if m:
            return str(m).strip()
    except Exception as e:
        logger.debug("settings_store openai_model: %s", e)
    return "gpt-4o-mini"


def get_openai_embedding_model() -> str:
    v = get_env_or_secret("OPENAI_EMBED_MODEL")
    if v:
        return v
    try:
        from logic.settings_store import settings_store

        m = settings_store.get("openai_embed_model")
        if m:
            return str(m).strip()
    except Exception as e:
        logger.debug("settings_store openai_embed_model: %s", e)
    return "text-embedding-3-small"


def get_search_result_limit() -> int:
    raw = os.environ.get("SEARCH_RESULT_LIMIT")
    if raw is not None:
        try:
            return max(1, min(50, int(raw)))
        except ValueError:
            pass
    try:
        from logic.settings_store import settings_store

        n = settings_store.get("search_result_limit", 10)
        return max(1, min(50, int(n)))
    except Exception:
        return 10


def get_gmail_token_dict() -> dict:
    """OAuth token JSON for gmail_send_email (same shape as before)."""
    sec = _streamlit_secrets()
    if sec is not None and "GMAIL_TOKEN" in sec:
        val = sec["GMAIL_TOKEN"]
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            return json.loads(val)
    raw = os.environ.get("GMAIL_TOKEN_JSON")
    if raw:
        return json.loads(raw)
    raise RuntimeError(
        "GMAIL_TOKEN (Streamlit secrets) or GMAIL_TOKEN_JSON (env) is not configured."
    )
