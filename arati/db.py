"""SQLite storage for the Arati Hotel billing app."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
# ARATI_DB lets a deployment keep the database outside the release folder.
DB_PATH = Path(os.environ.get("ARATI_DB") or (APP_DIR / "arati.db"))

PBKDF2_ROUNDS = 120_000
ROLES = ("admin", "staff")
CATEGORIES = ("room", "food", "service", "other")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    pan           TEXT NOT NULL DEFAULT '',
    customer_type TEXT NOT NULL DEFAULT 'individual',
    created_at    TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_customers_name ON customers (name);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers (phone);

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin','staff')),
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    item_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL CHECK (category IN ('room','food','service','other')),
    code       TEXT,
    price      REAL NOT NULL DEFAULT 0,
    unit       TEXT NOT NULL DEFAULT 'pcs',
    taxable    INTEGER NOT NULL DEFAULT 1,
    active     INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (name, category)
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no    TEXT NOT NULL UNIQUE,
    item_id    INTEGER NOT NULL REFERENCES items(item_id),
    floor      TEXT,
    active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bills (
    bill_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_no              TEXT NOT NULL UNIQUE,
    created_at           TEXT NOT NULL,
    bill_date            TEXT NOT NULL,
    guest_name           TEXT NOT NULL DEFAULT '',
    guest_phone          TEXT NOT NULL DEFAULT '',
    guest_address        TEXT NOT NULL DEFAULT '',
    guest_pan            TEXT NOT NULL DEFAULT '',
    room_no              TEXT NOT NULL DEFAULT '',
    check_in             TEXT,
    check_out            TEXT,
    nights               INTEGER NOT NULL DEFAULT 0,
    subtotal             REAL NOT NULL DEFAULT 0,
    discount             REAL NOT NULL DEFAULT 0,
    item_discount        REAL NOT NULL DEFAULT 0,
    net_subtotal         REAL NOT NULL DEFAULT 0,
    taxable_net          REAL NOT NULL DEFAULT 0,
    service_charge_rate  REAL NOT NULL DEFAULT 0,
    service_charge       REAL NOT NULL DEFAULT 0,
    vat_rate             REAL NOT NULL DEFAULT 0,
    vat                  REAL NOT NULL DEFAULT 0,
    total                REAL NOT NULL DEFAULT 0,
    paid                 REAL NOT NULL DEFAULT 0,
    balance              REAL NOT NULL DEFAULT 0,
    payment_method       TEXT NOT NULL DEFAULT 'Cash',
    status               TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('issued','void')),
    is_draft             INTEGER NOT NULL DEFAULT 0,
    bill_type            TEXT NOT NULL DEFAULT 'tax',
    customer_type        TEXT NOT NULL DEFAULT 'individual',
    payment_terms        TEXT NOT NULL DEFAULT '',
    prepared_by          TEXT NOT NULL DEFAULT '',
    received_by          TEXT NOT NULL DEFAULT '',
    customer_id          INTEGER REFERENCES customers(customer_id),
    notes                TEXT NOT NULL DEFAULT '',
    user_id              INTEGER REFERENCES users(user_id),
    language             TEXT NOT NULL DEFAULT 'en',
    copy                 TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bill_items (
    line_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id     INTEGER NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    item_id     INTEGER,
    category    TEXT NOT NULL DEFAULT 'food',
    description TEXT NOT NULL,
    code        TEXT NOT NULL DEFAULT '',
    unit        TEXT NOT NULL DEFAULT 'pcs',
    qty         REAL NOT NULL DEFAULT 1,
    unit_price  REAL NOT NULL DEFAULT 0,
    line_total  REAL NOT NULL DEFAULT 0,
    taxable     INTEGER NOT NULL DEFAULT 1,
    discount    REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_bills_date ON bills (bill_date);
CREATE INDEX IF NOT EXISTS idx_bills_status ON bills (status);
CREATE INDEX IF NOT EXISTS idx_bill_items_bill ON bill_items (bill_id);

-- Cash actually received against invoices. A payment is dated by the moment
-- the money changed hands, which is not necessarily the invoice date, so a
-- payment received today for an invoice raised last month shows up in
-- today's collections and not in today's sales.
CREATE TABLE IF NOT EXISTS payments (
    payment_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id       INTEGER REFERENCES bills(bill_id),
    bill_no       TEXT NOT NULL,
    method        TEXT NOT NULL DEFAULT 'Cash',
    amount        REAL NOT NULL DEFAULT 0,
    paid_at       TEXT NOT NULL,
    business_date TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    user_id       INTEGER REFERENCES users(user_id),
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payments_business_date ON payments (business_date);
CREATE INDEX IF NOT EXISTS idx_payments_bill ON payments (bill_no);

-- Money returned to a guest, and authorised corrections to a bill balance.
-- Stored separately from payments so a reversal is never mistaken for cash in.
CREATE TABLE IF NOT EXISTS refunds (
    refund_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id       INTEGER REFERENCES bills(bill_id),
    bill_no       TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'refund'
                  CHECK (kind IN ('refund','adjustment')),
    method        TEXT NOT NULL DEFAULT 'Cash',
    amount        REAL NOT NULL DEFAULT 0,
    reason        TEXT NOT NULL DEFAULT '',
    refunded_at   TEXT NOT NULL,
    business_date TEXT NOT NULL,
    user_id       INTEGER REFERENCES users(user_id),
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_refunds_business_date ON refunds (business_date);
CREATE INDEX IF NOT EXISTS idx_refunds_bill ON refunds (bill_no);

-- A booking for a room. Reservation status lives here, never on the room.
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no        TEXT NOT NULL,
    guest_name     TEXT NOT NULL,
    guest_phone    TEXT NOT NULL DEFAULT '',
    guest_address  TEXT NOT NULL DEFAULT '',
    guest_pan      TEXT NOT NULL DEFAULT '',
    check_in       TEXT NOT NULL,
    check_out      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'confirmed'
                   CHECK (status IN ('confirmed','checked_in','checked_out','cancelled','no_show')),
    nightly_rate   REAL NOT NULL DEFAULT 0,
    deposit        REAL NOT NULL DEFAULT 0,
    source         TEXT NOT NULL DEFAULT 'front desk',
    notes          TEXT NOT NULL DEFAULT '',
    cancel_reason  TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    user_id        INTEGER REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_reservations_room ON reservations (room_no, status);
CREATE INDEX IF NOT EXISTS idx_reservations_dates ON reservations (check_in, check_out);

-- A guest actually in the room. A stay owns one folio invoice, so room
-- charges live in the ordinary bill_items table and are settled by the
-- ordinary payments table.
CREATE TABLE IF NOT EXISTS stays (
    stay_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id    INTEGER REFERENCES reservations(reservation_id),
    room_no           TEXT NOT NULL,
    bill_no           TEXT NOT NULL DEFAULT '',
    guest_name        TEXT NOT NULL,
    guest_phone       TEXT NOT NULL DEFAULT '',
    guest_address     TEXT NOT NULL DEFAULT '',
    guest_pan         TEXT NOT NULL DEFAULT '',
    check_in          TEXT NOT NULL,
    expected_checkout TEXT NOT NULL DEFAULT '',
    check_out         TEXT,
    nights            INTEGER NOT NULL DEFAULT 1,
    nightly_rate      REAL NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active','checked_out','cancelled')),
    created_at        TEXT NOT NULL,
    user_id           INTEGER REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_stays_room ON stays (room_no, status);

-- Extra services posted to a stay before checkout (food, laundry, extra
-- bed). The folio itself is billed through the ordinary bills/bill_items
-- tables, so this table records the stay-level detail without creating a
-- second financial ledger.
CREATE TABLE IF NOT EXISTS room_charges (
    charge_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    stay_id     INTEGER NOT NULL REFERENCES stays(stay_id),
    room_no     TEXT NOT NULL DEFAULT '',
    bill_no     TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'service',
    qty         REAL NOT NULL DEFAULT 1,
    unit_price  REAL NOT NULL DEFAULT 0,
    amount      REAL NOT NULL DEFAULT 0,
    charge_date TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    user_id     INTEGER REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_room_charges_stay ON room_charges (stay_id);

-- One row per completed business day. A regenerated report keeps the old row
-- and bumps the version, so the audit trail survives.
CREATE TABLE IF NOT EXISTS daily_reports (
    report_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    business_date TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'generated'
                  CHECK (status IN ('generated','failed','superseded')),
    file_path     TEXT NOT NULL DEFAULT '',
    generated_at  TEXT NOT NULL,
    generated_by  TEXT NOT NULL DEFAULT 'scheduler',
    error         TEXT NOT NULL DEFAULT '',
    totals_json   TEXT NOT NULL DEFAULT '{}',
    superseded_by INTEGER REFERENCES daily_reports(report_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_reports_version
    ON daily_reports (business_date, version);

-- Every attempt at a scheduled job, successful or not.
CREATE TABLE IF NOT EXISTS scheduler_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name      TEXT NOT NULL,
    business_date TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','ok','failed','skipped')),
    message       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_scheduler_runs_job ON scheduler_runs (job_name, started_at);

-- Who changed what, and when. Financial adjustments and report
-- regenerations always leave a line here.
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id    INTEGER,
    username   TEXT NOT NULL DEFAULT '',
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL DEFAULT '',
    entity_id  TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at);
"""

