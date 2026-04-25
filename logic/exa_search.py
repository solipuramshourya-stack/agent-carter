# logic/exa_search.py
import logging
import re
import html
from exa_py import Exa

from logic.config import get_exa_api_key, get_search_result_limit

logger = logging.getLogger(__name__)

_exa_client = None


def _get_exa() -> Exa:
    global _exa_client
    if _exa_client is None:
        _exa_client = Exa(get_exa_api_key())
    return _exa_client


# -------------------------------
# Basic prompt-injection sanitizer
# -------------------------------
def sanitize_text(text: str) -> str:
    """
    Very lightweight cleaner to reduce the risk of prompt injection
    from EXA / LinkedIn content before it is passed to the LLM.

    - Handles None safely
    - Strips HTML/JS tags
    - Removes common jailbreak / override phrases
    - Removes code blocks
    - Strips unicode direction overrides
    """
    if not text:
        return ""

    cleaned = str(text)

    # Remove unicode direction overrides
    cleaned = cleaned.replace("\u202e", "").replace("\u202d", "")

    # Escape HTML tags (so <script> etc. can't be interpreted later)
    cleaned = html.escape(cleaned)

    # Remove obvious code blocks that could contain prompts
    cleaned = re.sub(r"```.*?```", "[code removed]", cleaned, flags=re.DOTALL)

    # Very small set of common jailbreak / override phrases
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
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            cleaned = re.sub(pattern, "[removed for safety]", cleaned, flags=re.IGNORECASE)

    return cleaned


def run_exa(query: str, num_results: int | None = None):
    if num_results is None:
        num_results = get_search_result_limit()

    q = f"site:linkedin.com/in {query}"
    resp = _get_exa().search(
        query=q,
        num_results=num_results,
        type="keyword",
        contents={"text": {"max_characters": 5000}},
    )

    results = []
    for r in resp.results:
        results.append(
            {
                "full_name": sanitize_text(r.title or ""),
                "linkedin_url": r.url,
                "headline": "",
                "summary": sanitize_text(r.text or ""),
            }
        )
    logger.debug("Exa returned %d results for query prefix", len(results))
    return results
