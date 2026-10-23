"""SQLAlchemy database setup for the independent web application."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


DEFAULT_DB = Path(__file__).resolve().parent / "data" / "arati_web.db"
DATABASE_URL = os.getenv("ARATI_WEB_DATABASE_URL", f"sqlite:///{DEFAULT_DB}")
if DATABASE_URL.startswith("sqlite:"):
    Path(DATABASE_URL.removeprefix("sqlite:///" )).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15}
    if DATABASE_URL.startswith("sqlite:") else {},
    pool_pre_ping=not DATABASE_URL.startswith("sqlite:"),
)
if DATABASE_URL.startswith("sqlite:"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
