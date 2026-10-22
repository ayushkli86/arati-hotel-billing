#!/usr/bin/env python3
"""Arati Hotel — billing and hotel management application.

Desktop till for the front desk: rooms, restaurant and services on one bill,
Nepal VAT and service charge, A4 invoice plus 80mm/58mm thermal receipts,
25-room management, a reports dashboard, sales analysis and an automatic
daily closing at midnight in the hotel's business timezone.

The daily-closing scheduler runs as a background thread inside this process,
so closing a business day never depends on a browser tab being open. The same
job is available as a command line for cron-style scheduling
(:mod:`scripts.close_day`).
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from arati import db, invoice, permissions, printing, scheduler, ui
from arati.screens.admin import SettingsScreen, StaffScreen
from arati.screens.analysis import AnalysisScreen
from arati.screens.billing import BillingScreen
from arati.screens.bills import BillsScreen
from arati.screens.catalog import CatalogScreen
from arati.screens.customers import CustomersScreen
from arati.screens.dashboard import DashboardScreen
from arati.screens.login import LoginFrame
from arati.screens.payments import PaymentsScreen
from arati.screens.printer import PrinterSettingsScreen
from arati.screens.reports import ReportsScreen
from arati.screens.rooms_screen import RoomsScreen

APP_DIR = Path(__file__).resolve().parent
# ARATI_INVOICE_DIR lets a deployment write PDFs to a different volume.
INVOICE_DIR = Path(os.environ.get("ARATI_INVOICE_DIR") or (APP_DIR / "invoices"))
# ARATI_REPORT_DIR holds the daily closing PDFs and the exported reports.
REPORT_DIR = Path(os.environ.get("ARATI_REPORT_DIR") or (APP_DIR / "reports"))
# ARATI_DISABLE_SCHEDULER turns the background closing job off, for a
# machine that only reads the database.
SCHEDULER_ENABLED = os.environ.get("ARATI_DISABLE_SCHEDULER", "") == ""

# key, label, screen class, permission required to see it
SCREENS = [
    ("dashboard", "Dashboard", DashboardScreen, "dashboard.view"),
    ("billing", "Billing", BillingScreen, "invoice.create"),
    ("bills", "Invoices", BillsScreen, "invoice.view"),
    ("customers", "Customers", CustomersScreen, "customer.view"),
    ("rooms", "Rooms", RoomsScreen, "room.view"),
    ("payments", "Payments", PaymentsScreen, "payment.view"),
    ("reports", "Reports", ReportsScreen, "report.view"),
    ("analysis", "Sales Analysis", AnalysisScreen, "analysis.view"),
    ("catalog", "Catalog", CatalogScreen, "catalog.view"),
    ("printer", "Printer Settings", PrinterSettingsScreen, "settings.printer"),
    ("staff", "Staff", StaffScreen, "staff.manage"),
    ("settings", "Hotel Settings", SettingsScreen, "settings.hotel"),
]


class AratiApp(tk.Tk):
    def __init__(self, db_path: Path | str | None = None):
        super().__init__()
        self.title("Arati Hotel · Billing")
        self.geometry("1440x900")
        self.minsize(1280, 760)
        ui.apply_theme(self)

        self.conn = db.connect(db_path or db.DB_PATH)
        db.bootstrap(self.conn)
        self.settings = db.get_settings(self.conn)
        self.user = None
        self.screens: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.report_directory = REPORT_DIR
        self.scheduler: scheduler.Scheduler | None = None
        self._scheduler_stop = threading.Event()
        INVOICE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        REPORT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

        self._container = ttk.Frame(self)
        self._container.pack(fill="both", expand=True)
        self.show_login()

    # ---------------------------------------------------------------- auth
    def show_login(self) -> None:
        self._clear()
        LoginFrame(self._container, self).pack(fill="both", expand=True)

    def sign_in(self, user) -> None:
        self.user = user
        self.show_shell()

    def sign_out(self) -> None:
        self.user = None
        self.screens.clear()
        self.nav_buttons.clear()
        self.show_login()

    # --------------------------------------------------------------- shell
    def show_shell(self) -> None:
        self._clear()
        shell = ttk.Frame(self._container)
        shell.pack(fill="both", expand=True)

        sidebar = ttk.Frame(shell, style="Sidebar.TFrame", width=232)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = ttk.Frame(sidebar, style="Sidebar.TFrame")
        brand.pack(fill="x", padx=20, pady=(24, 22))
        ttk.Label(brand, text="ARATI", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(brand, text="HOTEL · KHANDBARI", style="SidebarSub.TLabel").pack(anchor="w")

        nav = ttk.Frame(sidebar, style="Sidebar.TFrame")
        nav.pack(fill="both", expand=True)
        for key, label, screen_class, permission in SCREENS:
            if not self._may_see(permission):
                continue
            button = ttk.Button(nav, text=f"  {label}", style="Nav.TButton",
                                command=lambda k=key: self.open_screen(k))
            button.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = button

        footer = ttk.Frame(sidebar, style="Sidebar.TFrame")
        footer.pack(fill="x", side="bottom", padx=16, pady=16)
        ttk.Label(footer, text=self.user["full_name"] or self.user["username"],
                  style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(footer, text=f"{self.user['role'].title()} · signed in",
                  style="SidebarSub.TLabel").pack(anchor="w")
        ttk.Button(footer, text="Sign out", style="Ghost.TButton",
                   command=self.sign_out).pack(fill="x", pady=(10, 0))

        self.content = ttk.Frame(shell)
        self.content.pack(side="left", fill="both", expand=True, padx=18, pady=16)

        self._start_scheduler()
        self.open_screen(self._first_screen())

    def _may_see(self, permission: str) -> bool:
        """Whether the signed-in role may open a screen.

        The check is a courtesy so a staff account is not offered a screen it
        cannot use. The data layer asks the same question again before it
        acts, so hiding the screen is never the only control.
        """
        if self.user is None:
            return False
        return permissions.can(self.user, permission)

    def _first_screen(self) -> str:
        for key, _label, _screen, permission in SCREENS:
            if key in self.nav_buttons:
                return key
        return "billing"

    def _mark_nav(self, key: str) -> None:
        for nav_key, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if nav_key == key else "Nav.TButton")

    def open_screen(self, key: str) -> None:
        for child in self.content.winfo_children():
            child.pack_forget()
        if key not in self.screens:
            entry = next(s for s in SCREENS if s[0] == key)
            self.screens[key] = entry[2](self.content, self)
        screen = self.screens[key]
        screen.pack(fill="both", expand=True)
        for method in ("reload", "reload_catalog", "run"):
            if hasattr(screen, method):
                getattr(screen, method)()
                break
        self._mark_nav(key)

    def open_draft(self, bill: dict, lines: list) -> None:
        """Switch to the billing form with a saved draft loaded for editing."""
        self.open_screen("billing")
        screen = self.screens.get("billing")
        if screen is not None and hasattr(screen, "load_draft"):
            screen.load_draft(bill, lines)

    # ------------------------------------------------------------ documents
    def render_invoice(self, bill: dict, lines: list) -> Path | None:
        try:
            path = INVOICE_DIR / f"{bill['bill_no']}.pdf"
            invoice.build_a4_pdf(path, bill, lines, self.settings)
            thermal = INVOICE_DIR / "thermal" / f"{bill['bill_no']}.pdf"
            invoice.build_thermal_pdf(thermal, bill, lines, self.settings)
            device = self.settings.get("thermal_device", "")
            if device:
                try:
                    invoice.send_to_device(
                        invoice.escpos_bytes(bill, lines, self.settings), device
                    )
                except OSError:
                    pass
            return path
        except Exception as exc:  # noqa: BLE001 - never lose a saved bill
            from tkinter import messagebox

            messagebox.showerror("Invoice error", f"Bill saved, but the PDF failed:\n{exc}")
            return None

    def render_preview(self, bill: dict, lines: list) -> Path | None:
        """Render the current form to a throwaway PDF without saving the bill."""
        try:
            path = INVOICE_DIR / "preview.pdf"
            invoice.build_a4_pdf(path, bill, lines, self.settings)
            self.open_pdf(path)
            return path
        except Exception as exc:  # noqa: BLE001
            from tkinter import messagebox

            messagebox.showerror("Preview error", str(exc))
            return None

    def render_receipt(self, bill: dict, lines: list) -> Path | None:
        try:
            path = INVOICE_DIR / "thermal" / f"{bill['bill_no']}.pdf"
            invoice.build_thermal_pdf(path, bill, lines, self.settings)
            return path
        except Exception as exc:  # noqa: BLE001
            from tkinter import messagebox

            messagebox.showerror("Receipt error", str(exc))
            return None

    # -------------------------------------------------------------- printing
    def print_invoice(
        self, bill: dict, lines: list, settings: dict | None = None
    ) -> Path:
        """Render the invoice for printing and open it in the browser.

        The document carries the paper size and margins the administrator
        chose. The browser's own print dialog decides which physical printer
        receives it — that part is the browser's and the driver's, not this
        app's.
        """
        settings = settings if settings is not None else self.settings
        config = printing.resolve(settings)
        path = INVOICE_DIR / "print" / f"{bill.get('bill_no') or 'invoice'}.html"
        printing.build_print_file(path, bill, lines, settings, config)
        self.open_in_browser(path)
        return path

    def download_invoice_pdf(
        self, bill: dict, lines: list, settings: dict | None = None
    ) -> Path:
        """Build the downloadable PDF from the very same print document."""
        settings = settings if settings is not None else self.settings
        config = printing.resolve(settings)
        path = INVOICE_DIR / f"{bill.get('bill_no') or 'invoice'}.pdf"
        printing.build_pdf(path, bill, lines, settings, config)
        return path

    def sample_invoice(self) -> tuple[dict | None, list]:
        """A real invoice to test the printer with.

        The most recent issued invoice is used, so a test print carries the
        same fields a guest will actually see. When the hotel has not raised
        an invoice yet, a small synthetic one is used instead of showing
        nothing.
        """
        rows = db.list_bills(self.conn, "", limit=1)
        for row in rows:
            if row["status"] == "issued" and not row["is_draft"]:
                found = db.get_bill(self.conn, row["bill_no"])
                if found:
                    bill, lines = found
                    return bill, [dict(line) for line in lines]
        return self._synthetic_invoice()

    def _synthetic_invoice(self) -> tuple[dict, list]:
        settings = self.settings
        total = 1000.0
        bill = {
            "bill_no": "SAMPLE",
            "bill_date": db.now()[:10],
            "created_at": db.now(),
            "guest_name": "Sample Guest",
            "guest_phone": "",
            "guest_address": "",
            "guest_pan": "",
            "room_no": "101",
            "nights": 1,
            "subtotal": total,
            "discount": 0.0,
            "item_discount": 0.0,
            "net_subtotal": total,
            "taxable_net": total,
            "service_charge_rate": float(settings.get("service_charge_rate", 0) or 0),
            "service_charge": 0.0,
            "vat_rate": float(settings.get("vat_rate", 0) or 0),
            "vat": 0.0,
            "total": total,
            "paid": total,
            "balance": 0.0,
            "payment_method": "Cash",
            "bill_type": "tax",
            "status": "issued",
            "prepared_by": "Printer test",
            "payment_terms": settings.get("payment_terms", ""),
            "notes": "Printer test invoice",
            "language": settings.get("invoice_language", "en"),
        }
        lines = [
            {
                "description": "Sample room charge",
                "category": "room",
                "qty": 1,
                "unit_price": total,
                "unit_price_total": total,
                "line_total": total,
                "taxable": True,
                "unit": "night",
                "discount": 0.0,
            }
        ]
        return bill, lines

    def open_pdf(self, path: Path) -> None:
        if not path or not Path(path).exists():
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            pass

    def open_in_browser(self, path: Path) -> None:
        """Open an HTML document in the default browser."""
        if not path or not Path(path).exists():
            return
        target = Path(path).resolve().as_uri()
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except OSError:
            pass

    # ------------------------------------------------------------- settings
    def refresh_settings(self) -> None:
        self.settings = db.get_settings(self.conn)

    # ------------------------------------------------------------ scheduler
    def _start_scheduler(self) -> None:
        """Run the daily closing job in the background.

        The job closes the previous business day at the configured local
        time. It writes its own run history, and it is idempotent, so a
        restart during the night cannot duplicate a day's report.
        """
        if not SCHEDULER_ENABLED:
            return
        if self.settings.get("auto_close_enabled", "1") not in ("1", "true", "True"):
            return

        def factory() -> sqlite3.Connection:
            conn = sqlite3.connect(str(db.DB_PATH), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            return conn

        self.scheduler = scheduler.Scheduler(
            factory,
            self.report_directory,
            settings=self.settings,
            stop_event=self._scheduler_stop,
            owns_connection=True,
        )
        self.scheduler.start()

    def stop_scheduler(self) -> None:
        if self.scheduler is not None:
            self.scheduler.stop()
        self._scheduler_stop.set()

    def _clear(self) -> None:
        for child in self._container.winfo_children():
            child.destroy()


def main() -> None:
    app = AratiApp()
    try:
        app.mainloop()
    finally:
        app.stop_scheduler()


if __name__ == "__main__":
    main()
