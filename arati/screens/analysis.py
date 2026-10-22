"""Sales Analysis — the trends, breakdowns and comparisons behind the numbers.

Every chart is drawn from the series the analysis engine computed out of the
database; there are no decorative charts and no hardcoded production
figures. Each metric carries the formula it was calculated with, so a
number on a card can always be traced back to the rows behind it.
"""

from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from tkinter import ttk

from .. import analysis, business_time as bt, db, permissions, ui

BUCKETS = ("day", "week", "month")

COLOUR_SALES = "#7A1F2B"
COLOUR_COLLECTIONS = "#B8912F"
COLOUR_NEUTRAL = "#3F6F8F"
COLOUR_GRID = "#E2DACA"


class AnalysisScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.result: dict = {}

        self.start = tk.StringVar(value=bt.today().isoformat())
        self.end = tk.StringVar(value=bt.today().isoformat())
        self.bucket = tk.StringVar(value="day")
        self.compare = tk.BooleanVar(value=False)
        self.compare_start = tk.StringVar()
        self.compare_end = tk.StringVar()

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Sales Analysis", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Trends, breakdowns and period comparison",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(10, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        ui.field(bar, "From", self.start, width=13, card=False).pack(side="left")
        ui.field(bar, "To", self.end, width=13, card=False).pack(side="left", padx=8)
        ttk.Label(bar, text="Bucket", style="Muted.TLabel").pack(side="left", padx=(10, 4))
        ttk.Combobox(bar, textvariable=self.bucket, state="readonly", width=8,
                     values=list(BUCKETS)).pack(side="left")
        ttk.Button(bar, text="Analyse", style="Primary.TButton",
                   command=self.run).pack(side="left", padx=8)
        ttk.Checkbutton(bar, text="Compare with an earlier period", variable=self.compare,
                        command=self.toggle_compare).pack(side="left")

        self.compare_bar = ttk.Frame(self)
        self.compare_bar.pack(fill="x", pady=(0, 10))
        ui.field(self.compare_bar, "Compare from", self.compare_start, width=13,
                 card=False).pack(side="left")
        ui.field(self.compare_bar, "Compare to", self.compare_end, width=13,
                 card=False).pack(side="left", padx=8)
        self.compare_bar.pack_forget()

        self.metrics = ttk.Frame(self)
        self.metrics.pack(fill="x", pady=(0, 10))

        charts = ttk.Frame(self)
        charts.pack(fill="both", expand=True)
        charts.columnconfigure(0, weight=1)
        charts.columnconfigure(1, weight=1)
        charts.rowconfigure(0, weight=1)
        charts.rowconfigure(1, weight=1)

        self.trend_canvas = _chart_canvas(charts)
        self.trend_canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        self.category_canvas = _chart_canvas(charts)
        self.category_canvas.grid(row=0, column=1, sticky="nsew", padx=(0, 0), pady=(0, 6))
        self.method_canvas = _chart_canvas(charts)
        self.method_canvas.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(6, 0))
        self.room_canvas = _chart_canvas(charts)
        self.room_canvas.grid(row=1, column=1, sticky="nsew", padx=(0, 0), pady=(6, 0))

        self.comparison_frame: ttk.Frame | None = None
        self.formulas = ttk.Label(self, text="", style="Muted.TLabel",
                                  wraplength=1100, justify="left")
        self.formulas.pack(anchor="w", pady=(10, 0))
        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(6, 0))

        self.run()

    # ---------------------------------------------------------------- setup
    def toggle_compare(self) -> None:
        if self.compare.get():
            end = bt.today()
            self.compare_start.set((end - timedelta(days=7)).isoformat())
            self.compare_end.set(end.isoformat())
            self.compare_bar.pack(fill="x", pady=(0, 10), before=self.metrics)
        else:
            self.compare_bar.pack_forget()
            if self.comparison_frame is not None:
                self.comparison_frame.destroy()
                self.comparison_frame = None

    def run(self) -> None:
        if not ui.is_iso_date(self.start.get()) or not ui.is_iso_date(self.end.get()):
            ui.notify(self.status, "Dates must be YYYY-MM-DD.", ui.DANGER)
            return
        comparison = None
        if self.compare.get():
            if not ui.is_iso_date(self.compare_start.get()) or not ui.is_iso_date(
                self.compare_end.get()
            ):
                ui.notify(self.status, "Comparison dates must be YYYY-MM-DD.", ui.DANGER)
                return
            comparison = (self.compare_start.get(), self.compare_end.get())

        self.result = analysis.full_analysis(
            self.conn, self.start.get(), self.end.get(), self.bucket.get(), comparison
        )
        self._draw_metrics()
        self._draw_charts()
        self._draw_comparison()
        self._draw_formulas()
        ui.notify(self.status, "Analysis updated.", ui.MUTED)

    # --------------------------------------------------------------- drawing
    def _draw_metrics(self) -> None:
        for child in self.metrics.winfo_children():
            child.destroy()
        metrics = self.result["metrics"]
        for metric in metrics[:10]:
            card = ui.Card(self.metrics, padding=10)
            card.pack(side="left", fill="both", expand=True, padx=(0, 6))
            ttk.Label(card.inner, text=metric["label"].upper(),
                      style="Section.TLabel").pack(anchor="w")
            if metric["unit"] == "percent":
                text = f"{metric['value']:,.2f}%"
            elif metric["unit"] == "count":
                text = f"{metric['value']:,.0f}"
            else:
                text = ui.money(metric["value"])
            ttk.Label(card.inner, text=text, style="Total.TLabel",
                      font=(ui.FONT, 13, "bold")).pack(anchor="w")
            if metric["formula"]:
                ttk.Label(card.inner, text=metric["formula"], style="CardMuted.TLabel",
                          wraplength=180, justify="left").pack(anchor="w", pady=(2, 0))

    def _series(self, key: str) -> dict:
        for series in self.result["series"]:
            if series["key"] == key:
                return series
        return {"points": [], "label": key, "total": 0.0}

    def _draw_charts(self) -> None:
        sales = self._series(f"sales_{self.bucket.get()}")
        collections = self._series(f"collections_{self.bucket.get()}")
        _draw_grouped_bars(
            self.trend_canvas,
            "Sales and collections by " + self.bucket.get(),
            sales["points"],
            collections["points"],
            (COLOUR_SALES, COLOUR_COLLECTIONS),
        )
        _draw_bars(self.category_canvas, "Revenue by category",
                   self._series("revenue_by_category")["points"], COLOUR_SALES)
        _draw_bars(self.method_canvas, "Collections by payment method",
                   self._series("revenue_by_method")["points"], COLOUR_COLLECTIONS)
        _draw_bars(self.room_canvas, "Revenue by room",
                   self._series("revenue_by_room")["points"], COLOUR_NEUTRAL)

    def _draw_comparison(self) -> None:
        if self.comparison_frame is not None:
            self.comparison_frame.destroy()
            self.comparison_frame = None
        comparison = self.result.get("comparison")
        if not comparison:
            return
        self.comparison_frame = ttk.Frame(self)
        self.comparison_frame.pack(fill="x", pady=(10, 0), before=self.formulas)

        header = ttk.Frame(self.comparison_frame)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Period comparison", style="H2.TLabel").pack(side="left")
        ttk.Label(
            header,
            text=f"{comparison['current_period'][0]}–{comparison['current_period'][1]} "
                 f"vs {comparison['previous_period'][0]}–{comparison['previous_period'][1]}"
                 + ("" if comparison["same_length"]
                    else "  (the periods are not the same length)"),
            style="Muted.TLabel",
        ).pack(side="left", padx=12, pady=(6, 0))

        card = ui.Card(self.comparison_frame)
        card.pack(fill="x")
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        tree = ui.table(
            wrap,
            [("metric", "Measure", 230), ("current", "This period", 130),
             ("previous", "Earlier period", 130), ("change", "Change", 110)],
            height=8,
        )
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        for row in comparison["comparisons"]:
            if row["unit"] == "percent":
                current = f"{row['current']:,.2f}%"
                previous = f"{row['previous']:,.2f}%"
            elif row["unit"] == "count":
                current = f"{row['current']:,.0f}"
                previous = f"{row['previous']:,.0f}"
            else:
                current = ui.money(row["current"])
                previous = ui.money(row["previous"])
            change = "—" if row["change"] is None else f"{row['change']:+.2f}%"
            tree.insert("", "end", values=(row["label"], current, previous, change))

    def _draw_formulas(self) -> None:
        lines = [
            "How these figures are calculated:",
        ]
        for metric in self.result["metrics"]:
            if metric["formula"]:
                lines.append(f"• {metric['label']}: {metric['formula']}")
        for series in self.result["series"]:
            if series["formula"]:
                lines.append(f"• {series['label']}: {series['formula']}")
        self.formulas.configure(text="\n".join(lines))


