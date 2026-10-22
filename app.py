#!/usr/bin/env python3
"""Arati Hotel — billing application.

Desktop till for the front desk: rooms, restaurant and services on one bill,
Nepal VAT and service charge, A4 invoice plus 80mm thermal receipt.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from arati import db, invoice, ui
from arati.screens.admin import SettingsScreen, StaffScreen
from arati.screens.billing import BillingScreen
from arati.screens.bills import BillsScreen
from arati.screens.catalog import CatalogScreen
from arati.screens.login import LoginFrame
from arati.screens.reports import ReportsScreen

APP_DIR = Path(__file__).resolve().parent
# ARATI_INVOICE_DIR lets a deployment write PDFs to a different volume.
INVOICE_DIR = Path(os.environ.get("ARATI_INVOICE_DIR") or (APP_DIR / "invoices"))

SCREENS = [
    ("billing", "Billing", BillingScreen, False),
    ("bills", "Invoices", BillsScreen, False),
    ("catalog", "Catalog", CatalogScreen, False),
    ("reports", "Reports", ReportsScreen, False),
    ("staff", "Staff", StaffScreen, True),
    ("settings", "Settings", SettingsScreen, True),
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
        INVOICE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

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
        for key, label, screen_class, admin_only in SCREENS:
            if admin_only and self.user["role"] != "admin":
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

        self.open_screen("billing")

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

    def refresh_settings(self) -> None:
        self.settings = db.get_settings(self.conn)

    def _clear(self) -> None:
        for child in self._container.winfo_children():
            child.destroy()


def main() -> None:
    app = AratiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
