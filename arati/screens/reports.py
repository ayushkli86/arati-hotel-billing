"""Reports Dashboard — the ten hotel reports, the filters that shape them and
the daily-closing reports the scheduler writes.

Every figure on this screen comes from the recorded transactions. The
summary cards are labelled with the measurement they show, so a collection
is never read as a sale, and the report table always prints the formula
its numbers were built from.
"""

from __future__ import annotations

import csv
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import business_time as bt
from .. import daily_report, db, permissions, report_pdf, reports, scheduler, ui

PRESETS = (
    "Today",
    "Yesterday",
    "This week",
    "This month",
    "Last 30 days",
    "Custom range",
)

REPORT_OPTIONS = [
    ("daily_sales", "1. Daily Sales Report"),
    ("monthly_sales", "2. Monthly Sales Report"),
    ("custom_range", "3. Custom Date Range Report"),
    ("payment_collection", "4. Payment Collection Report"),
    ("outstanding_invoices", "5. Outstanding Invoice Report"),
    ("refunds_adjustments", "6. Refund and Adjustment Report"),
    ("employee_sales", "7. Employee / Cashier Sales Report"),
    ("room_occupancy", "8. Room Occupancy Report"),
    ("room_revenue", "9. Room Revenue Report"),
    ("operations_summary", "10. Hotel Operations Summary"),
]

REPORT_KEYS = [key for key, _label in REPORT_OPTIONS]

CARD_FIELDS = (
    ("gross_sales", "Today's gross sales"),
    ("net_sales", "Today's net sales"),
    ("collected", "Today's payments collected"),
    ("cash_collected", "Today's cash collections"),
    ("outstanding", "Today's outstanding balances"),
    ("room_revenue", "Today's room revenue"),
    ("invoices", "Invoices issued"),
    ("occupied_rooms", "Occupied rooms"),
    ("available_rooms", "Available rooms"),
)


class ReportsScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.report: reports.Report | None = None

        self.preset = tk.StringVar(value="Today")
        self.start = tk.StringVar(value=bt.today().isoformat())
        self.end = tk.StringVar(value=bt.today().isoformat())
        self.report_key = tk.StringVar(value="daily_sales")
        self.employee = tk.StringVar(value="All")
        self.method = tk.StringVar(value="All")
        self.kind = tk.StringVar(value="All")
        self.room_no = tk.StringVar()
        self.invoice_no = tk.StringVar()

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Reports", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Sales, collections, occupancy and operations",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(10, 0))

        self.cards = ttk.Frame(self)
        self.cards.pack(fill="x", pady=(0, 10))
        self.card_labels: dict[str, ttk.Label] = {}
        for key, label in CARD_FIELDS:
            card = ui.Card(self.cards, padding=10)
            card.pack(side="left", fill="both", expand=True, padx=(0, 6))
            ttk.Label(card.inner, text=label.upper(), style="Section.TLabel").pack(anchor="w")
            value = ttk.Label(card.inner, text="—", style="Total.TLabel",
                              font=(ui.FONT, 13, "bold"))
            value.pack(anchor="w")
            self.card_labels[key] = value

        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=(0, 8))

        row1 = ttk.Frame(filters)
        row1.pack(fill="x", pady=(0, 6))
        ttk.Label(row1, text="Period", style="Muted.TLabel").pack(side="left", padx=(0, 4))
        preset_box = ttk.Combobox(row1, textvariable=self.preset, state="readonly",
                                  width=15, values=list(PRESETS))
        preset_box.pack(side="left")
        preset_box.bind("<<ComboboxSelected>>", lambda _e: self.apply_preset())
        ui.field(row1, "From", self.start, width=13, card=False).pack(side="left", padx=(10, 0))
        ui.field(row1, "To", self.end, width=13, card=False).pack(side="left", padx=8)
        ttk.Label(row1, text="Timezone", style="Muted.TLabel").pack(side="left", padx=(10, 4))
        self.zone_label = ttk.Label(row1, text=bt.DEFAULT_TIMEZONE, style="TLabel")
        self.zone_label.pack(side="left")

        row2 = ttk.Frame(filters)
        row2.pack(fill="x")
        ttk.Label(row2, text="Employee", style="Muted.TLabel").pack(side="left", padx=(0, 4))
        self.employee_box = ttk.Combobox(row2, textvariable=self.employee, state="readonly",
                                         width=16, values=["All"])
        self.employee_box.pack(side="left")
        ttk.Label(row2, text="Payment", style="Muted.TLabel").pack(side="left", padx=(10, 4))
        self.method_box = ttk.Combobox(row2, textvariable=self.method, state="readonly",
                                       width=15, values=["All"])
        self.method_box.pack(side="left")
        ttk.Label(row2, text="Type", style="Muted.TLabel").pack(side="left", padx=(10, 4))
        ttk.Combobox(row2, textvariable=self.kind, state="readonly", width=13,
                     values=["All", "Room", "Non-room", "Refund", "Adjustment"]).pack(side="left")
        ui.field(row2, "Room no.", self.room_no, width=10, card=False).pack(side="left", padx=(10, 0))
        ui.field(row2, "Invoice no.", self.invoice_no, width=13, card=False).pack(side="left", padx=8)
        ttk.Button(row2, text="Clear filters", style="Ghost.TButton",
                   command=self.clear_filters).pack(side="left", padx=6)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        report_tab = ttk.Frame(self.notebook)
        self.notebook.add(report_tab, text="  Report  ")

        bar = ttk.Frame(report_tab)
        bar.pack(fill="x", pady=(10, 8))
        ttk.Label(bar, text="Report", style="Muted.TLabel").pack(side="left", padx=(0, 4))
        ttk.Combobox(bar, textvariable=self.report_key, state="readonly", width=32,
                     values=[label for _key, label in REPORT_OPTIONS]).pack(side="left")
        ttk.Button(bar, text="Run report", style="Primary.TButton",
                   command=self.run).pack(side="left", padx=8)
        ttk.Button(bar, text="Export PDF", style="Ghost.TButton",
                   command=self.export_pdf).pack(side="left")
        ttk.Button(bar, text="Print report", style="Ghost.TButton",
                   command=self.print_report).pack(side="left", padx=6)
        ttk.Button(bar, text="Export CSV", style="Ghost.TButton",
                   command=self.export_csv).pack(side="left")

        self.report_title = ttk.Label(report_tab, text="", style="H2.TLabel")
        self.report_title.pack(anchor="w")
        self.report_meta = ttk.Label(report_tab, text="", style="Muted.TLabel")
        self.report_meta.pack(anchor="w", pady=(0, 6))

        table_card = ui.Card(report_tab)
        table_card.pack(fill="both", expand=True)
        wrap = ttk.Frame(table_card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = ui.table(wrap, [("col", "Report", 200)], height=14)
        self.tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.tree, wrap).pack(side="right", fill="y")
        self.tree.configure(columns=[])
        self.tree["show"] = "tree"

        self.formulas = ttk.Label(report_tab, text="", style="Muted.TLabel",
                                  wraplength=1100, justify="left")
        self.formulas.pack(anchor="w", pady=(8, 0))

        closing_tab = ttk.Frame(self.notebook)
        self.notebook.add(closing_tab, text="  Daily closing  ")
        self._build_closing_tab(closing_tab)

        runs_tab = ttk.Frame(self.notebook)
        self.notebook.add(runs_tab, text="  Scheduler  ")
        self._build_runs_tab(runs_tab)

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))

        self._load_filter_options()
        self.apply_preset()
        self.run()

    # ---------------------------------------------------------------- setup
    def _load_filter_options(self) -> None:
        staff = [
            row[0]
            for row in self.conn.execute(
                "SELECT DISTINCT prepared_by FROM bills WHERE prepared_by <> '' "
                "ORDER BY prepared_by"
            )
        ]
        self.employee_box.configure(values=["All", *staff])
        methods = [
            part.strip()
            for part in (self.app.settings.get("payment_methods") or "").split(",")
            if part.strip()
        ]
        self.method_box.configure(values=["All", *methods])
        self.zone_label.configure(text=self.app.settings.get("business_timezone", bt.DEFAULT_TIMEZONE))

    def apply_preset(self) -> None:
        preset = self.preset.get()
        today = bt.today()
        if preset == "Today":
            start = end = today
        elif preset == "Yesterday":
            start = end = today - timedelta(days=1)
        elif preset == "This week":
            start = today - timedelta(days=today.weekday())
            end = today
        elif preset == "This month":
            start = today.replace(day=1)
            end = today
        elif preset == "Last 30 days":
            start = today - timedelta(days=29)
            end = today
        else:
            return
        self.start.set(start.isoformat())
        self.end.set(end.isoformat())

    def clear_filters(self) -> None:
        self.employee.set("All")
        self.method.set("All")
        self.kind.set("All")
        self.room_no.set("")
        self.invoice_no.set("")
        self.run()

    def _filters(self) -> dict:
        return {
            "employee": self.employee.get(),
            "payment_method": self.method.get(),
            "transaction_type": self.kind.get(),
            "room_no": self.room_no.get().strip(),
            "invoice_no": self.invoice_no.get().strip(),
        }

    # ------------------------------------------------------------- running
    def run(self) -> None:
        if not ui.is_iso_date(self.start.get()) or not ui.is_iso_date(self.end.get()):
            ui.notify(self.status, "Dates must be YYYY-MM-DD.", ui.DANGER)
            return
        key = self.report_key.get()
        try:
            self.report = reports.build(self.conn, key, self.start.get(), self.end.get(),
                                        self._filters())
        except Exception as exc:  # noqa: BLE001 - show the problem, keep the screen
            ui.notify(self.status, f"Report failed: {exc}", ui.DANGER)
            return

        cards = reports.dashboard_cards(self.conn, self.start.get())
        for card_key, _label in CARD_FIELDS:
            value = cards.get(card_key, 0)
            if isinstance(value, int) and card_key in ("invoices", "occupied_rooms",
                                                       "available_rooms"):
                self.card_labels[card_key].configure(text=str(value))
            else:
                self.card_labels[card_key].configure(text=ui.money(value))

        self.report_title.configure(text=self.report.title)
        self.report_meta.configure(
            text=f"{self.report.subtitle} · {self.report.period} · "
                 f"Generated {self.report.generated_at}"
        )
        self._fill_table()
        if self.report.formulas:
            self.formulas.configure(
                text="How these figures are calculated:\n"
                + "\n".join(f"• {formula}" for formula in self.report.formulas)
            )
        else:
            self.formulas.configure(text="")
        ui.notify(self.status, f"{len(self.report.rows)} row(s) in {self.report.title}.", ui.MUTED)

    def _fill_table(self) -> None:
        report = self.report
        self.tree.configure(columns=[key for key, _l, _w in report.columns])
        for key, label, width in report.columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        self.tree.delete(*self.tree.get_children())
        if not report.rows:
            self.tree.insert("", "end", text=report.empty_message)
            return
        for row in report.rows:
            values = []
            for key, _label, _width in report.columns:
                value = row.get(key)
                if isinstance(value, float):
                    values.append(f"{value:,.2f}")
                elif value is None:
                    values.append("")
                else:
                    values.append(str(value))
            self.tree.insert("", "end", values=values)
        totals = []
        for key, _label, _width in report.columns:
            value = report.totals.get(key)
            if isinstance(value, float):
                totals.append(f"{value:,.2f}")
            elif isinstance(value, int):
                totals.append(str(value))
            elif value is None:
                totals.append("")
            else:
                totals.append(str(value))
        self.tree.insert("", "end", text="TOTAL", values=totals, open=False,
                         tags=("total",))

    # ------------------------------------------------------------- exports
    def export_csv(self) -> None:
        if not self.report:
            ui.notify(self.status, "Run a report first.", ui.DANGER)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"arati-{self.report.key}-{self.start.get()}_{self.end.get()}.csv",
        )
        if not path:
            return
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([label for _key, label, _w in self.report.columns])
            for row in self.report.rows:
                writer.writerow([row.get(key, "") for key, _l, _w in self.report.columns])
        ui.notify(self.status, f"Exported to {Path(path).name}", ui.OK)

    def export_pdf(self) -> None:
        if not self.report:
            ui.notify(self.status, "Run a report first.", ui.DANGER)
            return
        try:
            path = self.app.report_directory / (
                f"{self.report.key}-{self.start.get()}_{self.end.get()}.pdf"
            )
            report_pdf.build_report_pdf(path, self.report, self.app.settings)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export failed", str(exc))
            return
        self.app.open_pdf(path)
        ui.notify(self.status, f"Saved {path.name}", ui.OK)

    def print_report(self) -> None:
        if not self.report:
            ui.notify(self.status, "Run a report first.", ui.DANGER)
            return
        try:
            path = self.app.report_directory / (
                f"{self.report.key}-{self.start.get()}_{self.end.get()}.html"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                report_pdf.build_report_html(self.report, self.app.settings),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Print failed", str(exc))
            return
        self.app.open_in_browser(path)
        ui.notify(
            self.status,
            "The report is open in your browser — use the browser's print "
            "button (Ctrl+P) to send it to the printer.",
            ui.MUTED,
        )

    # --------------------------------------------------------- daily closing
    def _build_closing_tab(self, tab: ttk.Frame) -> None:
        header = ttk.Frame(tab)
        header.pack(fill="x", pady=(10, 8))
        ttk.Label(header, text="Daily Sales and Operations Reports",
                  style="H2.TLabel").pack(side="left")
        ttk.Label(header, text="Written automatically after midnight",
                  style="Muted.TLabel").pack(side="left", padx=12, pady=(6, 0))
        ttk.Button(header, text="Generate yesterday now", style="Ghost.TButton",
                   command=self.generate_now).pack(side="right")
        ttk.Button(header, text="Regenerate", style="Ghost.TButton",
                   command=self.regenerate).pack(side="right", padx=6)
        ttk.Button(header, text="Download PDF", style="Primary.TButton",
                   command=self.download_daily).pack(side="right")

        card = ui.Card(tab)
        card.pack(fill="both", expand=True)
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.daily_tree = ui.table(
            wrap,
            [("date", "Business date", 120), ("version", "Version", 70),
             ("status", "Status", 95), ("generated", "Generated at", 150),
             ("by", "By", 120), ("file", "PDF file", 260), ("error", "Error", 200)],
            height=13,
        )
        self.daily_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.daily_tree, wrap).pack(side="right", fill="y")

        self.closing_status = ui.status(tab)
        self.closing_status.pack(anchor="w", pady=(8, 0))
        self.reload_daily()

    def reload_daily(self) -> None:
        self.daily_tree.delete(*self.daily_tree.get_children())
        rows = daily_report.list_reports(self.conn)
        for row in rows:
            self.daily_tree.insert(
                "", "end", iid=str(row["report_id"]),
                values=(
                    row["business_date"], f"v{row['version']}", row["status"].title(),
                    row["generated_at"], row["generated_by"],
                    row["file_path"] or "—", row["error"] or "",
                ),
            )
        missing = scheduler.missing_report_days(self.conn)
        note = f"{len(rows)} report(s) on file."
        if missing:
            note += f" Missing for: {', '.join(missing)}."
        ui.notify(self.closing_status, note, ui.MUTED if not missing else ui.DANGER)

    def _selected_daily(self) -> str | None:
        selection = self.daily_tree.selection()
        if not selection:
            ui.notify(self.closing_status, "Select a report first.", ui.DANGER)
            return None
        return selection[0]

    def download_daily(self) -> None:
        report_id = self._selected_daily()
        if not report_id:
            return
        row = daily_report.get_report(self.conn, int(report_id))
        if not row or not row["file_path"] or not Path(row["file_path"]).exists():
            ui.notify(self.closing_status, "That report has no PDF on disk.", ui.DANGER)
            return
        self.app.open_pdf(Path(row["file_path"]))

    def regenerate(self) -> None:
        report_id = self._selected_daily()
        if not report_id:
            return
        try:
            permissions.require(self.app.user, "report.regenerate",
                                "regenerate a daily report")
        except permissions.PermissionError_ as exc:
            ui.notify(self.closing_status, str(exc), ui.DANGER)
            return
        row = daily_report.get_report(self.conn, int(report_id))
        if not row:
            return
        if not ui.ask(
            f"Regenerate the report for {row['business_date']}?\n"
            "The previous version is kept and marked as superseded."
        ):
            return
        result = scheduler.regenerate(
            self.conn,
            row["business_date"],
            self.app.report_directory,
            settings=self.app.settings,
            username=self.app.user["full_name"] or self.app.user["username"],
            user_id=self.app.user["user_id"],
        )
        self.reload_daily()
        if result["status"] == "generated":
            ui.notify(self.closing_status,
                      f"Regenerated as v{result['version']}.", ui.OK)
        else:
            ui.notify(self.closing_status,
                      "Regeneration failed: " + "; ".join(result.get("problems", [])),
                      ui.DANGER)

    def generate_now(self) -> None:
        try:
            permissions.require(self.app.user, "report.regenerate",
                                "generate a daily report")
        except permissions.PermissionError_ as exc:
            ui.notify(self.closing_status, str(exc), ui.DANGER)
            return
        yesterday = bt.previous_day(bt.today())
        result = daily_report.generate(
            self.conn,
            yesterday,
            self.app.report_directory,
            settings=self.app.settings,
            generated_by=self.app.user["full_name"] or self.app.user["username"],
            username=self.app.user["full_name"] or self.app.user["username"],
            user_id=self.app.user["user_id"],
        )
        self.reload_daily()
        if result["status"] == "generated":
            ui.notify(self.closing_status,
                      f"{yesterday} closed as v{result['version']}.", ui.OK)
        else:
            ui.notify(self.closing_status,
                      "Could not close the day: " + "; ".join(result.get("problems", [])),
                      ui.DANGER)

    # -------------------------------------------------------------- runs tab
    def _build_runs_tab(self, tab: ttk.Frame) -> None:
        header = ttk.Frame(tab)
        header.pack(fill="x", pady=(10, 8))
        ttk.Label(header, text="Scheduler history", style="H2.TLabel").pack(side="left")
        ttk.Label(header, text="Every attempt at the midnight job, successful or not",
                  style="Muted.TLabel").pack(side="left", padx=12, pady=(6, 0))
        ttk.Button(header, text="Refresh", style="Ghost.TButton",
                   command=self.reload_runs).pack(side="right")

        card = ui.Card(tab)
        card.pack(fill="both", expand=True)
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.runs_tree = ui.table(
            wrap,
            [("job", "Job", 130), ("date", "Business date", 120),
             ("started", "Started", 150), ("finished", "Finished", 150),
             ("status", "Status", 90), ("message", "Message", 380)],
            height=12,
        )
        self.runs_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.runs_tree, wrap).pack(side="right", fill="y")
        self.reload_runs()

    def reload_runs(self) -> None:
        self.runs_tree.delete(*self.runs_tree.get_children())
        for row in scheduler.list_runs(self.conn, 80):
            self.runs_tree.insert("", "end", values=(
                row["job_name"], row["business_date"] or "—", row["started_at"],
                row["finished_at"] or "—", row["status"].title(), row["message"] or "",
            ))
