"""Printer Settings — how the till prints.

The administrator chooses the paper size, the margins, what the header and
footer carry and how many copies a print produces. The app sets the page
size and the layout in the document; choosing a physical printer, and
printing without the dialog, still depends on the browser, the operating
system and the printer driver, so the screen says so plainly rather than
promising something it cannot deliver.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import db, permissions, printing, ui

PAPER_LABELS = {
    "A4": "A4 — full tax invoice (210 × 297 mm)",
    "80": "80 mm thermal receipt",
    "58": "58 mm thermal receipt",
}

MARGIN_LABELS = {
    "narrow": "Narrow (8 mm)",
    "normal": "Normal (12 mm)",
    "wide": "Wide (18 mm)",
}


class PrinterSettingsScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        settings = db.get_settings(self.conn)

        self.paper = tk.StringVar(value=settings.get("printer_paper_size", "A4"))
        self.margins = tk.StringVar(value=settings.get("printer_margins", "normal"))
        self.logo = tk.StringVar(value=settings.get("printer_show_logo", "1"))
        self.header = tk.StringVar(value=settings.get("printer_header", "1"))
        self.footer = tk.StringVar(value=settings.get("printer_footer", "1"))
        self.contact = tk.StringVar(value=settings.get("printer_contact_details", "1"))
        self.tax = tk.StringVar(value=settings.get("printer_tax_details", "1"))
        self.copies = tk.StringVar(value=settings.get("printer_copies", "1"))
        self.workflow = tk.StringVar(value=settings.get("printer_default_workflow", "preview"))
        self.logo_path = tk.StringVar(value=settings.get("logo_path", ""))
        self.header_text = tk.StringVar(value=settings.get("footer_note", ""))
        self.device = tk.StringVar(value=settings.get("printer_default_device", ""))

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Printer Settings", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Paper, layout and what the invoice carries",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(10, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ui.Card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(left.inner, text="PAPER AND LAYOUT", style="Section.TLabel").pack(anchor="w")

        ttk.Label(left.inner, text="Paper size", style="Muted.TLabel").pack(anchor="w",
                                                                         pady=(10, 0))
        ttk.Combobox(left.inner, textvariable=self.paper, state="readonly", width=34,
                     values=list(PAPER_LABELS.values())).pack(anchor="w", pady=(2, 0))

        ttk.Label(left.inner, text="Margins", style="Muted.TLabel").pack(anchor="w",
                                                                       pady=(10, 0))
        ttk.Combobox(left.inner, textvariable=self.margins, state="readonly", width=34,
                     values=list(MARGIN_LABELS.values())).pack(anchor="w", pady=(2, 0))

        ttk.Label(left.inner, text="Copies per print", style="Muted.TLabel").pack(anchor="w",
                                                                                 pady=(10, 0))
        ttk.Combobox(left.inner, textvariable=self.copies, state="readonly", width=12,
                     values=["1", "2", "3", "4", "5"]).pack(anchor="w", pady=(2, 0))

        ttk.Label(left.inner, text="Default workflow", style="Muted.TLabel").pack(anchor="w",
                                                                                   pady=(10, 0))
        ttk.Combobox(left.inner, textvariable=self.workflow, state="readonly", width=34,
                     values=list(printing.WORKFLOWS.values())).pack(anchor="w", pady=(2, 0))

        ttk.Label(left.inner, text="Logo file", style="Muted.TLabel").pack(anchor="w",
                                                                          pady=(10, 0))
        logo_row = ttk.Frame(left.inner, style="Card.TFrame")
        logo_row.pack(fill="x", pady=(2, 0))
        ttk.Entry(logo_row, textvariable=self.logo_path).pack(side="left", fill="x", expand=True)
        ttk.Button(logo_row, text="Browse", style="Ghost.TButton",
                   command=self.browse_logo).pack(side="left", padx=(6, 0))

        ttk.Label(left.inner, text="Receipt footer", style="Muted.TLabel").pack(anchor="w",
                                                                               pady=(10, 0))
        ttk.Entry(left.inner, textvariable=self.header_text).pack(fill="x", pady=(2, 0))

        right = ui.Card(body)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right.inner, text="WHAT THE INVOICE CARRIES", style="Section.TLabel").pack(anchor="w")
        for label, variable, hint in (
            ("Hotel logo", self.logo, "Show the logo in the header."),
            ("Header block", self.header, "Hotel name, address and the document title."),
            ("Footer", self.footer, "Notes, signatures and the thank-you line."),
            ("Contact details", self.contact, "Phone and email under the hotel name."),
            ("Tax details", self.tax, "PAN, VAT number and the VAT rows."),
        ):
            row = tk.Frame(right.inner, bg=ui.CARD)
            row.pack(fill="x", pady=(8, 0))
            check = tk.Checkbutton(row, text=label, variable=variable, onvalue="1",
                                   offvalue="0", bg=ui.CARD, fg=ui.INK,
                                   activebackground=ui.CARD, font=(ui.FONT, 10),
                                   anchor="w")
            check.pack(side="left")
            tk.Label(row, text=hint, bg=ui.CARD, fg=ui.MUTED, font=(ui.FONT, 8),
                     wraplength=230, justify="left").pack(side="left", fill="x",
                                                           expand=True, padx=8)

        note = ui.Card(body)
        note.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(note.inner, text="HOW PRINTING WORKS HERE", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            note.inner,
            text=(
                "The app renders the invoice to a document with the paper size and "
                "margins you chose, and hands it to your operating system's print "
                "dialog. Choosing a physical printer, and printing without the "
                "dialog, depend on your browser, your operating system and your "
                "printer driver — not on this app. Test a print on your own "
                "machine before relying on it at the counter."
            ),
            style="CardMuted.TLabel",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Save settings", style="Primary.TButton",
                   command=self.save).pack(side="left")
        ttk.Button(actions, text="Print a test invoice", style="Gold.TButton",
                   command=self.test_print).pack(side="left", padx=6)
        ttk.Button(actions, text="Revert", style="Ghost.TButton",
                   command=self.reload).pack(side="left")

        self.summary = ttk.Label(self, text="", style="Muted.TLabel")
        self.summary.pack(anchor="w", pady=(8, 0))
        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(4, 0))

        self.reload()

    # ---------------------------------------------------------------- setup
    def reload(self) -> None:
        settings = db.get_settings(self.conn)
        self.paper.set(settings.get("printer_paper_size", "A4"))
        self.margins.set(settings.get("printer_margins", "normal"))
        self.logo.set(settings.get("printer_show_logo", "1"))
        self.header.set(settings.get("printer_header", "1"))
        self.footer.set(settings.get("printer_footer", "1"))
        self.contact.set(settings.get("printer_contact_details", "1"))
        self.tax.set(settings.get("printer_tax_details", "1"))
        self.copies.set(settings.get("printer_copies", "1"))
        self.workflow.set(settings.get("printer_default_workflow", "preview"))
        self.logo_path.set(settings.get("logo_path", ""))
        self.header_text.set(settings.get("footer_note", ""))
        self.device.set(settings.get("printer_default_device", ""))
        self._update_summary()

    def _update_summary(self) -> None:
        settings = self._collect()
        self.summary.configure(text="Current setup: " + printing.describe(settings))

    def _collect(self) -> dict:
        paper_key = next(
            (key for key, label in PAPER_LABELS.items() if label == self.paper.get()), "A4"
        )
        margin_key = next(
            (key for key, label in MARGIN_LABELS.items() if label == self.margins.get()),
            "normal",
        )
        workflow_key = next(
            (key for key, label in printing.WORKFLOWS.items() if label == self.workflow.get()),
            "preview",
        )
        return {
            "printer_paper_size": paper_key,
            "printer_margins": margin_key,
            "printer_show_logo": self.logo.get(),
            "printer_header": self.header.get(),
            "printer_footer": self.footer.get(),
            "printer_contact_details": self.contact.get(),
            "printer_tax_details": self.tax.get(),
            "printer_copies": self.copies.get(),
            "printer_default_workflow": workflow_key,
            "logo_path": self.logo_path.get().strip(),
            "footer_note": self.header_text.get().strip(),
            "printer_default_device": self.device.get().strip(),
        }

    def browse_logo(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose the hotel logo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.svg"), ("All files", "*.*")],
        )
        if path:
            self.logo_path.set(path)

    def save(self) -> None:
        try:
            permissions.require(self.app.user, "settings.printer", "change printer settings")
        except permissions.PermissionError_ as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return
        values = self._collect()
        db.save_settings(self.conn, values)
        db.log_audit(self.conn, "settings.printer", "settings", "printer",
                     ", ".join(f"{k}={v}" for k, v in values.items()),
                     self.app.user["user_id"], self.app.user["username"])
        self.app.refresh_settings()
        self._update_summary()
        ui.notify(self.status, "Printer settings saved.", ui.OK)

    def test_print(self) -> None:
        """Print a sample invoice so the hotel can check the paper size."""
        try:
            permissions.require(self.app.user, "settings.printer", "test the printer")
        except permissions.PermissionError_ as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return
        bill, lines = self.app.sample_invoice()
        if not bill:
            ui.notify(self.status, "There is no invoice to print yet — raise one first.",
                      ui.DANGER)
            return
        settings = self._collect()
        try:
            path = self.app.print_invoice(bill, lines, settings)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Test print failed", str(exc))
            return
        ui.notify(
            self.status,
            "A test invoice is open — use your browser's print button (Ctrl+P) "
            "to send it to the printer.",
            ui.OK,
        )
