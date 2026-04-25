# logic/db_ops.py

import hashlib
import json
import logging
from datetime import datetime, timezone
import pyarrow as pa
import numpy as np
from lancedb import connect
from sqlalchemy.exc import IntegrityError

from logic.db_models import SessionLocal, Contact, DailyQueue, Outbox
from logic.embeddings import embed, embed_query, get_contacts_table
from logic.llm_ops import draft_outreach

DB_DIR = "agent_carter_lancedb_streamlitcloud"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def today_key():
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------
# INSERT CONTACTS
# ---------------------------------------------------------

def insert_contacts(profiles, user_id: str):
    s = SessionLocal()
    new = 0
    for p in profiles:
        exists = (
            s.query(Contact)
            .filter(
                Contact.linkedin_url == p["linkedin_url"],
                Contact.user_id == user_id
            )
            .first()
        )
        if exists:
            continue

        c = Contact(
            user_id=user_id,
            full_name=p.get("full_name", ""),
            linkedin_url=p.get("linkedin_url", ""),
            headline=p.get("headline", ""),
            profile_summary=p.get("text", "") or p.get("summary", ""),
            first_seen_at=datetime.now(timezone.utc),
        )

        s.add(c)
        new += 1

    s.commit()
    s.close()
    return new

def count_contacts(user_id=None):
    s = SessionLocal()
    if user_id is None:
        n = s.query(Contact).count()          # single-user mode
    else:
        n = s.query(Contact).filter(Contact.user_id == user_id).count()
    s.close()
    return n

# ---------------------------------------------------------
# INGEST LANCEDB (Embedding fresh rebuild)
# ---------------------------------------------------------

def ingest_lancedb(user_id=None):
    logger.info("ingest_lancedb start user_id=%s", user_id)

    s = SessionLocal()
    rows = (
        s.query(Contact).filter(Contact.user_id == user_id).all()
        if user_id else
        s.query(Contact).all()
    )
    s.close()

    logger.debug("sql rows fetched: %d", len(rows))
    if not rows:
        logger.info("no contacts to ingest for user_id=%s", user_id)
        return

    ids = [str(r.id) for r in rows]
    docs = [r.profile_summary or "" for r in rows]
    metas = [
        {
            "name": r.full_name,
            "headline": r.headline,
            "linkedin": r.linkedin_url,
            "profile_summary": r.profile_summary or "",
        }
        for r in rows
    ]

    logger.debug("first meta example: %s", metas[0] if metas else None)

    vecs = embed(docs)
    logger.debug("embeddings shape: %s", getattr(vecs, "shape", None))

    tbl = get_contacts_table(user_id=user_id)
    logger.debug("table name=%s schema=%s", tbl.name, tbl.schema)

    arr = pa.Table.from_arrays(
        [
            pa.array(ids, pa.string()),
            pa.array(docs, pa.string()),
            pa.array(metas, tbl.schema.field("meta").type),
            pa.array(vecs.tolist(), tbl.schema.field("vector").type),
        ],
        schema=tbl.schema
    )

    logger.debug("arrow table rows: %s", arr.num_rows)

    logger.info("ingesting %d contacts into %s", len(rows), tbl.name)
    tbl.add(arr, mode="overwrite")

# ---------------------------------------------------------
# STALE DETECTION
# ---------------------------------------------------------

def is_stale_lancedb(tbl):
    df = tbl.to_pandas()
    if len(df) < 5:
        return True

    # stale case: too many identical embeddings
    if df["vector"].apply(lambda v: tuple(v)).nunique() < len(df) * 0.3:
        return True

    return False


# ---------------------------------------------------------
# SEARCH (multi-user)
# ---------------------------------------------------------

