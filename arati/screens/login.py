"""Premium sign-in screen for the Arati Hotel till.

The screen is split in two: a dark brand panel on the left carrying the
BilledIn logo lockup, the "Premium Billing Software" tag and the feature
list, and a light sign-in column on the right with rounded fields and a
rounded primary button.

Everything here is drawn with the Tk canvas, so the screen needs no image
assets and stays crisp at any window size.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from arati import db, ui

# ------------------------------------------------------------------ palette
PANEL_TOP = "#350C13"
PANEL_BOTTOM = "#6E1B26"
PANEL_SHEEN = "#7C2029"

GOLD = ui.GOLD
GOLD_LIGHT = "#E8D29A"
GOLD_DIM = "#B99C6E"

CREAM = "#FBF8F2"
CARD = ui.CARD
INK = ui.INK
MUTED = ui.MUTED
LINE = ui.LINE
BRAND = ui.BRAND
BRAND_DARK = ui.BRAND_DARK
BRAND_DEEP = "#4A121B"

DISPLAY = "Lato"
BODY = "Inter"

FEATURES = (
    "VAT-ready tax invoices and bill of supply",
    "Rooms, restaurant and event services on one bill",
    "80mm thermal receipt and A4 print in one click",
    "Runs fully offline — the till never needs internet",
)


def _blend(first: str, second: str, amount: float) -> str:
    """Blend two ``#rrggbb`` colours; ``amount`` 0 gives ``first``."""
    amount = max(0.0, min(1.0, amount))
    parts = []
    for offset in (1, 3, 5):
        a = int(first[offset:offset + 2], 16)
        b = int(second[offset:offset + 2], 16)
        parts.append(round(a + (b - a) * amount))
    return "#%02x%02x%02x" % tuple(parts)


