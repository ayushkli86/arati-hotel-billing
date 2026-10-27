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
        """Busy front-office days (500+ bills) hammer one file, so the
        connection is put in WAL mode (concurrent reads while a bill is
        written), a normal-fsync profile, a 10 s statement timeout and a
        bounded cache so the hotel day never stalls on lock conflicts."""
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-20000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """Request-scoped session.

    A committed unit of work is the route's job, but if anything raises the
    pending transaction is rolled back here so no half-finished hotel write
    (a stay marked checked-in without its invoice, a payment without its
    audit row) can ever linger on the pooled connection.
    """
    session: Session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate_guest_integrity() -> None:
    try:
        with engine.begin() as conn:
            try:
                conn.execute(text("UPDATE guests SET full_name = COALESCE(NULLIF(TRIM(full_name),''), NULLIF(TRIM(name),'')) WHERE full_name IS NULL OR TRIM(full_name)=''"))
            except Exception:
                pass
            try:
                conn.execute(text("UPDATE guests SET name = COALESCE(NULLIF(TRIM(name),''), NULLIF(TRIM(full_name),'')) WHERE name IS NULL OR TRIM(name)=''"))
            except Exception:
                pass
            try:
                conn.execute(text("UPDATE guests SET phone = NULL WHERE phone IS NOT NULL AND TRIM(phone) = ''"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE guests ADD COLUMN full_name VARCHAR(160) DEFAULT ''"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE guests ADD COLUMN updated_at DATETIME"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE stays ADD COLUMN rate_per_night NUMERIC(12,2) DEFAULT 0"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE stays ADD COLUMN notes TEXT DEFAULT ''"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE stays ADD COLUMN updated_at DATETIME"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN updated_at DATETIME"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE invoice_items ADD COLUMN catalog_item_id INTEGER"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE invoice_items ADD COLUMN unit_price NUMERIC(12,2) DEFAULT 0"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE invoice_items ADD COLUMN business_date DATE"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE invoice_items ADD COLUMN added_at DATETIME"))
            except Exception:
                pass
            try:
                conn.execute(text("ALTER TABLE invoice_items ADD COLUMN added_by_id INTEGER"))
            except Exception:
                pass
    except Exception:
        pass
