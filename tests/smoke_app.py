"""Boot the real application and build every screen.

This runs the actual Tk application against a throwaway database, signs in
as an administrator, opens every screen in the sidebar and then signs in as
a staff member to check the restricted screens stay closed. It is the
cheapest way to catch a screen that raises on construction — the kind of
error that only shows up when a user clicks the menu item.

Run it with a display available:

    xvfb-run -a .venv/bin/python tests/smoke_app.py

It is not part of the pytest suite because it needs a display; the CI job
runs it explicitly.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The scheduler writes into the report directory; keep the smoke test's
# output inside the temporary folder.
os.environ.setdefault("ARATI_DISABLE_SCHEDULER", "1")


def main() -> int:
    import app as app_module
    from arati import db, permissions

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        app_module.INVOICE_DIR = tmp_path / "invoices"
        app_module.REPORT_DIR = tmp_path / "reports"

        application = app_module.AratiApp(db_path=tmp_path / "smoke.db")
        application.update_idletasks()

        # --- sign in as the administrator -------------------------------
        admin = db.authenticate(application.conn, "admin", "arat123")
        if admin is None:
            print("FAIL: the default admin account could not sign in.")
            return 1
        application.sign_in(admin)
        application.update_idletasks()

        failures: list[str] = []
        for key, label, _screen, permission in app_module.SCREENS:
            if not permissions.can(admin, permission):
                print(f"skip {key:12s} — admin lacks {permission}")
                continue
            try:
                application.open_screen(key)
                application.update_idletasks()
                print(f"ok   {key:12s} — {label}")
            except Exception as exc:  # noqa: BLE001 - the point is to report it
                failures.append(f"{key}: {type(exc).__name__}: {exc}")
                print(f"FAIL {key:12s} — {type(exc).__name__}: {exc}")
                import traceback

                traceback.print_exc()

        # --- a staff member must not reach the privileged screens --------
        application.sign_out()
        application.update_idletasks()
        db.create_user(application.conn, "frontdesk", "frontdesk123", "Front Desk", "staff")
        staff = db.authenticate(application.conn, "frontdesk", "frontdesk123")
        application.sign_in(staff)
        application.update_idletasks()

        visible = set(application.nav_buttons)
        for restricted in ("printer", "staff", "settings", "analysis"):
            if restricted in visible:
                failures.append(
                    f"staff can see the {restricted!r} screen, which is admin-only"
                )
                print(f"FAIL staff should not see {restricted}")
            else:
                print(f"ok   staff cannot see {restricted}")
        for key in visible:
            try:
                application.open_screen(key)
                application.update_idletasks()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"staff/{key}: {type(exc).__name__}: {exc}")
                print(f"FAIL staff/{key}: {exc}")

        application.destroy()

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nAll screens built cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
