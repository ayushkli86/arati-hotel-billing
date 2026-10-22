from arati import db
from arati.money import Line, compute_totals


def make_db(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.bootstrap(conn)
    return conn


def bill_payload(lines, totals, payment_method="Cash", **guest):
    return dict(
        prefix="ARH",
        guest={"name": "Sita Rai", "phone": "9800000000", **guest},
        lines=lines,
        totals=totals.as_dict(),
        payment_method=payment_method,
        user_id=1,
    )


def test_bootstrap_seeds_catalog_and_admin(tmp_path):
    conn = make_db(tmp_path)

    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert db.authenticate(conn, "admin", "arat123") is not None
    assert db.authenticate(conn, "admin", "wrong") is None

    items = db.list_items(conn)
    assert len(items) == 34                     # 5 room types + 23 dishes + 6 services
    assert any(i["name"] == "Chicken Biryani" and i["price"] == 490 for i in items)
    assert len(db.list_rooms(conn)) == 10
    assert db.get_room(conn, "2001")["room_type"] == "Deluxe Room"


def test_bootstrap_is_idempotent(tmp_path):
    conn = make_db(tmp_path)
    db.bootstrap(conn)
    db.bootstrap(conn)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 34
    assert len(db.list_rooms(conn)) == 10


def test_bill_numbering_and_persistence(tmp_path):
    conn = make_db(tmp_path)
    lines = [
        {"description": "Chicken Biryani", "qty": 2, "unit_price": 490.0,
         "line_total": 980.0, "category": "food", "unit": "plate", "taxable": True},
        {"description": "Deluxe Room — Room 2001", "qty": 2, "unit_price": 4500.0,
         "line_total": 9000.0, "category": "room", "unit": "night", "taxable": True},
    ]
    totals = compute_totals([Line("x", 1, 9980.0)])

    first = db.create_bill(conn, **bill_payload(lines, totals))
    second = db.create_bill(conn, **bill_payload(lines, totals))

    assert first == "ARH0000001"
    assert second == "ARH0000002"

    bill, saved_lines = db.get_bill(conn, first)
    assert bill["total"] == 12405.14
    assert bill["guest_name"] == "Sita Rai"
    assert len(saved_lines) == 2


def test_void_bill_excluded_from_reports(tmp_path):
    conn = make_db(tmp_path)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    lines = [{"description": "Lunch", "qty": 1, "unit_price": 1000.0,
              "line_total": 1000.0, "category": "food", "taxable": True}]

    bill_no = db.create_bill(conn, **bill_payload(lines, totals))
    db.void_bill(conn, bill_no)

    summary = db.sales_summary(conn, "2000-01-01", "2100-01-01")
    assert summary["totals"]["bills"] == 0
    assert summary["totals"]["total"] == 0


def test_reports_group_by_method_and_category(tmp_path):
    conn = make_db(tmp_path)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    lines = [{"description": "Lunch", "qty": 1, "unit_price": 1000.0,
              "line_total": 1000.0, "category": "food", "taxable": True}]
    db.create_bill(conn, **bill_payload(lines, totals))
    db.create_bill(conn, **bill_payload(lines, totals, payment_method="Card"))

    summary = db.sales_summary(conn, "2000-01-01", "2100-01-01")
    assert summary["totals"]["bills"] == 2
    methods = {row["payment_method"]: row["bills"] for row in summary["by_method"]}
    assert methods["Cash"] == 1
    assert summary["by_category"][0]["category"] == "food"


def test_settings_roundtrip(tmp_path):
    conn = make_db(tmp_path)
    db.save_settings(conn, {"vat_rate": "13", "hotel_name": "Arati Hotel"})
    settings = db.get_settings(conn)
    assert settings["vat_rate"] == "13"
    assert settings["bill_prefix"] == "ARH"
    assert settings["service_charge_rate"] == "10"


# --------------------------------------------------------------------------- #
# invoice type, customer type and additive migration
# --------------------------------------------------------------------------- #
def test_bill_type_and_footer_fields_persist(tmp_path):
    conn = make_db(tmp_path)
    totals = compute_totals([Line("Lunch", 1, 1000.0)], bill_type="supply")
    payload = bill_payload([{
        "description": "Lunch", "qty": 1, "unit_price": 1000.0, "line_total": 1000.0,
        "category": "food", "taxable": True, "code": "FOOD-1",
    }], totals)
    payload.update(bill_type="supply", customer_type="business", payment_terms="Due in 7 days",
                   prepared_by="Sita", received_by="Ram")
    bill_no = db.create_bill(conn, **payload)

    bill, lines = db.get_bill(conn, bill_no)
    assert bill["bill_type"] == "supply"
    assert bill["customer_type"] == "business"
    assert bill["payment_terms"] == "Due in 7 days"
    assert bill["prepared_by"] == "Sita"
    assert bill["received_by"] == "Ram"
    assert bill["vat"] == 0
    assert lines[0]["code"] == "FOOD-1"


def test_migration_adds_columns_and_keeps_bills(tmp_path):
    conn = make_db(tmp_path)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    bill_no = db.create_bill(conn, **bill_payload([{
        "description": "Lunch", "qty": 1, "unit_price": 1000.0, "line_total": 1000.0,
        "category": "food", "taxable": True,
    }], totals))

    # Simulate a database created before the redesign.
    for column in ("bill_type", "customer_type", "payment_terms", "prepared_by", "received_by"):
        conn.execute(f"ALTER TABLE bills DROP COLUMN {column}")
    conn.execute("ALTER TABLE bill_items DROP COLUMN code")
    conn.commit()

    db.migrate(conn)

    bill, _ = db.get_bill(conn, bill_no)
    assert bill["bill_type"] == "tax"          # default for legacy rows
    assert bill["customer_type"] == "individual"
    assert bill["total"] > 0


# --------------------------------------------------------------------------- #
# taxable base is stored, and recovered for bills saved before the fix
# --------------------------------------------------------------------------- #
def _one_line_bill(conn, **kwargs):
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    lines = [{"description": "Lunch", "qty": 1, "unit_price": 1000.0,
              "line_total": 1000.0, "category": "food", "taxable": True}]
    return db.create_bill(conn, **bill_payload(lines, totals, **kwargs))


def test_taxable_amount_is_persisted(tmp_path):
    conn = make_db(tmp_path)
    bill_no = _one_line_bill(conn)
    bill, _ = db.get_bill(conn, bill_no)
    assert bill["taxable_net"] == 1000.00
    assert bill["vat"] == 143.00


def test_backfill_recovers_taxable_amount(tmp_path):
    conn = make_db(tmp_path)
    bill_no = _one_line_bill(conn)
    conn.execute("UPDATE bills SET taxable_net = 0 WHERE bill_no = ?", (bill_no,))
    conn.commit()

    db.migrate(conn)

    bill, _ = db.get_bill(conn, bill_no)
    assert bill["taxable_net"] == 1000.00


def test_backfill_leaves_bill_of_supply_alone(tmp_path):
    conn = make_db(tmp_path)
    totals = compute_totals([Line("Lunch", 1, 1000.0)], bill_type="supply")
    payload = bill_payload([{"description": "Lunch", "qty": 1, "unit_price": 1000.0,
                             "line_total": 1000.0, "category": "food", "taxable": True}], totals)
    payload["bill_type"] = "supply"
    bill_no = db.create_bill(conn, **payload)
    conn.execute("UPDATE bills SET taxable_net = 0 WHERE bill_no = ?", (bill_no,))
    conn.commit()

    db.migrate(conn)

    bill, _ = db.get_bill(conn, bill_no)
    assert bill["taxable_net"] == 0
