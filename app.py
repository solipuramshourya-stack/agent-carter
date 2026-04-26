import streamlit as st
import base64
import hashlib
import pandas as pd
import json, re
import html

import streamlit.components.v1 as components

from logic.candidate_match import (
    build_search_digest_body,
    candidate_from_lancedb_row,
    format_match_line,
    row_vector_distance,
)
from logic.config import get_search_result_limit
from logic.db_ops import (
    insert_contacts,
    ingest_lancedb,
    search_lancedb,
    add_to_queue,
    fetch_queue,
)
from logic.email_ops import gmail_send_email
from logic.exa_search import run_exa
from logic.llm_ops import draft_outreach, chat_refine


# -------------------------------------------------------
# BASIC SANITIZER (same style as llm_ops + exa_search)
# -------------------------------------------------------
def sanitize_text(text):
    if not text:
        return ""
    cleaned = str(text)
    cleaned = cleaned.replace("\u202e", "").replace("\u202d", "")
    cleaned = html.escape(cleaned)
    cleaned = re.sub(r"```.*?```", "[code removed]", cleaned, flags=re.DOTALL)
    patterns = [
        r"ignore (all|previous) instructions",
        r"override.*system",
        r"reset system prompt",
        r"you are no longer",
        r"act as (dan|an unfiltered)",
        r"bypass safety",
        r"disregard the above",
    ]
    for p in patterns:
        cleaned = re.sub(p, "[removed for safety]", cleaned, flags=re.IGNORECASE)
    return cleaned


# -------------------------------------------------------
# PAGE CONFIG + THEME
# -------------------------------------------------------
st.set_page_config(page_title="Agent Carter", page_icon="🕵️", layout="wide")

st.markdown(
    """
<style>
    :root {
        --ac-bg: #0b0f17;
        --ac-panel: rgba(22, 28, 42, 0.82);
        --ac-panel-strong: rgba(29, 37, 55, 0.95);
        --ac-border: rgba(148, 163, 184, 0.18);
        --ac-muted: #9ca3af;
        --ac-text: #f8fafc;
        --ac-accent: #ff4b5c;
        --ac-accent-2: #f59e0b;
    }

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(255, 75, 92, 0.18), transparent 30rem),
            radial-gradient(circle at top right, rgba(245, 158, 11, 0.12), transparent 26rem),
            var(--ac-bg);
    }

    .block-container {
        max-width: 1220px;
        padding-top: 2.2rem;
        padding-bottom: 4rem;
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    h1, h2, h3 {
        letter-spacing: -0.035em;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--ac-border);
        background: var(--ac-panel);
        box-shadow: 0 18px 55px rgba(0, 0, 0, 0.26);
        backdrop-filter: blur(14px);
    }

    div[data-testid="stButton"] > button,
    div[data-testid="stDownloadButton"] > button,
    div[data-testid="stLinkButton"] > a {
        border-radius: 0.75rem;
        font-weight: 650;
        border: 1px solid rgba(148, 163, 184, 0.25);
        transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
    }

    div[data-testid="stButton"] > button:hover,
    div[data-testid="stDownloadButton"] > button:hover,
    div[data-testid="stLinkButton"] > a:hover {
        transform: translateY(-1px);
        border-color: rgba(255, 75, 92, 0.55);
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.22);
    }

    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea,
    div[data-baseweb="select"] > div {
        border-radius: 0.8rem;
        border-color: rgba(148, 163, 184, 0.22);
        background: rgba(15, 23, 42, 0.75);
    }

    .ac-hero {
        padding: 1.45rem 1.6rem;
        margin-bottom: 1.25rem;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 1.35rem;
        background:
            linear-gradient(135deg, rgba(255, 75, 92, 0.20), rgba(245, 158, 11, 0.10)),
            rgba(15, 23, 42, 0.86);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.28);
    }

    .ac-kicker {
        color: #fecdd3;
        font-size: 0.78rem;
        font-weight: 800;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
    }

    .ac-hero h1 {
        margin: 0;
        font-size: clamp(2rem, 4vw, 3.4rem);
        line-height: 1.02;
    }

    .ac-hero p {
        color: #cbd5e1;
        max-width: 720px;
        margin: 0.8rem 0 0;
        font-size: 1.03rem;
    }

    .ac-pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.55rem;
        margin-top: 1.1rem;
    }

    .ac-pill {
        color: #e5e7eb;
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 999px;
        padding: 0.35rem 0.7rem;
        background: rgba(15, 23, 42, 0.55);
        font-size: 0.84rem;
    }

    .ac-section-eyebrow {
        color: var(--ac-accent-2);
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.13em;
        text-transform: uppercase;
        margin-bottom: 0.25rem;
    }

    .ac-card-title {
        margin: 0 0 0.25rem;
        font-size: 1.25rem;
        font-weight: 800;
    }

    .ac-muted {
        color: var(--ac-muted);
        font-size: 0.92rem;
    }

    .ac-result-rank {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2rem;
        height: 2rem;
        border-radius: 999px;
        background: rgba(255, 75, 92, 0.18);
        color: #fecdd3;
        font-weight: 800;
        margin-bottom: 0.5rem;
    }

    .ac-chat-bubble {
        padding: 0.8rem 0.95rem;
        border-radius: 1rem;
        margin: 0.45rem 0;
        border: 1px solid rgba(148, 163, 184, 0.16);
    }

    .ac-chat-user {
        background: rgba(255, 75, 92, 0.15);
        margin-left: 12%;
    }

    .ac-chat-bot {
        background: rgba(30, 41, 59, 0.82);
        margin-right: 12%;
    }
</style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="ac-hero">
    <div class="ac-kicker">Agent Carter</div>
    <h1>Find warm intros faster.</h1>
    <p>Search for high-signal candidates, rank them semantically, and generate LinkedIn outreach you can refine before sending.</p>
    <div class="ac-pill-row">
        <span class="ac-pill">Semantic candidate search</span>
        <span class="ac-pill">Queue-first outreach</span>
        <span class="ac-pill">Draft, refine, copy</span>
    </div>
</div>
    """,
    unsafe_allow_html=True,
)


