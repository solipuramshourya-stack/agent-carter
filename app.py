import streamlit as st
import os
import pandas as pd
import json, re
import html

from logic.db_ops import (
    insert_contacts,
    ingest_lancedb,
    search_lancedb,
    add_to_queue,
    fetch_queue,
)
from logic.exa_search import run_exa
from logic.llm_ops import draft_outreach, chat_refine
from logic.email_ops import gmail_send_email


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

if "updated_email_body" not in st.session_state:
    st.session_state.updated_email_body = None

if "updated_dm_text" not in st.session_state:
    st.session_state.updated_dm_text = None


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

                profiles = run_exa(safe_query)
                insert_contacts(profiles, user_id=st.session_state.user_id)

                ingest_lancedb(user_id=st.session_state.user_id)

                df = search_lancedb(safe_query, user_id=st.session_state.user_id, n=10)
                st.session_state.search_results = df

                if len(df) > 0:
                    top = df.iloc[0]
                    meta = top["meta"]

                    st.session_state.selected_candidate = {
                        "name": meta.get("name", ""),
                        "headline": meta.get("headline", ""),
                        "linkedin": meta.get("linkedin", ""),
                    }
                else:
                    st.session_state.selected_candidate = None

            st.success("Search complete!")

    # DISPLAY RESULTS
    df = st.session_state.search_results

    if df is not None:
        st.subheader("Top Candidates")

        if df.empty:
            st.info("No matches found.")
        else:
            for idx, row in df.iterrows():
                meta = row["meta"]

                name = meta.get("name", "")
                headline = meta.get("headline", "")
                linkedin = meta.get("linkedin", "")

                with st.container():
                    st.markdown(f"### {name}")
                    st.caption("" if headline in (None, "None") else headline)
                    st.link_button("Open LinkedIn", linkedin)

                    colA, colB = st.columns(2)

                    with colA:
                        if st.button(f"Add to Queue", key=f"queue_{idx}", use_container_width=True):
                            candidate = {
                                "name": name,
                                "headline": headline,
                                "linkedin": linkedin,
                            }
                            ok = add_to_queue(candidate, user_id=st.session_state.user_id)
                            st.success("Added to Queue!" if ok else "Already in Queue.")

                    with colB:
                        if st.button(f"Select for Outreach", key=f"pick_{idx}", use_container_width=True):
                            st.session_state.selected_candidate = {
                                "name": name,
                                "headline": headline,
                                "linkedin": linkedin,
                            }
                            st.rerun()


# -------------------------------------------------------
# RIGHT PANEL — OUTREACH + CHAT
# -------------------------------------------------------
with right:
    st.header("✉️ Outreach Draft")

    def parse_outreach(raw):
        if isinstance(raw, dict):
            return raw
        txt = str(raw).strip()
        txt = re.sub(r"^```(?:json)?", "", txt)
        txt = re.sub(r"```$", "", txt)
        try:
            return json.loads(txt)
        except:
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
        st.markdown(f"### {candidate['name']}")
        st.caption("" if candidate["headline"] in (None, "None") else candidate["headline"])

        if candidate.get("linkedin"):
            st.link_button("LinkedIn", candidate["linkedin"])

        # Generate outreach
        with st.spinner("Generating drafts…"):
            raw = draft_outreach("networking outreach", candidate)

        drafts = parse_outreach(raw)

        reasons = drafts.get("reason", [])
        reason_text = "\n".join(f"- {r}" for r in reasons)

        dm_text = st.session_state.updated_dm_text or drafts.get("drafted_dm", "")
        email_subject = drafts.get("email_subject", "")
        email_body = st.session_state.updated_email_body or drafts.get("email_body", "")

        st.subheader("Why this candidate")
        st.markdown(reason_text)

        st.subheader("LinkedIn DM")
        st.text_area("DM", value=dm_text, height=160)

        st.subheader("Email")
        st.text_area("Email", value=email_body, height=220)

        # Email sending
        st.subheader("📧 Send Email")
        recipient_email = st.text_input(
            "Recipient Email Address",
            placeholder="person@example.com"
        )

        if st.button("Send Outreach Email", use_container_width=True):
            if not recipient_email:
                st.error("Enter a valid email address.")
            else:
                with st.spinner("Sending via Gmail…"):
                    try:
                        gmail_send_email(
                            to_email=recipient_email,
                            subject=email_subject,
                            body=email_body
                        )
                        st.success("Email sent!")
                    except Exception as e:
                        st.error(f"Error sending email: {e}")

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
            key="tone_select"
        )

        user_question = st.text_input(
            "Ask Carter to refine your DM or Email:",
            placeholder="e.g., rewrite the email in a warmer tone",
            key="refine_input"
        )

        if st.button("Send to Carter", use_container_width=True, key="refine_button"):
            safe_q = sanitize_text(user_question)

            with st.spinner("Thinking…"):
                reply = chat_refine(
                    safe_q,
                    {
                        "name": candidate["name"],
                        "headline": candidate["headline"],
                        "linkedin": candidate["linkedin"],
                        "dm": dm_text,
                        "email_subject": email_subject,
                        "email_body": email_body,
                        "tone": tone,
                    }
                )

            st.session_state.chat_history.append(("user", user_question))
            st.session_state.chat_history.append(("bot", reply))
            st.rerun()

        # CHAT HISTORY
        if st.session_state.chat_history:
            st.markdown("### Conversation")
            for sender, msg in st.session_state.chat_history:
                if sender == "user":
                    st.markdown(
                        f"<div style='padding:10px; border-radius:8px; margin:6px; text-align:right;'>{msg}</div>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<div style='padding:10px; border-radius:8px; margin:6px; text-align:left;'>{msg}</div>",
                        unsafe_allow_html=True
                    )

        # APPLY refinements
        if st.session_state.chat_history and st.session_state.chat_history[-1][0] == "bot":
            last_msg = st.session_state.chat_history[-1][1]
            colA, colB = st.columns(2)

            with colA:
                if st.button("✨ Apply to Email", key="apply_email"):
                    st.session_state.updated_email_body = last_msg
                    st.success("Email updated!")
                    st.rerun()

            with colB:
                if st.button("✨ Apply to DM", key="apply_dm"):
                    st.session_state.updated_dm_text = last_msg
                    st.success("DM updated!")
                    st.rerun()


# -------------------------------------------------------
# QUEUE
# -------------------------------------------------------
st.divider()
st.header("🗂️ Queue")

rows = fetch_queue(user_id=st.session_state.user_id, limit=10)

if not rows:
    st.write("Queue is empty.")
else:
    for r in rows:
        with st.container():
            st.markdown(f"**{r.full_name}**")
            st.caption("" if r.headline in (None, "None") else r.headline)
            st.write(r.linkedin_url)

            if st.button(f"Use for Outreach", key=f"use_{r.id}"):
                st.session_state.selected_candidate = {
                    "name": r.full_name,
                    "headline": r.headline,
                    "linkedin": r.linkedin_url,
                }
                st.rerun()
