"""
Persistence layer.

THEORY: why store the raw text AND the LLM-parsed JSON, not just one?
We keep raw_text (from resume_parser/job_parser) alongside the structured
fields so that if we improve our extraction prompt later, we can re-run
structuring on old data without asking the user to re-upload anything.
This is a cheap insurance policy that's easy to forget until you need it.

SQLite is used here because it's a single file, zero setup, and fine up to
real usage volumes for a single-user tool. Swapping to Postgres later is a
one-line change (just the connection string) because we're going through
SQLAlchemy rather than writing raw sqlite3 calls.
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

DATABASE_URL = "sqlite:///./job_search.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


class Resume(Base):
    __tablename__ = "resumes"
    id = Column(Integer, primary_key=True)
    raw_text = Column(Text)
    parsed_json = Column(Text)          # ParsedResume, stored as JSON text
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    company = Column(String, nullable=True)
    source_url = Column(String, nullable=True)   # the LinkedIn/Indeed page it was captured from
    raw_text = Column(Text)
    parsed_json = Column(Text)
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    resume_id = Column(Integer, ForeignKey("resumes.id"))
    fit_score = Column(Float, nullable=True)
    match_json = Column(Text, nullable=True)    # MatchResult, stored as JSON text
    status = Column(String, default="captured")  # captured -> applied -> interviewing -> rejected/offer
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