# -------------------------------------------------------
# MULTI-USER SUPPORT
# -------------------------------------------------------
if "user_id" not in st.session_state:
    st.session_state.user_id = (
        st.experimental_user.get("email", None)
        if hasattr(st, "experimental_user") and st.experimental_user
        else "anonymous"
    )


# -------------------------------------------------------
# SESSION STATE VARIABLES
# -------------------------------------------------------
if "selected_candidate" not in st.session_state:
    st.session_state.selected_candidate = None

if "search_results" not in st.session_state:
    st.session_state.search_results = None

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "updated_dm_text" not in st.session_state:
    st.session_state.updated_dm_text = None

if "last_search_query" not in st.session_state:
    st.session_state.last_search_query = ""


# -------------------------------------------------------
# UI HELPERS
# -------------------------------------------------------
def format_chat_message_html(msg: str) -> str:
    """Escape user/assistant content for safe HTML; preserve line breaks."""
    safe = html.escape(str(msg))
    return safe.replace("\n", "<br>")


def render_copy_dm_button(dm_text: str, component_key: str):
    """Client-side clipboard (works in browser; DM text passed as UTF-8 base64)."""
    b64 = base64.b64encode((dm_text or "").encode("utf-8")).decode("ascii")
    safe_id = "cpy_" + hashlib.sha256(component_key.encode()).hexdigest()[:12]
    components.html(
        f"""
<!DOCTYPE html>
<html><body style="margin:0;">
<button type="button" id="{safe_id}" style="width:100%;padding:0.65rem 0.9rem;cursor:pointer;border-radius:12px;border:1px solid rgba(148,163,184,.35);background:#111827;color:#f8fafc;font-weight:700;">
  Copy DM
</button>
<script>
(function() {{
  const b64 = {json.dumps(b64)};
  const btn = document.getElementById("{safe_id}");
  btn.addEventListener("click", async function() {{
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const t = new TextDecoder("utf-8").decode(bytes);
    try {{
      await navigator.clipboard.writeText(t);
      const o = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(function() {{ btn.textContent = o; }}, 2000);
    }} catch (e) {{
      btn.textContent = "Select DM text manually";
      setTimeout(function() {{ btn.textContent = "Copy DM"; }}, 2500);
    }}
  }});
}})();
</script>
</body></html>
        """,
        height=52,
    )


