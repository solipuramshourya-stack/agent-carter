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
# PAGE CONFIG
# -------------------------------------------------------
st.set_page_config(page_title="Agent Carter", layout="wide")
st.title("🕵️ Agent Carter — Networking Assistant")


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
<button type="button" id="{safe_id}" style="padding:0.4rem 0.9rem;cursor:pointer;border-radius:6px;border:1px solid #ccc;background:#f8f9fa;">
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
    st.header("🔍 Search Candidates")

    query = st.text_input(
        "Enter search query",
        placeholder="e.g., nyc product manager yale fintech"
    )

    if st.button("Search", type="primary", use_container_width=True):
        if not query.strip():
            st.warning("Please enter a query.")
        else:
            safe_query = sanitize_text(query)

            with st.spinner("Searching for candidates"):
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

            st.success("Search complete!")

    # DISPLAY RESULTS
    df = st.session_state.search_results

    if df is not None:
        st.subheader("Top Candidates")
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

                name = meta.get("name", "")
                headline = meta.get("headline", "")
                linkedin = meta.get("linkedin", "")

                with st.container():
                    st.markdown(f"### {name}")
                    st.caption("" if headline in (None, "None") else headline)
                    dist = row_vector_distance(row)
                    if dist is not None:
                        st.caption(format_match_line(dist))

                    li_url = (linkedin or "").strip()
                    if li_url:
                        st.link_button("Open LinkedIn", li_url)
                    else:
                        st.caption("No LinkedIn URL on profile.")

                    colA, colB = st.columns(2)

                    with colA:
                        if st.button(f"Add to Queue", key=f"queue_row_{i}", use_container_width=True):
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
                        if st.button(f"Select for Outreach", key=f"pick_row_{i}", use_container_width=True):
                            st.session_state.selected_candidate = candidate_from_lancedb_row(row)
                            st.rerun()

            st.divider()
            st.subheader("Email me this list")
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
    st.header("💬 LinkedIn outreach")

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
        st.info("Run a search — results will appear here.")
    else:
        _ckey = candidate.get("linkedin") or candidate.get("name") or ""
        _wk = hashlib.sha256(_ckey.encode("utf-8")).hexdigest()[:16]
        if st.session_state.get("outreach_candidate_key") != _ckey:
            st.session_state.outreach_candidate_key = _ckey
            st.session_state.updated_dm_text = None
            st.session_state.chat_history = []

        st.subheader(str(candidate.get("name", "Unknown")))
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
            st.link_button("LinkedIn", _li)
        else:
            st.caption("No LinkedIn URL — open profile from search when available.")

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

        st.subheader("Why this candidate")
        st.markdown(reason_text)

        st.caption(
            "Paste the DM into LinkedIn yourself — messages must come from your account."
        )
        st.subheader("LinkedIn DM")
        _dm_widget_key = "dm_ta_" + hashlib.sha256(_ckey.encode("utf-8")).hexdigest()[:16]
        current_dm = st.text_area(
            "DM draft",
            value=dm_text,
            height=160,
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

        # REFINEMENT CHAT
        st.divider()
        st.subheader("🧠 Refine With Agent Carter")

        tone = st.selectbox(
            "Select tone:",
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
            "Ask Carter to refine your DM:",
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
            st.markdown("### Conversation")
            for sender, msg in st.session_state.chat_history:
                body = format_chat_message_html(msg)
                if sender == "user":
                    st.markdown(
                        f"<div style='padding:10px; border-radius:8px; margin:6px; text-align:right;'>{body}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<div style='padding:10px; border-radius:8px; margin:6px; text-align:left;'>{body}</div>",
                        unsafe_allow_html=True,
                    )

        # APPLY refinements
        if st.session_state.chat_history and st.session_state.chat_history[-1][0] == "bot":
            last_msg = st.session_state.chat_history[-1][1]
            if st.button("✨ Apply refinement to DM", key=f"apply_dm_{_wk}"):
                st.session_state.updated_dm_text = last_msg
                st.success("DM updated!")
                st.rerun()


# -------------------------------------------------------
# QUEUE
# -------------------------------------------------------
st.divider()
st.header("🗂️ Queue")

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
    st.write("Queue is empty.")
else:
    for r in rows:
        with st.container():
            st.markdown(f"**{r.full_name}**")
            st.caption("" if r.headline in (None, "None") else r.headline)
            li = r.linkedin_url or ""
            if li.startswith("manual:"):
                st.caption("No LinkedIn URL on file (internal id).")
            elif (li or "").strip():
                st.link_button("Open LinkedIn", li.strip())
            else:
                st.caption("No LinkedIn URL.")

            if st.button("Use for Outreach", key=f"use_q_{r.id}"):
                outreach_li = None if (li.startswith("manual:")) else li
                st.session_state.selected_candidate = {
                    "name": r.full_name,
                    "headline": r.headline or "",
                    "linkedin": outreach_li or "",
                    "_vector_distance": None,
                    "_provenance": "queue",
                }
                st.rerun()