def _rounded_fill(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float,
                  radius: float, color: str) -> list:
    """Fill a rounded rectangle and return the canvas items that make it."""
    radius = max(0.0, min(radius, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    if radius <= 0.5:
        return [canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")]
    piece = {"fill": color, "outline": ""}
    return [
        canvas.create_arc(x0, y0, x0 + 2 * radius, y0 + 2 * radius,
                          start=90, extent=90, style="pieslice", **piece),
        canvas.create_arc(x1 - 2 * radius, y0, x1, y0 + 2 * radius,
                          start=0, extent=90, style="pieslice", **piece),
        canvas.create_arc(x1 - 2 * radius, y1 - 2 * radius, x1, y1,
                          start=270, extent=90, style="pieslice", **piece),
        canvas.create_arc(x0, y1 - 2 * radius, x0 + 2 * radius, y1,
                          start=180, extent=90, style="pieslice", **piece),
        canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1, **piece),
        canvas.create_rectangle(x0, y0 + radius, x0 + radius, y1 - radius, **piece),
        canvas.create_rectangle(x1 - radius, y0 + radius, x1, y1 - radius, **piece),
    ]


class BrandPanel(tk.Canvas):
    """Left-hand brand panel: gradient, BilledIn logo lockup, feature list."""

    def __init__(self, master, hotel_name: str = "", hotel_address: str = ""):
        super().__init__(master, bg=PANEL_BOTTOM, highlightthickness=0, bd=0)
        self.hotel_name = hotel_name or "Arati Hotel"
        self.hotel_address = hotel_address
        self._display = tkfont.Font(family=DISPLAY, weight="bold")
        self._body = tkfont.Font(family=BODY)
        self._body_small = tkfont.Font(family=BODY, size=8)
        self._body_bold = tkfont.Font(family=BODY, size=9, weight="bold")
        self._mono = tkfont.Font(family=DISPLAY, weight="bold", size=22)
        self._wordmark = tkfont.Font(family=DISPLAY, weight="bold", size=26)
        self._tag = tkfont.Font(family=BODY, size=8, weight="bold")
        self.bind("<Configure>", self._redraw)

    # -- drawing ---------------------------------------------------------
    def _redraw(self, _event=None) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            return
        self.delete("all")
        self._draw_gradient(width, height)
        self._draw_motif(width, height)
        self._draw_logo(width)
        self._draw_headline(width, height)
        self._draw_features(width, height)
        self._draw_footer(width, height)

    def _draw_gradient(self, width: int, height: int) -> None:
        steps = 80
        for step in range(steps):
            top = height * step / steps
            bottom = height * (step + 1) / steps + 1
            self.create_rectangle(
                0, top, width, bottom,
                fill=_blend(PANEL_TOP, PANEL_BOTTOM, step / (steps - 1)),
                outline="",
            )
        self.create_polygon(
            0, 0, width * 0.62, 0, width * 0.18, height, 0, height,
            fill=PANEL_SHEEN, outline="",
        )

    def _draw_motif(self, width: int, height: int) -> None:
        """Faint outlined circles for depth behind the content."""
        self.create_oval(
            width * 0.52, height * 0.58, width * 1.25, height * 1.31,
            outline=_blend(PANEL_SHEEN, GOLD, 0.22), width=1,
        )
        self.create_oval(
            width * 0.70, height * 0.74, width * 1.05, height * 1.09,
            outline=_blend(PANEL_SHEEN, GOLD, 0.35), width=1,
        )

    def _draw_logo(self, width: int) -> None:
        pad = 64
        top = 58
        box = 58

        # Monogram: gold tile with a maroon "B" and a thin gold keyline.
        _rounded_fill(self, pad, top, pad + box, top + box, 16, GOLD)
        _rounded_fill(self, pad + 4, top + 4, pad + box - 4, top + box - 4, 13,
                      _blend(GOLD, "#000000", 0.12))
        self.create_text(
            pad + box / 2, top + box / 2 - 1, text="B", font=self._mono,
            fill=PANEL_TOP, anchor="center",
        )

        # Wordmark: "Billed" in cream, "In" in gold.
        text_x = pad + box + 20
        text_y = top + 6
        self.create_text(text_x, text_y, text="Billed", font=self._wordmark,
                         fill=CREAM, anchor="nw")
        billed_width = self._wordmark.measure("Billed")
        self.create_text(text_x + billed_width, text_y, text="In",
                         font=self._wordmark, fill=GOLD, anchor="nw")
        self.create_text(
            text_x + 2, top + 40, text="D E S K T O P   B I L L I N G   S U I T E",
            font=self._body_small, fill=GOLD_DIM, anchor="nw",
        )

        # "Premium Billing Software" tag.
        self._draw_tag(pad, top + box + 34)

    def _draw_tag(self, x: float, y: float) -> None:
        label = "PREMIUM BILLING SOFTWARE"
        pad_x = 16
        height = 30
        text_width = self._tag.measure(label)
        width = text_width + pad_x * 2 + 22
        _rounded_fill(self, x, y, x + width, y + height, height / 2,
                      _blend(PANEL_SHEEN, GOLD, 0.30))
        _rounded_fill(self, x + 1.5, y + 1.5, x + width - 1.5, y + height - 1.5,
                      (height - 3) / 2, _blend(PANEL_SHEEN, GOLD, 0.16))
        self.create_polygon(
            x + pad_x, y + height / 2 - 4.5, x + pad_x + 4.5, y + height / 2,
            x + pad_x, y + height / 2 + 4.5, x + pad_x - 4.5, y + height / 2,
            fill=GOLD, outline="",
        )
        self.create_text(
            x + pad_x + 12, y + height / 2, text=label, font=self._tag,
            fill=GOLD_LIGHT, anchor="w",
        )

    def _draw_headline(self, width: int, height: int) -> None:
        pad = 64
        top = 232
        self.create_text(pad, top, text=self.hotel_name.upper(), font=self._display,
                         fill=CREAM, anchor="nw")
        title_size = self._display.measure(self.hotel_name.upper())
        self.create_text(pad, top + 44, text=self.hotel_address, font=self._body,
                         fill=GOLD_LIGHT, anchor="nw")
        self.create_rectangle(pad, top + 76, pad + 54, top + 79, fill=GOLD, outline="")
        self.create_text(pad + 74, top + 74, text="Front desk till", font=self._body_small,
                         fill=GOLD_DIM, anchor="w")

    def _draw_features(self, width: int, height: int) -> None:
        pad = 64
        top = 348
        for line in FEATURES:
            _rounded_fill(self, pad + 1, top + 6, pad + 7, top + 12, 1.5, GOLD)
            self.create_text(pad + 22, top, text=line, font=self._body,
                             fill="#E7DCCB", anchor="nw")
            top += 34

    def _draw_footer(self, width: int, height: int) -> None:
        pad = 64
        base = height - 52
        self.create_line(pad, base - 26, width - pad, base - 26,
                         fill=_blend(PANEL_SHEEN, GOLD, 0.28))
        self.create_text(pad, base, text="Version 1.0  ·  Offline desktop till",
                         font=self._body_small, fill=GOLD_DIM, anchor="nw")
        self.create_text(width - pad, base, text="Built on BilledIn",
                         font=self._body_small, fill=GOLD_DIM, anchor="ne")


class RoundedEntry(tk.Frame):
    """A field with a rounded outline that lights up gold when focused."""

    def __init__(self, master, variable: tk.StringVar | None = None, show: str = ""):
        super().__init__(master, bg=CARD)
        self.canvas = tk.Canvas(self, bg=CARD, highlightthickness=0, bd=0, height=48)
        self.canvas.pack(fill="both", expand=True)
        self.entry = tk.Entry(
            self, textvariable=variable, show=show, bd=0, relief="flat",
            bg=CARD, fg=INK, highlightthickness=0, insertbackground=BRAND,
            font=(BODY, 11),
        )
        self.entry.place(x=18, rely=0.5, anchor="w")
        self.entry.bind("<FocusIn>", lambda _e: self._paint(GOLD))
        self.entry.bind("<FocusOut>", lambda _e: self._paint(LINE))
        self.canvas.bind("<Configure>", lambda _e: self._paint(self._border))
        self._border = LINE

    def _paint(self, border: str) -> None:
        self._border = border
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        self.canvas.delete("all")
        _rounded_fill(self.canvas, 0.5, 0.5, width - 0.5, height - 0.5, 10, border)
        _rounded_fill(self.canvas, 1.5, 1.5, width - 1.5, height - 1.5, 9, CARD)


class RoundedButton(tk.Canvas):
    """The primary sign-in button, drawn as a rounded maroon block."""

    def __init__(self, master, text: str, command=None, width: int = 420,
                 height: int = 50):
        super().__init__(master, bg=CARD, highlightthickness=0, bd=0,
                         width=width, height=height, cursor="hand2")
        self._text = text
        self._command = command
        self._fill = BRAND
        self._label = CREAM
        self.bind("<Configure>", lambda _e: self._paint())
        self.bind("<Enter>", lambda _e: self._set(BRAND_DARK, CREAM))
        self.bind("<Leave>", lambda _e: self._set(BRAND, CREAM))
        self.bind("<ButtonPress-1>", lambda _e: self._set(BRAND_DEEP, GOLD_LIGHT))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Return>", lambda _e: self._click(e))
        self.bind("<FocusIn>", lambda _e: self._paint())

    def _set(self, fill: str, label: str) -> None:
        self._fill = fill
        self._label = label
        self._paint()

    def _paint(self) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            return
        self.delete("all")
        _rounded_fill(self, 0.5, 0.5, width - 0.5, height - 0.5, 12, self._fill)
        self.create_text(
            width / 2, height / 2, text=self._text, font=(BODY, 11, "bold"),
            fill=self._label, anchor="center",
        )

    def _click(self, event) -> None:
        self._set(BRAND, CREAM)
        if self._command:
            self._command()


class LoginFrame(tk.Frame):
    """The whole sign-in screen: brand panel plus the sign-in column."""

    def __init__(self, master, app):
        super().__init__(master, bg=CREAM)
        self.app = app
        self.username = tk.StringVar()
        self.password = tk.StringVar()

        self.grid_columnconfigure(0, weight=2, minsize=470)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)

        settings = getattr(app, "settings", {}) or {}
        self.panel = BrandPanel(
            self,
            hotel_name=settings.get("hotel_name", "Arati Hotel"),
            hotel_address=settings.get("hotel_address1", ""),
        )
        self.panel.grid(row=0, column=0, sticky="nsew")

        self.form = tk.Frame(self, bg=CREAM)
        self.form.grid(row=0, column=1, sticky="nsew")
        self._build_form()

        self.bind_all("<Return>", lambda _e: self.submit())
        self.after(150, self.focus_first)

    # -- form ------------------------------------------------------------
    def _build_form(self) -> None:
        column = tk.Frame(self.form, bg=CREAM)
        column.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(column, text="A R A T I   H O T E L", background=CREAM,
                  foreground=MUTED, font=(BODY, 8, "bold")).pack()
        ttk.Label(column, text="Welcome back", background=CREAM, foreground=INK,
                  font=(DISPLAY, 20, "bold")).pack(pady=(6, 2))
        ttk.Label(column, text="Sign in to open the till", background=CREAM,
                  foreground=MUTED, font=(BODY, 10)).pack()

        rule = tk.Canvas(column, height=10, width=60, bg=CREAM,
                         highlightthickness=0, bd=0)
        rule.pack(pady=(14, 22))
        rule.create_rectangle(0, 3, 60, 5, fill=GOLD, outline="")

        self._field_label(column, "USERNAME")
        self.username_field = RoundedEntry(column, variable=self.username)
        self.username_field.pack(fill="x", pady=(6, 0))

        self._field_label(column, "PASSWORD")
        self.password_field = RoundedEntry(column, variable=self.password,
                                            show="•")
        self.password_field.pack(fill="x", pady=(6, 0))

        self.error = ttk.Label(column, text="", background=CREAM,
                               foreground=ui.DANGER, font=(BODY, 9))
        self.error.pack(anchor="w", pady=(10, 0))

        self.button = RoundedButton(column, "Sign in", command=self.submit,
                                    width=420, height=50)
        self.button.pack(fill="x", pady=(18, 0))

        users = db.list_users(self.app.conn)
        if len(users) == 1 and users[0]["username"] == "admin":
            ttk.Label(column, text="First run  ·  admin / arat123",
                      background=CREAM, foreground=MUTED,
                      font=(BODY, 9)).pack(pady=(14, 0))

        ttk.Label(column, text="Works offline  ·  Your data stays on this computer",
                  background=CREAM, foreground=MUTED,
                  font=(BODY, 8)).pack(pady=(26, 0))

    @staticmethod
    def _field_label(master, text: str) -> None:
        ttk.Label(master, text=text, background=CREAM, foreground=MUTED,
                  font=(BODY, 8, "bold")).pack(anchor="w")

    # -- behaviour -------------------------------------------------------
    def focus_first(self) -> None:
        self.username_field.entry.focus_set()

    def submit(self) -> None:
        user = db.authenticate(self.app.conn, self.username.get(),
                               self.password.get())
        if not user:
            self.error.configure(text="Wrong username or password.")
            self.password.set("")
            self.password_field.entry.focus_set()
            return
        self.unbind_all("<Return>")
        self.app.sign_in(user)