# -------------------------------------------------------
# LAYOUT
# -------------------------------------------------------
left, right = st.columns([1.4, 1.0], gap="large")


# -------------------------------------------------------
# LEFT PANEL — SEARCH
# -------------------------------------------------------
with left:
    with st.container(border=True):
        st.markdown('<div class="ac-section-eyebrow">Search</div>', unsafe_allow_html=True)
        st.markdown('<div class="ac-card-title">Discover candidates</div>', unsafe_allow_html=True)
        st.caption("Describe the people you want to meet. Carter will search, save, embed, and rank them.")

        query = st.text_input(
            "Search query",
            placeholder="e.g., nyc product manager yale fintech"
        )

        if st.button("Search candidates", type="primary", use_container_width=True):
            if not query.strip():
                st.warning("Please enter a query.")
            else:
                safe_query = sanitize_text(query)

                with st.spinner("Searching, indexing, and ranking candidates…"):
                    n_results = get_search_result_limit()
                    profiles = run_exa(safe_query, num_results=n_results)
                    insert_contacts(profiles, user_id=st.session_state.user_id)

                    ingest_lancedb(user_id=st.session_state.user_id)

                    df = search_lancedb(
                        safe_query, user_id=st.session_state.user_id, n=n_results
                    )
                    st.session_state.search_results = df

                    if len(df) > 0:
                        top = df.iloc[0]
                        st.session_state.selected_candidate = candidate_from_lancedb_row(top)
                    else:
                        st.session_state.selected_candidate = None

                    st.session_state.last_search_query = safe_query

                st.success("Search complete.")

    st.write("")

    # DISPLAY RESULTS
    df = st.session_state.search_results

    if df is not None:
        with st.container(border=True):
            result_count = 0 if df.empty else len(df)
            st.markdown('<div class="ac-section-eyebrow">Ranked results</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="ac-card-title">Top candidates <span class="ac-muted">({result_count})</span></div>',
                unsafe_allow_html=True,
            )
            with st.expander("How ranking works", expanded=False):
                st.markdown(
                    """
1. **Exa** returns profiles for your query; we save them as contacts.  
2. Profiles are **embedded** into **LanceDB** (your personal index).  
3. This list is **re-ranked by semantic similarity** (cosine distance) between your **query text** and each profile’s stored text — order can differ from Exa’s.  

**Semantic match %** is a rough visualization (vector distance → score; **lower distance = closer**).  
Run **Search** again after adding many profiles so the index stays in sync.
                    """
                )

            if df.empty:
                st.info("No matches found.")
            else:
                for i, (_, row) in enumerate(df.iterrows()):
                    meta = row["meta"] or {}
                    if not isinstance(meta, dict):
                        try:
                            meta = dict(meta)
                        except Exception:
                            meta = {}

                    name = meta.get("name", "") or "Unknown candidate"
                    headline = meta.get("headline", "")
                    linkedin = meta.get("linkedin", "")

                    with st.container(border=True):
                        title_col, action_col = st.columns([3, 1.15])
                        with title_col:
                            st.markdown(f'<div class="ac-result-rank">#{i + 1}</div>', unsafe_allow_html=True)
                            st.markdown(f"### {name}")
                            st.caption("" if headline in (None, "None") else headline)
                        with action_col:
                            li_url = (linkedin or "").strip()
                            if li_url:
                                st.link_button("Open LinkedIn", li_url, use_container_width=True)
                            else:
                                st.caption("No LinkedIn URL.")

                        dist = row_vector_distance(row)
                        if dist is not None:
                            st.caption(format_match_line(dist))

                        colA, colB = st.columns(2)

                        with colA:
                            if st.button("Add to queue", key=f"queue_row_{i}", use_container_width=True):
                                candidate = {
                                    "name": name,
                                    "headline": headline,
                                    "linkedin": linkedin,
                                }
                                added, err = add_to_queue(
                                    candidate, user_id=st.session_state.user_id
                                )
                                if added:
                                    st.success("Added to queue.")
                                elif err:
                                    st.warning(err)
                                else:
                                    st.info("Already in your queue.")

                        with colB:
                            if st.button("Use for outreach", key=f"pick_row_{i}", use_container_width=True):
                                st.session_state.selected_candidate = candidate_from_lancedb_row(row)
                                st.rerun()

        with st.container(border=True):
            st.markdown('<div class="ac-section-eyebrow">Digest</div>', unsafe_allow_html=True)
            st.markdown('<div class="ac-card-title">Email me this list</div>', unsafe_allow_html=True)
            st.caption(
                "Sends a plain-text copy of the candidates above to **your** inbox "
                "(from the Gmail account configured for this app — not to the candidates)."
            )
            default_inbox = (
                st.session_state.user_id
                if isinstance(st.session_state.user_id, str) and "@" in st.session_state.user_id
                else ""
            )
            digest_email = st.text_input(
                "Your email address",
                value=default_inbox,
                placeholder="you@example.com",
                key="digest_email_inbox",
            )
            if st.button("Send list to my email", key="send_digest", use_container_width=True):
                qtext = (st.session_state.last_search_query or "").strip()
                if not digest_email.strip():
                    st.error("Enter your email address.")
                elif not qtext:
                    st.warning("Run a search first so there is a list to send.")
                else:
                    body = build_search_digest_body(df, qtext)
                    subj = f"Agent Carter — candidates ({qtext[:60]}{'…' if len(qtext) > 60 else ''})"
                    with st.spinner("Sending…"):
                        try:
                            gmail_send_email(
                                to_email=digest_email.strip(),
                                subject=subj,
                                body=body,
                            )
                            st.success("Sent. Check your inbox (and spam).")
                        except Exception as e:
                            st.error(f"Could not send: {e}")