DEFAULT_SETTINGS = [
    ("hotel_name", "Arati Hotel"),
    ("hotel_address1", "Khandbari-01, Sankhuwasabha"),
    ("hotel_address2", "Koshi Province, Nepal"),
    ("hotel_phone", "+977-29-560117"),
    ("hotel_email", "aratihotelkhandbari@gmail.com"),
    ("hotel_pan", ""),
    ("hotel_website", "aratihotel.com.np"),
    ("bill_prefix", "ARH"),
    ("vat_rate", "13"),
    ("service_charge_rate", "10"),
    ("thermal_device", ""),
    ("footer_note", "Thank you for staying with us."),
    ("invoice_copy", "Customer Copy"),
    ("payment_terms", "Payment due on presentation."),
    ("return_policy", ""),
    ("logo_path", ""),
    ("date_format", "DD/MM/YYYY"),
    ("hotel_name_ne", ""),
    ("hotel_vat", ""),
    ("invoice_language", "en"),
    ("invoice_copy_office", "Office Copy"),
    ("currency_symbol", "रु."),
    # --- printer configuration (Phase 2) -----------------------------------
    ("printer_paper_size", "A4"),
    ("printer_thermal_width", "80"),
    ("printer_margins", "normal"),
    ("printer_show_logo", "1"),
    ("printer_header", "1"),
    ("printer_footer", "1"),
    ("printer_contact_details", "1"),
    ("printer_tax_details", "1"),
    ("printer_copies", "1"),
    ("printer_default_workflow", "preview"),
    ("printer_default_device", ""),
    # --- hotel / reporting configuration -----------------------------------
    ("business_timezone", "Asia/Kathmandu"),
    ("auto_close_enabled", "1"),
    ("close_time", "00:05"),
    ("payment_methods", "Cash,Card,Bank Transfer,Digital Wallet,Other"),
    ("room_numbers", ""),
    ("cash_opening_balance", "0"),
    ("backup_dir", ""),
    ("backup_hour", "02:00"),
    ("backup_retention_days", "30"),
]


