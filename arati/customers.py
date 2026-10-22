"""Customer master records for the billing app."""

from __future__ import annotations

import sqlite3

from .db import now


def list_customers(conn: sqlite3.Connection, search: str = "") -> list[sqlite3.Row]:
    sql = "SELECT * FROM customers WHERE active = 1"
    params: list = []
    if search:
        sql += " AND (name LIKE ? OR phone LIKE ? OR pan LIKE ?)"
        params = [f"%{search}%"] * 3
    sql += " ORDER BY name COLLATE NOCASE"
    return list(conn.execute(sql, params))


def get_customer(conn: sqlite3.Connection, customer_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()


def upsert_customer(
    conn: sqlite3.Connection,
    name: str,
    phone: str = "",
    address: str = "",
    pan: str = "",
    customer_type: str = "individual",
) -> int | None:
    """Return a customer id, reusing the record when name (and phone) already exist."""
    name = (name or "").strip()
    if not name:
        return None
    phone = (phone or "").strip()

    if phone:
        row = conn.execute(
            "SELECT customer_id FROM customers WHERE active = 1 AND phone = ? AND name = ?",
            (phone, name),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT customer_id FROM customers WHERE active = 1 AND name = ? AND phone = ''",
            (name,),
        ).fetchone()

    if row:
        conn.execute(
            "UPDATE customers SET address = COALESCE(NULLIF(?, ''), address), "
            "pan = COALESCE(NULLIF(?, ''), pan), customer_type = ? WHERE customer_id = ?",
            (address.strip(), pan.strip(), customer_type, row["customer_id"]),
        )
        conn.commit()
        return int(row["customer_id"])

    cur = conn.execute(
        "INSERT INTO customers (name, phone, address, pan, customer_type, created_at, active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (name, phone, address.strip(), pan.strip(), customer_type, now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def save_customer(conn: sqlite3.Connection, customer_id: int, **fields) -> None:
    allowed = {"name", "phone", "address", "pan", "customer_type", "active"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE customers SET {assignments} WHERE customer_id = ?",
        (*updates.values(), customer_id),
    )
    conn.commit()


def deactivate_customer(conn: sqlite3.Connection, customer_id: int) -> None:
    conn.execute("UPDATE customers SET active = 0 WHERE customer_id = ?", (customer_id,))
    conn.commit()