# -------------------------------------------------------
# RIGHT PANEL — OUTREACH + CHAT
# -------------------------------------------------------
with right:
    st.markdown('<div class="ac-section-eyebrow">Outreach</div>', unsafe_allow_html=True)
    st.markdown('<div class="ac-card-title">LinkedIn message studio</div>', unsafe_allow_html=True)
    st.caption("Pick a candidate, generate a tailored draft, then refine it before copying.")

    def parse_outreach(raw):
        if isinstance(raw, dict):
            return raw
        txt = str(raw).strip()
        txt = re.sub(r"^```(?:json)?", "", txt)
        txt = re.sub(r"```$", "", txt)
        try:
            return json.loads(txt)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {
                "reason": [],
                "drafted_dm": "",
                "email_subject": "",
                "email_body": "",
            }

    candidate = st.session_state.selected_candidate

    if not candidate:
        with st.container(border=True):
            st.info("Run a search — results will appear here.")
    else:
        _ckey = candidate.get("linkedin") or candidate.get("name") or ""
        _wk = hashlib.sha256(_ckey.encode("utf-8")).hexdigest()[:16]
        if st.session_state.get("outreach_candidate_key") != _ckey:
            st.session_state.outreach_candidate_key = _ckey
            st.session_state.updated_dm_text = None
            st.session_state.chat_history = []

        with st.container(border=True):
            st.markdown('<div class="ac-section-eyebrow">Selected candidate</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="ac-card-title">{html.escape(str(candidate.get("name", "Unknown")))}</div>',
                unsafe_allow_html=True,
            )
            _hl = candidate.get("headline")
            st.caption("" if _hl in (None, "None") else str(_hl))

            prov = candidate.get("_provenance")
            vd = candidate.get("_vector_distance")
            if prov == "lancedb_search" and vd is not None:
                try:
                    st.caption(format_match_line(float(vd)))
                except (TypeError, ValueError):
                    st.caption("Semantic ranking: distance not available.")
            elif prov == "queue":
                st.caption(
                    "From **queue** — no vector score. Choose someone from **Top Candidates** after Search to see match %."
                )
            else:
                st.caption(
                    "Run **Search** and open a row from **Top Candidates** to see cosine / semantic match scores."
                )

            _li = (candidate.get("linkedin") or "").strip()
            if _li:
                st.link_button("Open LinkedIn", _li, use_container_width=True)
            else:
                st.caption("No LinkedIn URL — open profile from search when available.")

        st.write("")

        st.markdown('<div class="ac-section-eyebrow">Draft</div>', unsafe_allow_html=True)
        st.markdown('<div class="ac-card-title">Personalized outreach</div>', unsafe_allow_html=True)
        st.caption("Uses one cached LLM draft while you stay on this person.")

        draft_cache_key = f"{st.session_state.user_id}::{_ckey}"
        if st.session_state.get("outreach_draft_cache_key") != draft_cache_key:
            st.session_state.cached_outreach_drafts = None
            st.session_state.outreach_draft_cache_key = draft_cache_key

        regen_col, regen_help = st.columns([1, 3])
        with regen_col:
            if st.button("Regenerate draft", key=f"regen_draft_btn_{_wk}"):
                st.session_state.cached_outreach_drafts = None
        with regen_help:
            st.caption("Uses one new LLM call. Cached while you stay on this person.")

        if st.session_state.cached_outreach_drafts is None:
            with st.spinner("Generating drafts…"):
                try:
                    raw = draft_outreach("networking outreach", candidate)
                except Exception as e:
                    st.error(f"Could not generate drafts: {e}")
                    st.stop()
                st.session_state.cached_outreach_drafts = parse_outreach(raw)

        drafts = st.session_state.cached_outreach_drafts

        reasons = drafts.get("reason", [])
        reason_text = "\n".join(f"- {html.escape(str(r))}" for r in reasons)

        dm_text = st.session_state.updated_dm_text or drafts.get("drafted_dm", "")

        with st.container(border=True):
            st.markdown("#### Why this candidate")
            st.markdown(reason_text or "- Carter could not extract reasons from the draft response.")

        with st.container(border=True):
            st.markdown("#### LinkedIn DM")
            st.caption(
                "Paste the DM into LinkedIn yourself — messages must come from your account."
            )
            _dm_widget_key = "dm_ta_" + hashlib.sha256(_ckey.encode("utf-8")).hexdigest()[:16]
            current_dm = st.text_area(
                "DM draft",
                value=dm_text,
                height=180,
                key=_dm_widget_key,
                label_visibility="collapsed",
            )
            cpy1, cpy2 = st.columns(2)
            with cpy1:
                render_copy_dm_button(current_dm or "", "outreach_main")
            with cpy2:
                st.download_button(
                    label="Download DM as .txt",
                    data=current_dm or "",
                    file_name="linkedin_dm.txt",
                    mime="text/plain",
                    key=f"download_dm_txt_{_wk}",
                    use_container_width=True,
                )

        with st.container(border=True):
            st.markdown("#### Refine with Carter")
            st.caption("Ask for tone, length, specificity, or a more natural opener.")

            tone = st.selectbox(
                "Tone",
                [
                    "Professional",
                    "Warm & Friendly",
                    "Founder-to-Founder",
                    "Short & Punchy",
                    "Academic",
                    "Recruiter Tone",
                ],
                key=f"tone_select_{_wk}",
            )

            user_question = st.text_input(
                "Ask Carter to refine your DM",
                placeholder="e.g., make it warmer and shorter",
                key=f"refine_input_{_wk}",
            )

            if st.button("Send to Carter", use_container_width=True, key=f"refine_button_{_wk}"):
                safe_q = sanitize_text(user_question)

                with st.spinner("Thinking…"):
                    try:
                        reply = chat_refine(
                            safe_q,
                            {
                                "name": candidate["name"],
                                "headline": candidate["headline"],
                                "linkedin": candidate["linkedin"],
                                "dm": current_dm or "",
                                "tone": tone,
                            },
                        )
                    except Exception as e:
                        st.error(f"Refinement failed: {e}")
                        st.stop()

                st.session_state.chat_history.append(("user", user_question))
                st.session_state.chat_history.append(("bot", reply))
                st.rerun()

            # CHAT HISTORY
            if st.session_state.chat_history:
                st.markdown("##### Conversation")
                for sender, msg in st.session_state.chat_history:
                    body = format_chat_message_html(msg)
                    bubble_class = "ac-chat-user" if sender == "user" else "ac-chat-bot"
                    st.markdown(
                        f'<div class="ac-chat-bubble {bubble_class}">{body}</div>',
                        unsafe_allow_html=True,
                    )

            # APPLY refinements
            if st.session_state.chat_history and st.session_state.chat_history[-1][0] == "bot":
                last_msg = st.session_state.chat_history[-1][1]
                if st.button("Apply refinement to DM", key=f"apply_dm_{_wk}", use_container_width=True):
                    st.session_state.updated_dm_text = last_msg
                    st.success("DM updated.")
                    st.rerun()


