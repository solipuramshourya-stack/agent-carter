# logic/db_models.py
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, Boolean, create_engine
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
    linkedin_url = Column(String(500), unique=True)
    full_name = Column(String(255))
    headline = Column(String(700))
    reason = Column(Text)
    drafted_dm = Column(Text)
    drafted_email = Column(Text)
    added_at = Column(DateTime)
    sent = Column(Boolean, default=False)
    user_id = Column(String, index=True)

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