# --------------------------------------------------------------------------- #
# connection
# --------------------------------------------------------------------------- #
def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open the database with durability settings suitable for a live till."""
    path = Path(path)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    # Waits must be configured before any locking pragma.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        # Another instance holds the database in rollback-journal mode; writing
        # still works, so never block startup on the journal switch.
        pass
    conn.execute("PRAGMA synchronous = NORMAL")
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            try:
                os.chmod(candidate, 0o600)
            except OSError:
                pass
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# Columns added after the first release. Kept additive so existing bills survive.
BILL_MIGRATIONS = [
    ("taxable_net", "REAL NOT NULL DEFAULT 0"),
    ("bill_type", "TEXT NOT NULL DEFAULT 'tax'"),
    ("customer_type", "TEXT NOT NULL DEFAULT 'individual'"),
    ("payment_terms", "TEXT NOT NULL DEFAULT ''"),
    ("prepared_by", "TEXT NOT NULL DEFAULT ''"),
    ("received_by", "TEXT NOT NULL DEFAULT ''"),
    ("customer_id", "INTEGER"),
    ("is_draft", "INTEGER NOT NULL DEFAULT 0"),
    ("language", "TEXT NOT NULL DEFAULT 'en'"),
    ("item_discount", "REAL NOT NULL DEFAULT 0"),
    ("copy", "TEXT NOT NULL DEFAULT ''"),
]
ITEM_MIGRATIONS = [
    ("code", "TEXT NOT NULL DEFAULT ''"),
    ("discount", "REAL NOT NULL DEFAULT 0"),
]
ROOM_MIGRATIONS = [
    ("nightly_rate", "REAL NOT NULL DEFAULT 0"),
    ("housekeeping", "TEXT NOT NULL DEFAULT 'clean'"),
]
BILL_ITEM_MIGRATIONS = [
    ("stay_id", "INTEGER"),
]


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> None:
    """Add missing columns to older databases without touching existing rows."""
    for table, columns in (
        ("bills", BILL_MIGRATIONS),
        ("bill_items", ITEM_MIGRATIONS),
        ("bill_items", BILL_ITEM_MIGRATIONS),
        ("rooms", ROOM_MIGRATIONS),
    ):
        existing = _column_names(conn, table)
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    _backfill_taxable_net(conn)
    conn.commit()


def _backfill_taxable_net(conn: sqlite3.Connection) -> None:
    """Recover the taxable base for tax bills saved before it was stored."""
    rows = conn.execute(
        "SELECT bill_id, subtotal, net_subtotal FROM bills "
        "WHERE bill_type = 'tax' AND vat > 0 AND COALESCE(taxable_net, 0) = 0 AND subtotal > 0"
    ).fetchall()
    for row in rows:
        taxable = conn.execute(
            "SELECT COALESCE(SUM(line_total), 0) FROM bill_items "
            "WHERE bill_id = ? AND taxable = 1",
            (row["bill_id"],),
        ).fetchone()[0]
        if taxable:
            conn.execute(
                "UPDATE bills SET taxable_net = ? WHERE bill_id = ?",
                (round(taxable * row["net_subtotal"] / row["subtotal"], 2), row["bill_id"]),
            )


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_audit(
    conn: sqlite3.Connection,
    action: str,
    entity: str = "",
    entity_id: str = "",
    detail: str = "",
    user_id: int | None = None,
    username: str = "",
) -> None:
    """Append one line to the audit log.

    Financial adjustments, report regenerations and permission-sensitive
    changes all leave a trail here. Writes never raise: losing an audit line
    must not roll back the operation it describes.
    """
    try:
        conn.execute(
            "INSERT INTO audit_log (created_at, user_id, username, action, entity, "
            "entity_id, detail) VALUES (?,?,?,?,?,?,?)",
            (now(), user_id, username, action, entity, str(entity_id), detail),
        )
        conn.commit()
    except sqlite3.Error:
        pass


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    values = {key: default for key, default in DEFAULT_SETTINGS}
    for row in conn.execute("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"]
    return values


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def save_settings(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    for key, value in values.items():
        set_setting(conn, key, value)
    conn.commit()


# --------------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------------- #
def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(rounds)
    ).hex()
    return secrets.compare_digest(candidate, digest)


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    full_name: str = "",
    role: str = "staff",
) -> int:
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, full_name, role, active, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (username.strip().lower(), hash_password(password), full_name.strip(), role, now()),
    )
    return int(cur.lastrowid)


def authenticate(
    conn: sqlite3.Connection, username: str, password: str
) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND active = 1",
        (username.strip().lower(),),
    ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return row
    return None


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT user_id, username, full_name, role, active, created_at "
            "FROM users ORDER BY role, username"
        )
    )


def update_user(
    conn: sqlite3.Connection,
    user_id: int,
    full_name: str,
    role: str,
    active: bool,
    password: str | None = None,
) -> None:
    conn.execute(
        "UPDATE users SET full_name = ?, role = ?, active = ? WHERE user_id = ?",
        (full_name.strip(), role, int(active), user_id),
    )
    if password:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (hash_password(password), user_id),
        )
    conn.commit()


def delete_user(conn: sqlite3.Connection, user_id: int) -> None:
    if conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND user_id <> ?",
        (user_id,),
    ).fetchone()[0] == 0:
        raise ValueError("At least one active admin must remain")
    conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #
def list_items(
    conn: sqlite3.Connection, category: str | None = None, search: str = ""
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM items WHERE active = 1"
    params: list = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if search:
        sql += " AND (name LIKE ? OR code LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY category, sort_order, name"
    return list(conn.execute(sql, params))


def get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()


def upsert_item(
    conn: sqlite3.Connection,
    name: str,
    category: str,
    price: float,
    unit: str = "pcs",
    taxable: bool = True,
    code: str = "",
    sort_order: int = 0,
    item_id: int | None = None,
) -> int:
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    if not name.strip():
        raise ValueError("Item name is required")
    if item_id:
        conn.execute(
            "UPDATE items SET name = ?, category = ?, price = ?, unit = ?, "
            "taxable = ?, code = ?, sort_order = ? WHERE item_id = ?",
            (
                name.strip(),
                category,
                float(price),
                unit or "pcs",
                int(taxable),
                code.strip(),
                int(sort_order),
                item_id,
            ),
        )
        conn.commit()
        return item_id
    cur = conn.execute(
        "INSERT INTO items (name, category, price, unit, taxable, code, sort_order, active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        (name.strip(), category, float(price), unit or "pcs", int(taxable), code.strip(), int(sort_order)),
    )
    conn.commit()
    return int(cur.lastrowid)


def deactivate_item(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("UPDATE items SET active = 0 WHERE item_id = ?", (item_id,))
    conn.commit()


def list_rooms(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT r.*, i.name AS room_type, i.price AS rate, i.item_id "
            "FROM rooms r JOIN items i ON i.item_id = r.item_id "
            "WHERE r.active = 1 AND i.active = 1 ORDER BY r.room_no"
        )
    )


def get_room(conn: sqlite3.Connection, room_no: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT r.*, i.name AS room_type, i.price AS rate "
        "FROM rooms r JOIN items i ON i.item_id = r.item_id "
        "WHERE r.room_no = ? AND r.active = 1 AND i.active = 1",
        (room_no,),
    ).fetchone()


def save_room(
    conn: sqlite3.Connection,
    room_no: str,
    item_id: int,
    floor: str = "",
    active: bool = True,
) -> int:
    existing = conn.execute(
        "SELECT room_id FROM rooms WHERE room_no = ?", (room_no.strip(),)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE rooms SET item_id = ?, floor = ?, active = ? WHERE room_id = ?",
            (item_id, floor.strip(), int(active), existing["room_id"]),
        )
        conn.commit()
        return int(existing["room_id"])
    cur = conn.execute(
        "INSERT INTO rooms (room_no, item_id, floor, active) VALUES (?, ?, ?, ?)",
        (room_no.strip(), item_id, floor.strip(), int(active)),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_room(conn: sqlite3.Connection, room_id: int) -> None:
    conn.execute("UPDATE rooms SET active = 0 WHERE room_id = ?", (room_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
# billing
# --------------------------------------------------------------------------- #
def next_bill_no(conn: sqlite3.Connection, prefix: str) -> str:
    row = conn.execute(
        "SELECT bill_no FROM bills WHERE bill_no LIKE ? ORDER BY bill_id DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    if not row:
        return f"{prefix}0000001"
    tail = "".join(ch for ch in row["bill_no"][len(prefix):] if ch.isdigit())
    return f"{prefix}{int(tail or 0) + 1:07d}"


def create_bill(conn: sqlite3.Connection, **kwargs) -> str:
    """Persist a bill, retrying if a concurrent writer took the same number."""
    for attempt in range(5):
        try:
            return _create_bill_once(conn, **kwargs)
        except sqlite3.IntegrityError as exc:
            if "bill_no" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError("unreachable")


def _create_bill_once(
    conn: sqlite3.Connection,
    *,
    prefix: str,
    guest: dict,
    lines: list[dict],
    totals: dict,
    payment_method: str,
    user_id: int | None,
    status: str = "issued",
    bill_date: str | None = None,
    notes: str = "",
    bill_type: str = "tax",
    customer_type: str = "individual",
    payment_terms: str = "",
    prepared_by: str = "",
    received_by: str = "",
    customer_id: int | None = None,
    is_draft: int = 0,
    language: str = "en",
    copy: str = "",
) -> str:
    """Persist a bill and its lines in one transaction. Returns the bill number."""
    with conn:
        bill_no = next_bill_no(conn, prefix)
        cur = conn.execute(
            """INSERT INTO bills (bill_no, created_at, bill_date, guest_name, guest_phone,
                    guest_address, guest_pan, room_no, check_in, check_out, nights,
                    subtotal, discount, item_discount, net_subtotal, taxable_net,
                    service_charge_rate, service_charge, vat_rate, vat, total, paid, balance,
                    payment_method, status, is_draft, bill_type, customer_type, payment_terms,
                    prepared_by, received_by, customer_id, notes, user_id, language, copy)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                bill_no,
                now(),
                bill_date or date.today().isoformat(),
                guest.get("name", ""),
                guest.get("phone", ""),
                guest.get("address", ""),
                guest.get("pan", ""),
                guest.get("room_no", ""),
                guest.get("check_in") or None,
                guest.get("check_out") or None,
                int(guest.get("nights") or 0),
                totals["subtotal"],
                totals["discount"],
                totals.get("item_discount", 0),
                totals["net_subtotal"],
                totals["taxable_net"],
                totals["service_charge_rate"],
                totals["service_charge"],
                totals["vat_rate"],
                totals["vat"],
                totals["total"],
                totals["paid"],
                totals["balance"],
                payment_method,
                status,
                int(is_draft),
                bill_type,
                customer_type,
                payment_terms,
                prepared_by,
                received_by,
                customer_id,
                notes,
                user_id,
                language,
                copy,
            ),
        )
        bill_id = int(cur.lastrowid)
        for line in lines:
            line_total = line.get("line_total")
            if line_total is None:
                line_total = round(float(line.get("qty") or 0) * float(line.get("unit_price") or 0), 2)
            conn.execute(
                """INSERT INTO bill_items (bill_id, item_id, category, description, code,
                        unit, qty, unit_price, line_total, taxable, discount)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    bill_id,
                    line.get("item_id"),
                    line.get("category", "food"),
                    line["description"],
                    line.get("code", ""),
                    line.get("unit", "pcs"),
                    line["qty"],
                    line["unit_price"],
                    line_total,
                    int(line.get("taxable", True)),
                    line.get("discount", 0),
                ),
            )
    # The opening payment is written to the cash ledger so the daily report
    # counts the money as collected, not just as billed.
    if not is_draft and float(totals.get("paid") or 0) > 0:
        _record_opening_payment(
            conn, bill_no, bill_id, float(totals["paid"]), payment_method, bill_date
        )
    return bill_no


def _record_opening_payment(
    conn: sqlite3.Connection,
    bill_no: str,
    bill_id: int,
    amount: float,
    payment_method: str,
    bill_date: str | None,
) -> None:
    """Write the payment taken at the time of sale into the cash ledger."""
    from . import business_time as bt

    business_date = bill_date or bt.today().isoformat()
    stamp = f"{business_date} {bt.now().strftime('%H:%M:%S')}"
    conn.execute(
        "INSERT INTO payments (bill_id, bill_no, method, amount, paid_at, "
        "business_date, note, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            bill_id,
            bill_no,
            payment_method or "Cash",
            round(amount, 2),
            stamp,
            business_date,
            "Payment taken at the time of sale",
            None,
            bt.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def get_bill(conn: sqlite3.Connection, bill_no: str) -> tuple[dict, list[sqlite3.Row]] | None:
    row = conn.execute("SELECT * FROM bills WHERE bill_no = ?", (bill_no,)).fetchone()
    if not row:
        return None
    lines = list(
        conn.execute(
            "SELECT * FROM bill_items WHERE bill_id = ? ORDER BY line_id",
            (row["bill_id"],),
        )
    )
    return dict(row), lines


def list_bills(
    conn: sqlite3.Connection, search: str = "", limit: int = 300
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM bills"
    params: list = []
    if search:
        sql += " WHERE bill_no LIKE ? OR guest_name LIKE ? OR guest_phone LIKE ? OR room_no LIKE ?"
        params = [f"%{search}%"] * 4
    sql += " ORDER BY bill_id DESC LIMIT ?"
    params.append(limit)
    return list(conn.execute(sql, params))


def void_bill(conn: sqlite3.Connection, bill_no: str) -> None:
    conn.execute(
        "UPDATE bills SET status = 'void' WHERE bill_no = ? AND is_draft = 0", (bill_no,)
    )
    conn.commit()


def update_draft(
    conn: sqlite3.Connection,
    bill_no: str,
    *,
    guest: dict,
    lines: list[dict],
    totals: dict,
    payment_method: str,
    bill_type: str = "tax",
    customer_type: str = "individual",
    payment_terms: str = "",
    prepared_by: str = "",
    received_by: str = "",
    customer_id: int | None = None,
    notes: str = "",
    language: str = "en",
    copy: str = "",
) -> bool:
    """Replace a draft's contents. Returns False if the bill is not a draft."""
    row = conn.execute(
        "SELECT bill_id, is_draft FROM bills WHERE bill_no = ?", (bill_no,)
    ).fetchone()
    if not row or not row["is_draft"]:
        return False

    with conn:
        conn.execute(
            """UPDATE bills SET guest_name = ?, guest_phone = ?, guest_address = ?,
                    guest_pan = ?, room_no = ?, check_in = ?, check_out = ?, nights = ?,
                    subtotal = ?, discount = ?, item_discount = ?, net_subtotal = ?,
                    taxable_net = ?, service_charge_rate = ?, service_charge = ?,
                    vat_rate = ?, vat = ?, total = ?, paid = ?, balance = ?,
                    payment_method = ?, bill_type = ?, customer_type = ?, payment_terms = ?,
                    prepared_by = ?, received_by = ?, customer_id = ?, notes = ?,
                    language = ?, copy = ?
               WHERE bill_id = ?""",
            (
                guest.get("name", ""),
                guest.get("phone", ""),
                guest.get("address", ""),
                guest.get("pan", ""),
                guest.get("room_no", ""),
                guest.get("check_in") or None,
                guest.get("check_out") or None,
                int(guest.get("nights") or 0),
                totals["subtotal"],
                totals["discount"],
                totals.get("item_discount", 0),
                totals["net_subtotal"],
                totals["taxable_net"],
                totals["service_charge_rate"],
                totals["service_charge"],
                totals["vat_rate"],
                totals["vat"],
                totals["total"],
                totals["paid"],
                totals["balance"],
                payment_method,
                bill_type,
                customer_type,
                payment_terms,
                prepared_by,
                received_by,
                customer_id,
                notes,
                language,
                copy,
                row["bill_id"],
            ),
        )
        conn.execute("DELETE FROM bill_items WHERE bill_id = ?", (row["bill_id"],))
        for line in lines:
            conn.execute(
                """INSERT INTO bill_items (bill_id, item_id, category, description, code,
                        unit, qty, unit_price, line_total, taxable, discount)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["bill_id"],
                    line.get("item_id"),
                    line.get("category", "food"),
                    line["description"],
                    line.get("code", ""),
                    line.get("unit", "pcs"),
                    line["qty"],
                    line["unit_price"],
                    line["line_total"],
                    int(line.get("taxable", True)),
                    line.get("discount", 0),
                ),
            )
    return True


def finalize_draft(conn: sqlite3.Connection, bill_no: str) -> bool:
    """Mark a draft as issued. Returns False if it was not a draft."""
    cur = conn.execute(
        "UPDATE bills SET is_draft = 0 WHERE bill_no = ? AND is_draft = 1", (bill_no,)
    )
    conn.commit()
    return cur.rowcount > 0


def delete_draft(conn: sqlite3.Connection, bill_no: str) -> bool:
    """Delete a draft and its lines. Issued bills can never be deleted."""
    row = conn.execute(
        "SELECT bill_id FROM bills WHERE bill_no = ? AND is_draft = 1", (bill_no,)
    ).fetchone()
    if not row:
        return False
    with conn:
        conn.execute("DELETE FROM bill_items WHERE bill_id = ?", (row["bill_id"],))
        conn.execute("DELETE FROM bills WHERE bill_id = ?", (row["bill_id"],))
    return True


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
def sales_summary(conn: sqlite3.Connection, start: str, end: str) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS bills,
                  COALESCE(SUM(subtotal), 0) AS subtotal,
                  COALESCE(SUM(discount), 0) AS discount,
                  COALESCE(SUM(service_charge), 0) AS service_charge,
                  COALESCE(SUM(vat), 0) AS vat,
                  COALESCE(SUM(total), 0) AS total,
                  COALESCE(SUM(paid), 0) AS paid,
                  COALESCE(SUM(balance), 0) AS balance
           FROM bills WHERE status = 'issued' AND is_draft = 0 AND bill_date BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    by_method = list(
        conn.execute(
            """SELECT payment_method, COUNT(*) AS bills, COALESCE(SUM(total),0) AS total
               FROM bills WHERE status = 'issued' AND is_draft = 0
                 AND bill_date BETWEEN ? AND ?
               GROUP BY payment_method ORDER BY total DESC""",
            (start, end),
        )
    )
    by_category = list(
        conn.execute(
            """SELECT bi.category, COALESCE(SUM(bi.line_total),0) AS total
               FROM bill_items bi JOIN bills b ON b.bill_id = bi.bill_id
               WHERE b.status = 'issued' AND b.is_draft = 0
                 AND b.bill_date BETWEEN ? AND ?
               GROUP BY bi.category ORDER BY total DESC""",
            (start, end),
        )
    )
    daily = list(
        conn.execute(
            """SELECT bill_date, COUNT(*) AS bills, COALESCE(SUM(total),0) AS total
               FROM bills WHERE status = 'issued' AND is_draft = 0
                 AND bill_date BETWEEN ? AND ?
               GROUP BY bill_date ORDER BY bill_date""",
            (start, end),
        )
    )
    return {
        "totals": dict(row),
        "by_method": [dict(r) for r in by_method],
        "by_category": [dict(r) for r in by_category],
        "daily": [dict(r) for r in daily],
    }


def unpaid_bills(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM bills WHERE status = 'issued' AND is_draft = 0 AND balance > 0 "
            "ORDER BY bill_date DESC, bill_id DESC"
        )
    )


# --------------------------------------------------------------------------- #
# bootstrap
# --------------------------------------------------------------------------- #
def bootstrap(conn: sqlite3.Connection) -> None:
    """Create schema, default settings, admin user, and seed catalog once."""
    init_db(conn)
    migrate(conn)
    existing = {row["key"] for row in conn.execute("SELECT key FROM settings")}
    for key, value in DEFAULT_SETTINGS:
        if key not in existing:
            set_setting(conn, key, value)

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        create_user(conn, "admin", "arat123", "Administrator", "admin")

    if conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
        from .seed import seed_catalog

        seed_catalog(conn)

    # The room inventory is created once and then left alone: adding rooms is
    # harmless, so this is safe on every start-up.
    _ensure_default_rooms(conn)

    # Invoices raised before the cash ledger existed carry a paid amount but
    # no payment row, which would under-report collections. The backfill is
    # idempotent, so it is safe on every start-up.
    _backfill_payments(conn)

    conn.commit()


def _ensure_default_rooms(conn: sqlite3.Connection) -> None:
    """Create the room inventory the hotel is configured for.

    The list comes from the ``room_numbers`` setting when the hotel has set
    one, and falls back to the default 25 rooms (101-125). Existing rooms are
    never renamed or removed.
    """
    from . import rooms

    try:
        configured = (get_settings(conn).get("room_numbers") or "").strip()
        numbers = rooms.parse_room_numbers(configured) if configured else None
        rooms.ensure_inventory(conn, numbers)
    except Exception:  # noqa: BLE001 - a room problem must not block start-up
        pass


def _backfill_payments(conn: sqlite3.Connection) -> None:
    """Give pre-ledger invoices a matching payment row, once."""
    try:
        from .payments import backfill_legacy_payments

        backfill_legacy_payments(conn)
    except Exception:  # noqa: BLE001 - never block start-up on the backfill
        pass