# -------------------------------------------------------
# QUEUE
# -------------------------------------------------------
st.divider()
st.markdown('<div class="ac-section-eyebrow">Queue</div>', unsafe_allow_html=True)
st.markdown('<div class="ac-card-title">People saved for outreach</div>', unsafe_allow_html=True)

with st.expander("Add someone to the queue (without running search)", expanded=False):
    st.caption(
        "Use this if you already know who you want to contact. "
        "LinkedIn profile URL is required."
    )
    manual_name = st.text_input("Name", key="manual_q_name")
    manual_headline = st.text_input("Headline (optional)", key="manual_q_headline")
    manual_li = st.text_input(
        "LinkedIn profile URL",
        placeholder="https://www.linkedin.com/in/...",
        key="manual_q_li",
    )
    if st.button("Add to queue", key="manual_q_submit"):
        url = (manual_li or "").strip()
        if not url:
            st.error("Please enter a LinkedIn profile URL.")
        else:
            cand = {
                "name": (manual_name or "").strip() or "Unknown",
                "headline": (manual_headline or "").strip(),
                "linkedin": url,
            }
            added, err = add_to_queue(cand, user_id=st.session_state.user_id)
            if added:
                st.success("Added to queue.")
                st.rerun()
            elif err:
                st.warning(err)
            else:
                st.info("Already in your queue.")

try:
    rows = fetch_queue(user_id=st.session_state.user_id, limit=10)
except Exception as e:
    st.error(f"Could not load queue: {e}")
    rows = []

if not rows:
    with st.container(border=True):
        st.info("Queue is empty.")
else:
    for r in rows:
        with st.container(border=True):
            st.markdown(f"#### {r.full_name}")
            st.caption("" if r.headline in (None, "None") else r.headline)
            li = r.linkedin_url or ""
            q_link, q_action = st.columns([1, 1])
            with q_link:
                if li.startswith("manual:"):
                    st.caption("No LinkedIn URL on file (internal id).")
                elif (li or "").strip():
                    st.link_button("Open LinkedIn", li.strip(), use_container_width=True)
                else:
                    st.caption("No LinkedIn URL.")

            with q_action:
                if st.button("Use for outreach", key=f"use_q_{r.id}", use_container_width=True):
                    outreach_li = None if (li.startswith("manual:")) else li
                    st.session_state.selected_candidate = {
                        "name": r.full_name,
                        "headline": r.headline or "",
                        "linkedin": outreach_li or "",
                        "_vector_distance": None,
                        "_provenance": "queue",
                    }
                    st.rerun()
