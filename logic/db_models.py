# logic/db_models.py
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, Boolean, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

ENGINE = create_engine("sqlite:///agent_carter.db")
SessionLocal = sessionmaker(bind=ENGINE)
Base = declarative_base()

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    full_name = Column(String)
    linkedin_url = Column(String)
    headline = Column(String)
    profile_summary = Column(String)
    first_seen_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('linkedin_url', 'user_id', name='uq_linkedin_user'),
    )


class DailyQueue(Base):
    __tablename__ = "daily_queue"
    id = Column(Integer, primary_key=True)
    linkedin_url = Column(String(500), nullable=True)
    full_name = Column(String(255))
    headline = Column(String(700))
    reason = Column(Text)
    drafted_dm = Column(Text)
    drafted_email = Column(Text)
    added_at = Column(DateTime)
    sent = Column(Boolean, default=False)
    user_id = Column(String, index=True)

    __table_args__ = (
        UniqueConstraint("linkedin_url", "user_id", name="uq_daily_queue_linkedin_user"),
    )


class Outbox(Base):
    __tablename__ = "outbox"
    id = Column(Integer, primary_key=True)
    day = Column(String(10))
    email_to = Column(String(320))
    query = Column(Text)
    source = Column(String(32))
    linkedin_url = Column(String(500))
    full_name = Column(String(255))
    headline = Column(String(700))
    summary = Column(Text)
    match_pct = Column(Integer)
    reason = Column(Text)
    drafted_dm = Column(Text)
    email_subject = Column(Text)
    email_body = Column(Text)
    created_at = Column(DateTime)
    sent = Column(Boolean, default=False)
    user_id = Column(String, index=True)

Base.metadata.create_all(ENGINE)


def _coerce_sqlite_datetime(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _migrate_daily_queue_v2():
    """
    Rebuild daily_queue if the table was created with a legacy global UNIQUE on
    linkedin_url (breaks multi-user) or missing (linkedin_url, user_id) constraint.
    """
    from sqlalchemy import inspect

    insp = inspect(ENGINE)
    if "daily_queue" not in insp.get_table_names():
        return

    with ENGINE.connect() as conn:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_queue'")
        ).fetchone()
        tbl_sql = row[0] if row else None

    if not tbl_sql:
        return

    normalized = " ".join(tbl_sql.split())
    if "UNIQUE (linkedin_url, user_id)" in normalized or "UNIQUE(linkedin_url,user_id)" in normalized.replace(" ", ""):
        return

    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=ENGINE)
    s = Session()
    try:
        rows = s.execute(text("SELECT * FROM daily_queue")).mappings().all()
    finally:
        s.close()

    parsed = []
    for r in rows:
        added = _coerce_sqlite_datetime(r["added_at"])
        if r["added_at"] is not None and added is None:
            raise RuntimeError(
                "daily_queue migration: could not parse added_at; aborting without dropping table."
            )
        parsed.append(
            {
                "user_id": r["user_id"],
                "linkedin_url": r["linkedin_url"],
                "full_name": r["full_name"],
                "headline": r["headline"],
                "reason": r["reason"],
                "drafted_dm": r["drafted_dm"],
                "drafted_email": r["drafted_email"],
                "added_at": added,
                "sent": bool(r["sent"]),
            }
        )

    with ENGINE.begin() as conn:
        conn.execute(text("DROP TABLE daily_queue"))

    Base.metadata.create_all(ENGINE, tables=[DailyQueue.__table__])

    s = Session()
    try:
        for row in parsed:
            q = DailyQueue(
                user_id=row["user_id"],
                linkedin_url=row["linkedin_url"],
                full_name=row["full_name"],
                headline=row["headline"],
                reason=row["reason"],
                drafted_dm=row["drafted_dm"],
                drafted_email=row["drafted_email"],
                added_at=row["added_at"],
                sent=row["sent"],
            )
            s.add(q)
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


_migrate_daily_queue_v2()