def search_lancedb(query: str, user_id: str, n: int = 10):
    vec = np.array(embed_query(query), dtype=np.float32)
    db = connect(DB_DIR)
    if user_id is None:
        table_name = "contacts"
    else:
        table_name = f"{user_id}_contacts"


    # If missing: build table + index
    if table_name not in db.table_names():
        logger.info("lancedb table %s missing; ingesting", table_name)
        ingest_lancedb(user_id=user_id)

    # After ingest, check again
    if table_name not in db.table_names():
        raise RuntimeError(f"[LanceDB] Table {table_name} still missing after ingest!")

    tbl = db.open_table(table_name)

    if is_stale_lancedb(tbl):
        logger.info("lancedb table %s stale; rebuilding", table_name)
        ingest_lancedb(user_id=user_id)
        tbl = db.open_table(table_name)

    return (
        tbl.search(vec)
           .metric("cosine")
           .limit(n)
           .to_pandas()
    )


# ---------------------------------------------------------
# Convert LanceDB row to candidate
# ---------------------------------------------------------

def _row_to_candidate(df_row):
    meta = df_row.get("meta") or {}
    return {
        "name": meta.get("name", ""),
        "headline": meta.get("headline", ""),
        "linkedin": meta.get("linkedin", ""),
        "summary": meta.get("profile_summary", "") or "",
    }


# ---------------------------------------------------------
# ADD TO QUEUE (multi-user)
# ---------------------------------------------------------

def _queue_linkedin_key(candidate: dict, user_id: str) -> str:
    """
    Stable key for (user, linkedin) uniqueness. Empty/missing LinkedIn uses a
    deterministic placeholder so duplicates are detected without a global UNIQUE
    on bare empty strings (legacy schema issue).
    """
    u = (candidate.get("linkedin") or "").strip()
    if u:
        return u
    name = (candidate.get("name") or "").strip()
    headline = (candidate.get("headline") or "").strip()
    digest = hashlib.sha256(f"{user_id}|{name}|{headline}".encode()).hexdigest()[:32]
    return f"manual:{user_id}:{digest}"


def add_to_queue(candidate: dict, user_id: str, reason: str = "", drafted_dm: str = "", drafted_email: str = ""):
    """
    Returns (added: bool, message: str | None). Message is set on failure or duplicate.
    """
    linkedin_key = _queue_linkedin_key(candidate, user_id)

    s = SessionLocal()
    try:
        exists = (
            s.query(DailyQueue)
            .filter(
                DailyQueue.linkedin_url == linkedin_key,
                DailyQueue.user_id == user_id,
            )
            .first()
        )
        if exists:
            return False, "Already in your queue."

        q = DailyQueue(
            user_id=user_id,
            linkedin_url=linkedin_key,
            full_name=candidate.get("name", "") or "",
            headline=candidate.get("headline", "") or "",
            reason=reason,
            drafted_dm=drafted_dm,
            drafted_email=drafted_email,
            added_at=datetime.now(timezone.utc),
            sent=False,
        )

        s.add(q)
        s.commit()
        return True, None
    except IntegrityError:
        s.rollback()
        return False, "Could not add (duplicate entry or database conflict)."
    except Exception as e:
        s.rollback()
        return False, f"Could not add to queue: {e}"
    finally:
        s.close()


# ---------------------------------------------------------
# FETCH QUEUE (multi-user)
# ---------------------------------------------------------

def fetch_queue(user_id: str, limit: int = 20):
    s = SessionLocal()
    rows = (
        s.query(DailyQueue)
        .filter(
            DailyQueue.user_id == user_id,
            DailyQueue.sent == False,
        )
        .order_by(DailyQueue.added_at.asc())
        .limit(limit)
        .all()
    )
    s.close()
    return rows


# ---------------------------------------------------------
# OUTBOX
# ---------------------------------------------------------

def get_outbox_for_day(day: str, user_id: str):
    s = SessionLocal()
    row = (
        s.query(Outbox)
        .filter(
            Outbox.day == day,
            Outbox.user_id == user_id
        )
        .first()
    )
    s.close()
    return row


