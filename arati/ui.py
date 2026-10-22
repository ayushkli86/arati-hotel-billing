"""Shared Tkinter theme and widgets for the Arati Hotel billing app."""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

BRAND = "#7A1F2B"
BRAND_DARK = "#5A1620"
GOLD = "#B8912F"
BG = "#F6F2EA"
CARD = "#FFFFFF"
INK = "#241C17"
MUTED = "#746A5E"
LINE = "#E2DACA"
OK = "#1F7A4D"
DANGER = "#A3232B"

FONT = "DejaVu Sans"


def money(value: float) -> str:
    return f"NPR {float(value or 0):,.2f}"


def today_iso() -> str:
    return date.today().isoformat()


def tomorrow_iso() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def apply_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=BG)
    style.configure(".", font=(FONT, 10), background=BG, foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD, relief="flat")
    style.configure("Sidebar.TFrame", background=BRAND_DARK)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Card.TLabel", background=CARD, foreground=INK)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
    style.configure("H1.TLabel", background=BG, foreground=BRAND,
                    font=(FONT, 22, "bold"))
    style.configure("H2.TLabel", background=BG, foreground=INK,
                    font=(FONT, 14, "bold"))
    style.configure("Section.TLabel", background=CARD, foreground=MUTED,
                    font=(FONT, 8, "bold"))
    style.configure("Total.TLabel", background=CARD, foreground=BRAND,
                    font=(FONT, 20, "bold"))
    style.configure("SidebarTitle.TLabel", background=BRAND_DARK, foreground="white",
                    font=(FONT, 15, "bold"))
    style.configure("SidebarSub.TLabel", background=BRAND_DARK, foreground="#D9C7A3",
                    font=(FONT, 8))
    style.configure("Nav.TButton", background=BRAND_DARK, foreground="#EADFC8",
                    borderwidth=0, padding=(16, 11), anchor="w",
                    font=(FONT, 10))
    style.map("Nav.TButton",
              background=[("active", BRAND), ("selected", BRAND)],
              foreground=[("active", "white")])
    style.configure("NavActive.TButton", background=BRAND, foreground="white",
                    borderwidth=0, padding=(16, 11), anchor="w",
                    font=(FONT, 10, "bold"))

    style.configure("TButton", padding=(12, 7), font=(FONT, 9))
    style.configure("Primary.TButton", background=BRAND, foreground="white",
                    borderwidth=0, padding=(14, 9), font=(FONT, 10, "bold"))
    style.map("Primary.TButton",
              background=[("active", BRAND_DARK), ("disabled", "#C9BDB0")])
    style.configure("Gold.TButton", background=GOLD, foreground="#2B1D07",
                    borderwidth=0, padding=(14, 9), font=(FONT, 10, "bold"))
    style.map("Gold.TButton", background=[("active", "#A07E24")])
    style.configure("Ghost.TButton", background=CARD, foreground=BRAND,
                    borderwidth=1, padding=(10, 6))
    style.map("Ghost.TButton", background=[("active", "#F1E9DC")])
    style.configure("Danger.TButton", background="#FBEBEB", foreground=DANGER,
                    borderwidth=0, padding=(10, 6))

    style.configure("TEntry", fieldbackground="white", bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, padding=6)
    style.configure("TCombobox", fieldbackground="white", padding=5)

    style.configure("Treeview", background=CARD, fieldbackground=CARD,
                    foreground=INK, rowheight=27, borderwidth=0)
    style.configure("Treeview.Heading", background="#EFE7D8", foreground=BRAND_DARK,
                    font=(FONT, 9, "bold"), relief="flat", padding=6)
    style.map("Treeview", background=[("selected", BRAND)],
              foreground=[("selected", "white")])
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(14, 8), font=(FONT, 9, "bold"),
                    background="#EDE5D6", foreground=MUTED)
    style.map("TNotebook.Tab",
              background=[("selected", CARD)],
              foreground=[("selected", BRAND)])
    style.configure("TSeparator", background=LINE)


class Card(ttk.Frame):
    def __init__(self, master, padding=14, **kwargs):
        super().__init__(master, style="Card.TFrame", **kwargs)
        self.inner = ttk.Frame(self, style="Card.TFrame")
        self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)


def field(master, label: str, variable: tk.StringVar, width: int = 24,
          card: bool = True, show: str | None = None) -> ttk.Frame:
    row = ttk.Frame(master, style="Card.TFrame" if card else "TFrame")
    style = "CardMuted.TLabel" if card else "Muted.TLabel"
    ttk.Label(row, text=label.upper(), style=style).pack(anchor="w")
    entry = ttk.Entry(row, textvariable=variable, width=width, show=show or "")
    entry.pack(fill="x", pady=(2, 0))
    row.entry = entry
    return row


def table(master, columns: list[tuple[str, str, int]], height: int = 12,
          selectmode: str = "browse") -> ttk.Treeview:
    """columns: list of (key, heading, width)."""
    tree = ttk.Treeview(
        master, columns=[c[0] for c in columns], show="headings",
        height=height, selectmode=selectmode,
    )
    for key, heading, width in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor="w", stretch=key in ("name", "description"))
    return tree


def scroll(tree: ttk.Treeview, master) -> ttk.Scrollbar:
    bar = ttk.Scrollbar(master, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    return bar


def status(master) -> ttk.Label:
    label = ttk.Label(master, text="", style="Muted.TLabel")
    return label


def notify(label: ttk.Label, text: str, colour: str = MUTED, ms: int = 6000) -> None:
    label.configure(text=text, foreground=colour)
    label.after(ms, lambda: label.configure(text=""))


def is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def ask(message: str, title: str = "Confirm") -> bool:
    return messagebox.askyesno(title, message)
