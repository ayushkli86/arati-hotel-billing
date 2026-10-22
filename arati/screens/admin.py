"""Admin screens: staff accounts and hotel settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import db, ui
from ..nepali import LANGUAGE_CODES, LANGUAGE_LABELS


class StaffScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.user_id = None

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Staff", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Accounts that can sign in to the till", style="Muted.TLabel").pack(
            side="left", padx=14, pady=(10, 0)
        )

        card = ui.Card(self)
        card.pack(fill="both", expand=True)
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = ui.table(
            wrap,
            [("username", "Username", 150), ("name", "Full name", 200),
             ("role", "Role", 90), ("active", "Active", 70), ("created", "Created", 140)],
            height=12,
        )
        self.tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.tree, wrap).pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.load_user())

        self.username = tk.StringVar()
        self.full_name = tk.StringVar()
        self.role = tk.StringVar(value="staff")
        self.active = tk.BooleanVar(value=True)
        self.password = tk.StringVar()

        form = ttk.Frame(self)
        form.pack(fill="x", pady=(10, 0))
        for label, var, width, show in (
            ("Username", self.username, 16, None),
            ("Full name", self.full_name, 24, None),
            ("Password", self.password, 18, "•"),
        ):
            ui.field(form, label, var, width=width, card=False, show=show).pack(
                side="left", padx=(0, 8)
            )
        ui.field(form, "Role", self.role, width=10, card=False).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(form, text="Active", variable=self.active).pack(side="left", pady=(14, 0))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="New user", style="Ghost.TButton",
                   command=self.clear).pack(side="left")
        ttk.Button(buttons, text="Save user", style="Primary.TButton",
                   command=self.save).pack(side="left", padx=6)
        ttk.Button(buttons, text="Delete", style="Danger.TButton",
                   command=self.delete).pack(side="left")

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))
        self.reload()

    def reload(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for user in db.list_users(self.conn):
            self.tree.insert("", "end", iid=str(user["user_id"]), values=(
                user["username"], user["full_name"], user["role"],
                "Yes" if user["active"] else "No", user["created_at"][:10],
            ))

    def load_user(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        user = next(u for u in db.list_users(self.conn) if str(u["user_id"]) == selection[0])
        self.user_id = user["user_id"]
        self.username.set(user["username"])
        self.full_name.set(user["full_name"])
        self.role.set(user["role"])
        self.active.set(bool(user["active"]))
        self.password.set("")

    def clear(self) -> None:
        self.user_id = None
        self.username.set("")
        self.full_name.set("")
        self.role.set("staff")
        self.active.set(True)
        self.password.set("")

    def save(self) -> None:
        username = self.username.get().strip().lower()
        password = self.password.get()
        if not username:
            ui.notify(self.status, "Username is required.", ui.DANGER)
            return
        try:
            if self.user_id:
                db.update_user(
                    self.conn, self.user_id, self.full_name.get(), self.role.get(),
                    self.active.get(), password or None,
                )
                ui.notify(self.status, f"Updated {username}.", ui.OK)
            else:
                if len(password) < 6:
                    ui.notify(self.status, "Password must be at least 6 characters.", ui.DANGER)
                    return
                db.create_user(
                    self.conn, username, password, self.full_name.get(), self.role.get()
                )
                ui.notify(self.status, f"Created {username}.", ui.OK)
        except Exception as exc:
            ui.notify(self.status, f"Could not save: {exc}", ui.DANGER)
            return
        self.reload()

    def delete(self) -> None:
        if not self.user_id:
            ui.notify(self.status, "Select a user first.", ui.DANGER)
            return
        if self.user_id == self.app.user["user_id"]:
            messagebox.showwarning("Not allowed", "You cannot delete the signed-in account.")
            return
        if not ui.ask("Delete this user account?"):
            return
        try:
            db.delete_user(self.conn, self.user_id)
        except ValueError as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return
        self.clear()
        self.reload()
        ui.notify(self.status, "User deleted.", ui.MUTED)


class SettingsScreen(ttk.Frame):
    FIELDS = (
        ("hotel_name", "Hotel name"),
        ("hotel_name_ne", "Hotel name (Nepali)"),
        ("hotel_address1", "Address line 1"),
        ("hotel_address2", "Address line 2"),
        ("hotel_phone", "Phone"),
        ("hotel_email", "Email"),
        ("hotel_website", "Website"),
        ("hotel_pan", "PAN number"),
        ("hotel_vat", "VAT registration number"),
        ("bill_prefix", "Bill number prefix"),
        ("vat_rate", "VAT %"),
        ("service_charge_rate", "Service charge %"),
        ("thermal_device", "Thermal printer device"),
        ("invoice_copy", "Invoice copy label"),
        ("payment_terms", "Default payment terms"),
        ("return_policy", "Return / exchange policy"),
        ("logo_path", "Logo file path"),
        ("date_format", "Date format (DD/MM/YYYY or YYYY-MM-DD)"),
        ("invoice_language", "Invoice language"),
        ("footer_note", "Invoice footer"),
    )

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.values = {key: tk.StringVar() for key, _ in self.FIELDS}

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Settings", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Hotel details printed on every invoice",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(10, 0))

        card = ui.Card(self)
        card.pack(fill="both", expand=True)
        grid = ttk.Frame(card.inner, style="Card.TFrame")
        grid.pack(fill="both", expand=True)

        for index, (key, label) in enumerate(self.FIELDS):
            row, col = divmod(index, 2)
            cell = ui.field(grid, label, self.values[key], width=34)
            if key == "invoice_language":
                cell.entry.destroy()
                box = ttk.Combobox(cell, textvariable=self.values[key],
                                   values=list(LANGUAGE_CODES), state="readonly")
                box.pack(fill="x", pady=(2, 0))
            cell.grid(row=row, column=col, sticky="ew", padx=(0, 16), pady=(0, 10))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Save settings", style="Primary.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(buttons, text="Reload", style="Ghost.TButton",
                   command=self.load).pack(side="right", padx=8)
        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))
        self.load()

    def load(self) -> None:
        settings = db.get_settings(self.conn)
        for key, _ in self.FIELDS:
            self.values[key].set(settings.get(key, ""))
        self.values["invoice_language"].set(
            LANGUAGE_LABELS.get(settings.get("invoice_language", "en"), "English")
        )

    def save(self) -> None:
        try:
            vat = float(self.values["vat_rate"].get())
            service = float(self.values["service_charge_rate"].get())
            if not 0 <= vat <= 100 or not 0 <= service <= 100:
                raise ValueError
        except ValueError:
            ui.notify(self.status, "VAT and service charge must be between 0 and 100.",
                      ui.DANGER)
            return
        prefix = self.values["bill_prefix"].get().strip().upper()
        if not prefix or not prefix.isalnum():
            ui.notify(self.status, "Bill prefix must be letters/digits.", ui.DANGER)
            return
        if self.values["date_format"].get().strip() not in ("DD/MM/YYYY", "YYYY-MM-DD"):
            ui.notify(self.status, "Date format must be DD/MM/YYYY or YYYY-MM-DD.", ui.DANGER)
            return
        language = LANGUAGE_CODES.get(self.values["invoice_language"].get().strip(), "en")
        payload = {key: var.get().strip() for key, var in self.values.items()}
        payload["invoice_language"] = language
        db.save_settings(self.conn, payload)
        self.app.refresh_settings()
        ui.notify(self.status, "Settings saved.", ui.OK)
