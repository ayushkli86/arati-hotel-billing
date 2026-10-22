"""Cash ledger: payments, refunds and adjustments.

Sales and cash are different things. A sale is *earned* on the invoice date;
cash is *received* on the day the money actually changes hands. A guest who
checks out today and pays tomorrow earns revenue today and puts cash in the
drawer tomorrow, so the two are tracked in separate tables and reported
separately.

Rules enforced here:

* A payment is never larger than the balance it settles.
* A refund is never larger than the cash already taken for that invoice.
* Nothing is ever deleted. Corrections are recorded as new ledger rows, so
  the money trail stays intact and the daily report can be reproduced.
* Every adjustment is written to the audit log.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from . import business_time as bt
from .money import from_paisa, to_paisa

REFUND_REASONS = (
    "Service not delivered",
    "Guest overcharged",
    "Booking cancelled",
    "Courtesy / goodwill",
    "Other (see note)",
)

ADJUSTMENT_REASONS = (
    "Correct earlier entry",
    "Goodwill credit",
    "Service charge waiver",
    "Other (see note)",
)


class LedgerError(ValueError):
    """Raised when a ledger entry would be invalid."""


# --------------------------------------------------------------------------- #
# payments
# --------------------------------------------------------------------------- #
def record_payment(
    conn: sqlite3.Connection,
    bill_no: str,
    amount: float,
    method: str = "Cash",
    user_id: int | None = None,
    note: str = "",
    paid_at: datetime | None = None,
) -> int:
    """Record cash received against an invoice and settle its balance.

    Returns the new payment id. Raises :class:`LedgerError` when the amount
    is not positive or exceeds the outstanding balance.
    """
    bill = _issued_bill(conn, bill_no)
    if bill is None:
        raise LedgerError(f"Invoice {bill_no} was not found or is not issued.")

    amount_paisa = to_paisa(amount)
    if amount_paisa <= 0:
        raise LedgerError("A payment must be greater than zero.")
    balance_paisa = to_paisa(bill["balance"])
    if amount_paisa > balance_paisa:
        raise LedgerError(
            f"Payment of {from_paisa(amount_paisa):,.2f} exceeds the balance of "
            f"{from_paisa(balance_paisa):,.2f} on {bill_no}."
        )

    moment = paid_at or bt.now()
    business_date = bt.business_date_of(moment)
    stamp = moment.strftime("%Y-%m-%d %H:%M:%S")

    with conn:
        cursor = conn.execute(
            "INSERT INTO payments (bill_id, bill_no, method, amount, paid_at, "
            "business_date, note, user_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                bill["bill_id"],
                bill_no,
                method,
                from_paisa(amount_paisa),
                stamp,
                business_date,
                note.strip(),
                user_id,
                bt.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        _settle(conn, bill, bill["paid"] + amount, bill["balance"] - amount)
    return int(cursor.lastrowid)


def record_refund(
    conn: sqlite3.Connection,
    bill_no: str,
    amount: float,
    method: str = "Cash",
    reason: str = "",
    user_id: int | None = None,
    refunded_at: datetime | None = None,
) -> int:
    """Return cash to a guest. The invoice balance goes back up by the amount."""
    bill = _issued_bill(conn, bill_no)
    if bill is None:
        raise LedgerError(f"Invoice {bill_no} was not found or is not issued.")

    amount_paisa = to_paisa(amount)
    if amount_paisa <= 0:
        raise LedgerError("A refund must be greater than zero.")
    paid_paisa = to_paisa(bill["paid"])
    if amount_paisa > paid_paisa:
        raise LedgerError(
            f"Refund of {from_paisa(amount_paisa):,.2f} exceeds the "
            f"{from_paisa(paid_paisa):,.2f} collected on {bill_no}."
        )

    moment = refunded_at or bt.now()
    stamp = moment.strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        cursor = conn.execute(
            "INSERT INTO refunds (bill_id, bill_no, kind, method, amount, reason, "
            "refunded_at, business_date, user_id, created_at) "
            "VALUES (?,?,'refund',?,?,?,?,?,?,?)",
            (
                bill["bill_id"],
                bill_no,
                method,
                from_paisa(amount_paisa),
                reason.strip(),
                stamp,
                bt.business_date_of(moment),
                user_id,
                bt.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        _settle(conn, bill, bill["paid"] - amount, bill["balance"] + amount)
    return int(cursor.lastrowid)


def record_adjustment(
    conn: sqlite3.Connection,
    bill_no: str,
    amount: float,
    reason: str = "",
    user_id: int | None = None,
    adjusted_at: datetime | None = None,
) -> int:
    """Post an authorised correction against an invoice balance.

    A positive amount reduces what the guest owes (a credit), a negative
    amount increases it (a surcharge). Adjustments never touch the invoice
    total, so the original sale stays visible.
    """
    bill = _issued_bill(conn, bill_no)
    if bill is None:
        raise LedgerError(f"Invoice {bill_no} was not found or is not issued.")
    if not reason.strip():
        raise LedgerError("An adjustment needs a reason for the audit trail.")

    amount_paisa = to_paisa(amount)
    if amount_paisa == 0:
        raise LedgerError("An adjustment must not be zero.")

    moment = adjusted_at or bt.now()
    stamp = moment.strftime("%Y-%m-%d %H:%M:%S")
    new_paid = bill["paid"] - amount
    new_balance = bill["balance"] + amount
    if new_paid < -0.005:
        raise LedgerError("An adjustment cannot push the paid amount below zero.")

    with conn:
        cursor = conn.execute(
            "INSERT INTO refunds (bill_id, bill_no, kind, method, amount, reason, "
            "refunded_at, business_date, user_id, created_at) "
            "VALUES (?,?,'adjustment','Adjustment',?,?,?,?,?,?)",
            (
                bill["bill_id"],
                bill_no,
                from_paisa(amount_paisa),
                reason.strip(),
                stamp,
                bt.business_date_of(moment),
                user_id,
                bt.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        _settle(conn, bill, new_paid, new_balance)
    return int(cursor.lastrowid)


def _issued_bill(conn: sqlite3.Connection, bill_no: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM bills WHERE bill_no = ? AND is_draft = 0 AND status = 'issued'",
        (bill_no,),
    ).fetchone()


def _settle(conn: sqlite3.Connection, bill: sqlite3.Row, paid: float, balance: float) -> None:
    conn.execute(
        "UPDATE bills SET paid = ?, balance = ? WHERE bill_id = ?",
        (round(paid + 0.0, 2), round(balance + 0.0, 2), bill["bill_id"]),
    )


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def list_payments(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    method: str | None = None,
    bill_no: str = "",
    limit: int = 500,
) -> list[sqlite3.Row]:
    """Payments received, newest first."""
    sql = (
        "SELECT p.*, b.guest_name, b.room_no, b.prepared_by, b.bill_date "
        "FROM payments p LEFT JOIN bills b ON b.bill_id = p.bill_id WHERE 1=1"
    )
    params: list = []
    if start:
        sql += " AND p.business_date >= ?"
        params.append(start)
    if end:
        sql += " AND p.business_date <= ?"
        params.append(end)
    if method and method != "All":
        sql += " AND p.method = ?"
        params.append(method)
    if bill_no:
        sql += " AND p.bill_no LIKE ?"
        params.append(f"%{bill_no}%")
    sql += " ORDER BY p.business_date DESC, p.payment_id DESC LIMIT ?"
    params.append(limit)
    return list(conn.execute(sql, params))


def list_refunds(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    kind: str | None = None,
    limit: int = 500,
) -> list[sqlite3.Row]:
    sql = (
        "SELECT r.*, b.guest_name, b.room_no FROM refunds r "
        "LEFT JOIN bills b ON b.bill_id = r.bill_id WHERE 1=1"
    )
    params: list = []
    if start:
        sql += " AND r.business_date >= ?"
        params.append(start)
    if end:
        sql += " AND r.business_date <= ?"
        params.append(end)
    if kind and kind != "All":
        sql += " AND r.kind = ?"
        params.append(kind)
    sql += " ORDER BY r.business_date DESC, r.refund_id DESC LIMIT ?"
    params.append(limit)
    return list(conn.execute(sql, params))


def bill_ledger(conn: sqlite3.Connection, bill_no: str) -> list[sqlite3.Row]:
    """Every cash movement recorded against one invoice."""
    return list(
        conn.execute(
            "SELECT * FROM payments WHERE bill_no = ? ORDER BY paid_at, payment_id",
            (bill_no,),
        )
    ) + list(
        conn.execute(
            "SELECT * FROM refunds WHERE bill_no = ? ORDER BY refunded_at, refund_id",
            (bill_no,),
        )
    )


def collections_by_method(
    conn: sqlite3.Connection, start: str, end: str
) -> list[sqlite3.Row]:
    """Cash collected per method over a business date range."""
    return list(
        conn.execute(
            "SELECT method, COUNT(*) AS entries, COALESCE(SUM(amount), 0) AS total "
            "FROM payments WHERE business_date BETWEEN ? AND ? "
            "GROUP BY method ORDER BY total DESC",
            (start, end),
        )
    )


def refunds_by_method(
    conn: sqlite3.Connection, start: str, end: str
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT method, COUNT(*) AS entries, COALESCE(SUM(amount), 0) AS total "
            "FROM refunds WHERE business_date BETWEEN ? AND ? AND kind = 'refund' "
            "GROUP BY method ORDER BY total DESC",
            (start, end),
        )
    )


def outstanding_total(conn: sqlite3.Connection, as_of: str | None = None) -> float:
    """Money still owed on invoices issued up to ``as_of``."""
    sql = (
        "SELECT COALESCE(SUM(balance), 0) FROM bills "
        "WHERE status = 'issued' AND is_draft = 0 AND balance > 0"
    )
    params: list = []
    if as_of:
        sql += " AND bill_date <= ?"
        params.append(as_of)
    return round(conn.execute(sql, params).fetchone()[0], 2)


def backfill_legacy_payments(conn: sqlite3.Connection) -> int:
    """Give pre-ledger invoices a matching payment row.

    Bills raised before the ledger existed carry a ``paid`` amount but no
    payment row, so daily collections would under-report. This creates one
    opening payment per affected invoice, dated on the invoice date, and is
    safe to run repeatedly.
    """
    rows = conn.execute(
        "SELECT b.bill_id, b.bill_no, b.paid, b.payment_method, b.bill_date, "
        "b.created_at FROM bills b "
        "WHERE b.is_draft = 0 AND b.status = 'issued' AND b.paid > 0 "
        "AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.bill_id = b.bill_id)"
    ).fetchall()
    if not rows:
        return 0
    with conn:
        for row in rows:
            conn.execute(
                "INSERT INTO payments (bill_id, bill_no, method, amount, paid_at, "
                "business_date, note, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    row["bill_id"],
                    row["bill_no"],
                    row["payment_method"] or "Cash",
                    round(row["paid"], 2),
                    row["created_at"] or f"{row['bill_date']} 12:00:00",
                    row["bill_date"],
                    "Opening balance carried over from before the cash ledger",
                    None,
                    bt.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
    return len(rows)