def upsert_outbox(day: str, payload: dict, user_id: str, overwrite: bool = False):
    s = SessionLocal()
    row = (
        s.query(Outbox)
        .filter(Outbox.day == day, Outbox.user_id == user_id)
        .first()
    )

    if row and not overwrite:
        s.close()
        return row

    if not row:
        row = Outbox(day=day, user_id=user_id)

    for k, v in payload.items():
        setattr(row, k, v)

    row.created_at = datetime.now(timezone.utc)
    s.add(row)
    s.commit()
    s.refresh(row)
    s.close()

    return row


def mark_outbox_sent(day: str, user_id: str):
    s = SessionLocal()
    row = (
        s.query(Outbox)
        .filter(
            Outbox.day == day,
            Outbox.user_id == user_id
        )
        .first()
    )
    if row:
        row.sent = True
        s.add(row)
        s.commit()
    s.close()


# ---------------------------------------------------------
# PREPARE TODAY'S OUTREACH (multi-user)
# ---------------------------------------------------------

def prepare_today_from_queue(user_id: str, email_to: str, query: str = "", overwrite: bool = False):
    """
    Pull the next queue row, generate a LinkedIn DM draft, and store the day’s
    “outbox” row. Primary content is `drafted_dm`; `email_body` duplicates the DM
    for legacy readers that only read email columns (product is DM-first, not
    cold email to the candidate).
    """
    day = today_key()

    existing = get_outbox_for_day(day, user_id)
    if existing and not overwrite:
        return existing, "already_prepared"

    # Fetch next unsent queue entry for THIS USER
    s = SessionLocal()
    try:
        q = (
            s.query(DailyQueue)
            .filter(
                DailyQueue.user_id == user_id,
                DailyQueue.sent == False,
            )
            .order_by(DailyQueue.added_at.asc())
            .first()
        )

        if not q:
            raise RuntimeError("Queue is empty. Add someone to the queue first.")

        candidate = {
            "name": q.full_name,
            "headline": q.headline,
            "linkedin": q.linkedin_url,
            "summary": "",
        }

        try:
            drafts = draft_outreach(query or "general networking", candidate)
        except Exception as e:
            raise RuntimeError(f"Failed to generate outreach draft: {e}") from e

        dm = (drafts.get("drafted_dm") or "").strip()
        reason_raw = drafts.get("reason") or []
        if isinstance(reason_raw, list):
            reason_stored = json.dumps(reason_raw)
        else:
            reason_stored = str(reason_raw)

        payload = {
            "email_to": email_to,
            "query": query or "",
            "source": "queue",
            "linkedin_url": candidate["linkedin"],
            "full_name": candidate["name"],
            "headline": candidate["headline"],
            "summary": candidate["summary"],
            "match_pct": None,
            "reason": reason_stored,
            "drafted_dm": dm,
            "email_subject": "LinkedIn DM draft (Agent Carter)",
            "email_body": dm,
            "sent": False,
        }

        outbox = upsert_outbox(day, payload, user_id=user_id, overwrite=True)

        q.sent = True
        s.add(q)
        s.commit()

        return outbox, "prepared_from_queue"
    finally:
        s.close()



# ---------------------------------------------------------
# LANCE DB STARTUP CHECK
# ---------------------------------------------------------

def ensure_lancedb_ready():
    db = connect(DB_DIR)

    # If table does not exist → build
    if "contacts" not in db.table_names():
        logger.warning("lancedb contacts table missing; building")
        ingest_lancedb()
        return

    # Table exists but we need to verify it
    tbl = db.open_table("contacts")
    try:
        existing = tbl.count()  # might work in your version
    except Exception:
        logger.warning("lancedb corrupt or unreadable; rebuilding")
        ingest_lancedb()
        return

    s = SessionLocal()
    sql_count = s.query(Contact).count()
    s.close()

    if sql_count != existing:
        logger.warning(
            "lancedb/sql count mismatch (sql=%s lance=%s); rebuilding",
            sql_count,
            existing,
        )
        ingest_lancedb()
    else:
        logger.debug("lancedb row count matches sql (%s)", sql_count)