# --------------------------------------------------------------------------- #
# charts
# --------------------------------------------------------------------------- #
def _chart_canvas(parent) -> tk.Canvas:
    frame = ui.Card(parent, padding=10)
    canvas = tk.Canvas(frame.inner, bg=ui.CARD, highlightthickness=0, height=190)
    canvas.pack(fill="both", expand=True)
    canvas.chart_frame = frame
    return canvas


def _draw_bars(canvas: tk.Canvas, title: str, points: list, colour: str) -> None:
    """A horizontal bar chart. Empty data is stated, not left blank."""
    canvas.delete("all")
    width = max(canvas.winfo_width(), 260)
    height = max(canvas.winfo_height(), 170)
    canvas.create_text(6, 4, anchor="nw", text=title, fill=ui.INK,
                       font=(ui.FONT, 9, "bold"))
    if not points:
        canvas.create_text(width / 2, height / 2, text="No transactions recorded",
                           fill=ui.MUTED, font=(ui.FONT, 9))
        return

    top = 26
    bottom = height - 18
    label_width = 118
    plot_width = max(40, width - label_width - 70)
    largest = max((abs(value) for _label, value in points), default=0) or 1
    usable = max(1, bottom - top)
    slot = usable / len(points)
    bar_height = max(6, min(20, slot - 6))

    for index, (label, value) in enumerate(points):
        y = top + index * slot
        bar = abs(value) / largest * plot_width
        canvas.create_text(6, y + bar_height / 2, anchor="w", text=str(label)[:22],
                           fill=ui.MUTED, font=(ui.FONT, 8))
        canvas.create_rectangle(label_width, y, label_width + max(bar, 1),
                                y + bar_height, fill=colour, outline="")
        canvas.create_text(label_width + bar + 6, y + bar_height / 2, anchor="w",
                           text=f"{value:,.0f}", fill=ui.INK, font=(ui.FONT, 8))


def _draw_grouped_bars(
    canvas: tk.Canvas,
    title: str,
    first: list,
    second: list,
    colours: tuple[str, str],
) -> None:
    """Two series side by side over the same buckets."""
    canvas.delete("all")
    width = max(canvas.winfo_width(), 260)
    height = max(canvas.winfo_height(), 170)
    canvas.create_text(6, 4, anchor="nw", text=title, fill=ui.INK,
                       font=(ui.FONT, 9, "bold"))

    labels = [label for label, _v in first] or [label for label, _v in second]
    if not labels:
        canvas.create_text(width / 2, height / 2, text="No transactions recorded",
                           fill=ui.MUTED, font=(ui.FONT, 9))
        return

    lookup_first = dict(first)
    lookup_second = dict(second)
    values = [abs(lookup_first.get(label, 0)) for label in labels]
    values += [abs(lookup_second.get(label, 0)) for label in labels]
    largest = max(values, default=0) or 1

    top = 30
    bottom = height - 26
    plot_width = max(40, width - 60)
    slot = max(1, (bottom - top) / len(labels))
    bar_width = max(3, min(16, slot / 2.6))
    baseline = bottom

    canvas.create_line(40, baseline, width - 10, baseline, fill=COLOUR_GRID)
    for index, label in enumerate(labels):
        centre = 45 + index * (plot_width / len(labels))
        for offset, value, colour in (
            (-bar_width, lookup_first.get(label, 0), colours[0]),
            (0, lookup_second.get(label, 0), colours[1]),
        ):
            height_of = abs(value) / largest * (baseline - top)
            canvas.create_rectangle(centre + offset, baseline - height_of,
                                    centre + offset + bar_width, baseline,
                                    fill=colour, outline="")
        canvas.create_text(centre, baseline + 6, anchor="n", text=str(label)[-11:],
                           fill=ui.MUTED, font=(ui.FONT, 7))

    legend_y = 14
    for index, (name, colour) in enumerate(zip(("Sales", "Collections"), colours)):
        x = width - 190 + index * 90
        canvas.create_rectangle(x, legend_y, x + 10, legend_y + 8, fill=colour, outline="")
        canvas.create_text(x + 14, legend_y + 4, anchor="w", text=name, fill=ui.MUTED,
                           font=(ui.FONT, 8))
