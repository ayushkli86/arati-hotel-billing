"""Room Management — the 25-room board and the front-desk operations.

Every card in the grid is drawn from the database, not from a hardcoded
list: the room inventory, the reservation, the stay and the housekeeping
state are read live, so what the front desk sees is what the reports count.

The three kinds of state stay separate, exactly as the database keeps them:
a room can be *reserved*, *occupied* and *needs cleaning* at the same time,
and a dirty room is never offered to a new guest.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from .. import db, permissions, rooms, ui
from ..money import BILL_TYPE_LABELS

STATUS_COLOURS = {
    rooms.STATUS_AVAILABLE: "#1F7A4D",
    rooms.STATUS_RESERVED: "#B8912F",
    rooms.STATUS_OCCUPIED: "#7A1F2B",
    rooms.STATUS_NEEDS_CLEANING: "#8A5A00",
    rooms.STATUS_UNDER_MAINTENANCE: "#5A5A5A",
}

HOUSEKEEPING_LABELS = {
    "clean": "Ready",
    "needs_cleaning": "Needs cleaning",
    "maintenance": "Under maintenance",
}

CHARGE_CATEGORIES = ("food", "service", "other")


class RoomsScreen(ttk.Frame):
    """The room board."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.search = tk.StringVar()
        self.status_filter = tk.StringVar(value="All")
        self.cards: list[tk.Frame] = []
        self.selected_room: str | None = None

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Room Management", style="H1.TLabel").pack(side="left")
        self.subtitle = ttk.Label(
            header, text="25 rooms · front desk board", style="Muted.TLabel"
        )
        self.subtitle.pack(side="left", padx=14, pady=(10, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        entry = ttk.Entry(bar, textvariable=self.search, width=26)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _e: self.reload())
        ttk.Label(bar, text="Status", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        filter_box = ttk.Combobox(
            bar,
            textvariable=self.status_filter,
            state="readonly",
            width=18,
            values=["All", rooms.STATUS_AVAILABLE, rooms.STATUS_RESERVED, rooms.STATUS_OCCUPIED,
                    rooms.STATUS_NEEDS_CLEANING, rooms.STATUS_UNDER_MAINTENANCE],
        )
        filter_box.pack(side="left")
        filter_box.bind("<<ComboboxSelected>>", lambda _e: self.reload())

        ttk.Button(bar, text="Reserve", style="Ghost.TButton",
                   command=self.reserve).pack(side="right")
        ttk.Button(bar, text="Check in", style="Ghost.TButton",
                   command=self.check_in).pack(side="right", padx=6)
        ttk.Button(bar, text="Check out", style="Primary.TButton",
                   command=self.check_out).pack(side="right")
        ttk.Button(bar, text="Add charge", style="Ghost.TButton",
                   command=self.add_charge).pack(side="right", padx=6)
        ttk.Button(bar, text="Extend stay", style="Ghost.TButton",
                   command=self.extend_stay).pack(side="right")
        ttk.Button(bar, text="History", style="Ghost.TButton",
                   command=self.show_history).pack(side="right", padx=6)
        ttk.Button(bar, text="Room rates", style="Ghost.TButton",
                   command=self.set_rate).pack(side="right")
        ttk.Button(bar, text="Housekeeping", style="Ghost.TButton",
                   command=self.housekeeping).pack(side="right", padx=6)
        ttk.Button(bar, text="Room list", style="Ghost.TButton",
                   command=self.manage_inventory).pack(side="right")

        self.counts = ttk.Frame(self)
        self.counts.pack(fill="x", pady=(0, 8))

        board = tk.Frame(self, bg=ui.BG)
        board.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(board, bg=ui.BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(board, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.grid_frame = tk.Frame(self.canvas, bg=ui.BG)
        self._grid_window = self.canvas.create_window(
            (0, 0), window=self.grid_frame, anchor="nw"
        )
        self.grid_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>", lambda _e: self._relayout(self.canvas.winfo_width())
        )
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))

        self.reload()

    # ----------------------------------------------------------------- load
    def reload(self) -> None:
        term = self.search.get().strip().lower()
        wanted = self.status_filter.get()
        rows = rooms.list_rooms(self.conn)
        self.all_rooms = rows
        shown = []
        for room in rows:
            if wanted != "All" and room["status"] != wanted:
                continue
            if term:
                haystack = " ".join(
                    str(room.get(key) or "")
                    for key in ("room_no", "guest_name", "guest_phone", "room_type")
                ).lower()
                if term not in haystack:
                    continue
            shown.append(room)

        self._draw_counters(rows)
        self._draw_cards(shown)
        ui.notify(
            self.status,
            f"{len(shown)} of {len(rows)} rooms shown · "
            f"{sum(1 for r in rows if r['status'] == rooms.STATUS_OCCUPIED)} occupied",
            ui.MUTED,
        )

    def _draw_counters(self, rows: list[dict]) -> None:
        for child in self.counts.winfo_children():
            child.destroy()
        counts: dict[str, int] = {}
        for room in rows:
            counts[room["status"]] = counts.get(room["status"], 0) + 1
        for status in (
            rooms.STATUS_AVAILABLE,
            rooms.STATUS_RESERVED,
            rooms.STATUS_OCCUPIED,
            rooms.STATUS_NEEDS_CLEANING,
            rooms.STATUS_UNDER_MAINTENANCE,
        ):
            card = tk.Frame(self.counts, bg=ui.CARD, highlightthickness=1,
                            highlightbackground=ui.LINE)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(
                card, text=status.upper(), bg=ui.CARD, fg=ui.MUTED,
                font=(ui.FONT, 8, "bold"),
            ).pack(anchor="w", padx=12, pady=(8, 0))
            tk.Label(
                card, text=str(counts.get(status, 0)), bg=ui.CARD,
                fg=STATUS_COLOURS.get(status, ui.INK), font=(ui.FONT, 18, "bold"),
            ).pack(anchor="w", padx=12, pady=(0, 8))

    def _relayout(self, width: int) -> None:
        if width < 100:
            return
        columns = max(1, min(5, width // 300))
        self.columns = columns
        for index, card in enumerate(self.cards):
            card.grid(row=index // columns, column=index % columns,
                      padx=(0, 10), pady=(0, 10), sticky="nsew")
        for column in range(5):
            self.grid_frame.columnconfigure(column, weight=1 if column < columns else 0)

    def _draw_cards(self, rows: list[dict]) -> None:
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.cards = []
        for room in rows:
            card = self._room_card(room)
            self.cards.append(card)
        self._relayout(self.canvas.winfo_width())

    def _room_card(self, room: dict) -> tk.Frame:
        colour = STATUS_COLOURS.get(room["status"], ui.MUTED)
        outer = tk.Frame(self.grid_frame, bg=colour, highlightthickness=1,
                         highlightbackground=ui.LINE)
        body = tk.Frame(outer, bg=ui.CARD)
        body.pack(fill="both", expand=True, padx=4, pady=4)

        top = tk.Frame(body, bg=ui.CARD)
        top.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(top, text=room["room_no"], bg=ui.CARD, fg=ui.INK,
                 font=(ui.FONT, 20, "bold")).pack(side="left")
        tk.Label(top, text=room["status"], bg=colour, fg="white",
                 font=(ui.FONT, 8, "bold"), padx=6, pady=2).pack(side="right", pady=(6, 0))

        tk.Label(body, text=room["room_type"] or "—", bg=ui.CARD, fg=ui.MUTED,
                 font=(ui.FONT, 8)).pack(anchor="w", padx=12, pady=(2, 0))

        details = tk.Frame(body, bg=ui.CARD)
        details.pack(fill="x", padx=12, pady=(8, 4))
        guest = room["guest_name"] or "—"
        rows = [
            ("Guest", guest),
            ("Check-in", room["check_in"] or "—"),
            ("Check-out", room["expected_checkout"] or "—"),
            ("Rate", ui.money(room["rate"]) + " / night"),
            ("Balance", ui.money(room["balance"])),
            ("Housekeeping", HOUSEKEEPING_LABELS.get(room["housekeeping"], room["housekeeping"])),
        ]
        for label, value in rows:
            line = tk.Frame(details, bg=ui.CARD)
            line.pack(fill="x", pady=1)
            tk.Label(line, text=label, bg=ui.CARD, fg=ui.MUTED,
                     font=(ui.FONT, 8), width=11, anchor="w").pack(side="left")
            tk.Label(line, text=str(value), bg=ui.CARD, fg=ui.INK,
                     font=(ui.FONT, 9), anchor="w", wraplength=190,
                     justify="left").pack(side="left", fill="x", expand=True)

        buttons = tk.Frame(body, bg=ui.CARD)
        buttons.pack(fill="x", padx=10, pady=(4, 10))
        tk.Button(buttons, text="Select", command=lambda r=room: self.select(r["room_no"]),
                  bg=ui.CARD, fg=ui.BRAND, activebackground="#F1E9DC",
                  relief="flat", font=(ui.FONT, 8), cursor="hand2").pack(side="left")
        tk.Button(buttons, text="Open folio", command=lambda r=room: self.open_folio(r["room_no"]),
                  bg=ui.CARD, fg=ui.BRAND, activebackground="#F1E9DC",
                  relief="flat", font=(ui.FONT, 8), cursor="hand2").pack(side="left")

        outer.room_no = room["room_no"]
        outer.bind("<Button-1>", lambda _e, r=room: self.select(r["room_no"]))
        return outer

    def _on_wheel(self, event) -> None:
        if self.winfo_exists() and self.canvas.winfo_ismapped():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------- actions
    def select(self, room_no: str) -> None:
        self.selected_room = room_no
        ui.notify(self.status, f"Room {room_no} selected.", ui.MUTED)

    def _require_room(self) -> str | None:
        room_no = self.selected_room
        if not room_no:
            ui.notify(self.status, "Select a room card first.", ui.DANGER)
            return None
        return room_no

    def _guard(self, permission: str, action: str) -> bool:
        try:
            permissions.require(self.app.user, permission, action)
        except permissions.PermissionError_ as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return False
        return True

    def _room(self, room_no: str) -> dict | None:
        for room in getattr(self, "all_rooms", []):
            if room["room_no"] == room_no:
                return room
        return None

    def reserve(self) -> None:
        room_no = self._require_room()
        if not room_no or not self._guard("room.reserve", "reserve a room"):
            return
        ReserveDialog(self, room_no, self.conn, self.app.user, self.reload)

    def check_in(self) -> None:
        room_no = self._require_room()
        if not room_no or not self._guard("room.check_in", "check a guest in"):
            return
        CheckInDialog(self, room_no, self.conn, self.app.user, self.reload)

    def check_out(self) -> None:
        room_no = self._require_room()
        if not room_no or not self._guard("room.check_out", "check a guest out"):
            return
        room = self._room(room_no)
        if not room or not room.get("stay_id"):
            ui.notify(self.status, f"Room {room_no} has no guest in house.", ui.DANGER)
            return
        CheckOutDialog(self, room_no, self.conn, self.app.user, self.app, self.reload)

    def add_charge(self) -> None:
        room_no = self._require_room()
        if not room_no or not self._guard("room.charge", "post a room charge"):
            return
        room = self._room(room_no)
        if not room or not room.get("stay_id"):
            ui.notify(self.status, f"Room {room_no} has no guest in house.", ui.DANGER)
            return
        ChargeDialog(self, room_no, self.conn, self.app.user, self.reload)

    def extend_stay(self) -> None:
        room_no = self._require_room()
        if not room_no or not self._guard("room.extend", "extend a stay"):
            return
        room = self._room(room_no)
        if not room or not room.get("stay_id"):
            ui.notify(self.status, f"Room {room_no} has no guest in house.", ui.DANGER)
            return
        ExtendDialog(self, room_no, self.conn, self.app.user, self.reload)

    def set_rate(self) -> None:
        room_no = self._require_room()
        if not room_no or not self._guard("room.rate", "change a room rate"):
            return
        RateDialog(self, room_no, self.conn, self.app.user, self.reload)

    def housekeeping(self) -> None:
        room_no = self._require_room()
        if not room_no:
            return
        HousekeepingDialog(self, room_no, self.conn, self.app.user, self.reload)

    def manage_inventory(self) -> None:
        if not self._guard("room.inventory", "change the room list"):
            return
        InventoryDialog(self, self.conn, self.app.user, self.reload)

    def show_history(self) -> None:
        room_no = self._require_room()
        if not room_no:
            return
        HistoryDialog(self, room_no, self.conn)

    def open_folio(self, room_no: str) -> None:
        room = self._room(room_no)
        if not room:
            return
        if room.get("stay_id"):
            FolioDialog(self, room_no, self.conn, self.app)
        else:
            StayHistoryDialog(self, room_no, self.conn)


# --------------------------------------------------------------------------- #
# dialogs
# --------------------------------------------------------------------------- #
class _Dialog(tk.Toplevel):
    """A small modal dialog with a Save and a Cancel button."""

    def __init__(self, master, title: str, width: int = 520):
        super().__init__(master)
        self.title(title)
        self.configure(bg=ui.BG)
        self.geometry(f"{width}x+80+80")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.body = ttk.Frame(self, padding=18)
        self.body.pack(fill="both", expand=True)
        self.result: object = None

    def add_buttons(self, on_save, save_text: str = "Save") -> None:
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(16, 0))
        ttk.Button(row, text=save_text, style="Primary.TButton",
                   command=self._save(on_save)).pack(side="right")
        ttk.Button(row, text="Cancel", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=8)

    def _save(self, on_save):
        try:
            on_save()
        except Exception as exc:  # noqa: BLE001 - show the problem, keep the dialog
            messagebox.showerror("Cannot continue", str(exc), parent=self)

    def info(self, text: str, colour: str = ui.MUTED) -> None:
        self._message = ttk.Label(self.body, text=text, style="Muted.TLabel",
                                  wraplength=460, justify="left")
        self._message.pack(anchor="w", pady=(6, 0))
        self._message.configure(foreground=colour)


class ReserveDialog(_Dialog):
    def __init__(self, master, room_no, conn, user, on_done):
        super().__init__(master, f"Reserve room {room_no}")
        self.conn = conn
        self.user = user
        self.on_done = on_done
        self.room_no = room_no

        ttk.Label(self.body, text=f"Reserve room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        self.info("A confirmed reservation blocks the room for those nights. "
                  "Overlapping bookings are refused.")

        row1 = ttk.Frame(self.body)
        row1.pack(fill="x", pady=(12, 0))
        self.name = tk.StringVar()
        self.phone = tk.StringVar()
        ui.field(row1, "Guest name", self.name, card=False).pack(side="left", fill="x", expand=True)
        ui.field(row1, "Phone", self.phone, width=16, card=False).pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(self.body)
        row2.pack(fill="x", pady=(8, 0))
        self.check_in = tk.StringVar(value=date.today().isoformat())
        self.check_out = tk.StringVar(
            value=(date.today() + timedelta(days=1)).isoformat()
        )
        ui.field(row2, "Check-in", self.check_in, width=14, card=False).pack(side="left")
        ui.field(row2, "Check-out", self.check_out, width=14, card=False).pack(side="left", padx=8)

        row3 = ttk.Frame(self.body)
        row3.pack(fill="x", pady=(8, 0))
        self.rate = tk.StringVar()
        self.deposit = tk.StringVar()
        ui.field(row3, "Nightly rate", self.rate, width=14, card=False).pack(side="left")
        ui.field(row3, "Deposit", self.deposit, width=14, card=False).pack(side="left", padx=8)

        self.address = tk.StringVar()
        ui.field(self.body, "Address", self.address, card=False).pack(fill="x", pady=(8, 0))
        self.notes = tk.StringVar()
        ui.field(self.body, "Notes", self.notes, card=False).pack(fill="x", pady=(8, 0))

        self.add_buttons(self.save, "Reserve")

    def save(self) -> None:
        rooms.create_reservation(
            self.conn,
            self.room_no,
            self.name.get(),
            self.check_in.get().strip(),
            self.check_out.get().strip(),
            nightly_rate=float(self.rate.get() or 0),
            guest_phone=self.phone.get().strip(),
            guest_address=self.address.get().strip(),
            deposit=float(self.deposit.get() or 0),
            notes=self.notes.get().strip(),
            user_id=self.user["user_id"],
        )
        self.on_done()
        self.destroy()


class CheckInDialog(_Dialog):
    def __init__(self, master, room_no, conn, user, on_done):
        super().__init__(master, f"Check in to room {room_no}")
        self.conn = conn
        self.user = user
        self.on_done = on_done
        self.room_no = room_no

        ttk.Label(self.body, text=f"Check in to room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        self.info("A room that already has a guest, or that is under "
                  "maintenance, cannot be checked in.")

        self.reservation_id: int | None = None
        pending = [
            row
            for row in rooms.list_reservations(conn, status="confirmed", room_no=room_no)
            if row["check_in"] <= date.today().isoformat()
            and row["check_out"] >= date.today().isoformat()
        ]
        if pending:
            self.info(
                f"Reservation found: {pending[0]['guest_name']} "
                f"({pending[0]['check_in']} → {pending[0]['check_out']}). "
                "Leave the fields as they are to use it.",
                ui.OK,
            )
            self.reservation_id = pending[0]["reservation_id"]
            self.name = tk.StringVar(value=pending[0]["guest_name"])
            self.phone = tk.StringVar(value=pending[0]["guest_phone"])
            self.rate = tk.StringVar(value=f"{float(pending[0]['nightly_rate'] or 0):g}")
            self.checkout = tk.StringVar(value=pending[0]["check_out"])
        else:
            self.name = tk.StringVar()
            self.phone = tk.StringVar()
            self.rate = tk.StringVar()
            self.checkout = tk.StringVar(
                value=(date.today() + timedelta(days=1)).isoformat()
            )

        row1 = ttk.Frame(self.body)
        row1.pack(fill="x", pady=(12, 0))
        ui.field(row1, "Guest name", self.name, card=False).pack(side="left", fill="x", expand=True)
        ui.field(row1, "Phone", self.phone, width=16, card=False).pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(self.body)
        row2.pack(fill="x", pady=(8, 0))
        ui.field(row2, "Expected check-out", self.checkout, width=16, card=False).pack(side="left")
        ui.field(row2, "Nightly rate", self.rate, width=14, card=False).pack(side="left", padx=8)

        self.address = tk.StringVar()
        self.pan = tk.StringVar()
        row3 = ttk.Frame(self.body)
        row3.pack(fill="x", pady=(8, 0))
        ui.field(row3, "Address", self.address, card=False).pack(side="left", fill="x", expand=True)
        ui.field(row3, "PAN", self.pan, width=16, card=False).pack(side="left", padx=(8, 0))

        self.add_buttons(self.save, "Check in")

    def save(self) -> None:
        rooms.check_in(
            self.conn,
            self.room_no,
            self.name.get(),
            expected_checkout=self.checkout.get().strip(),
            nightly_rate=float(self.rate.get() or 0),
            guest_phone=self.phone.get().strip(),
            guest_address=self.address.get().strip(),
            guest_pan=self.pan.get().strip(),
            reservation_id=self.reservation_id,
            user_id=self.user["user_id"],
        )
        self.on_done()
        self.destroy()


class CheckOutDialog(_Dialog):
    def __init__(self, master, room_no, conn, user, app, on_done):
        super().__init__(master, f"Check out of room {room_no}", width=640)
        self.conn = conn
        self.user = user
        self.app = app
        self.on_done = on_done
        self.room_no = room_no

        room = rooms.list_rooms(conn)
        stay_id = next(
            (r["stay_id"] for r in room if r["room_no"] == room_no and r["stay_id"]), None
        )
        if not stay_id:
            raise rooms.RoomError(f"Room {room_no} has no guest in house.")

        self.bill_type = tk.StringVar(value="tax")
        self.preview = rooms.folio_preview(conn, stay_id, self.bill_type.get())

        ttk.Label(self.body, text=f"Check out of room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        self.info("This raises the folio invoice. The invoice is created once — "
                  "checking out again is refused.")

        wrap = ttk.Frame(self.body)
        wrap.pack(fill="both", expand=True, pady=(10, 0))
        tree = ui.table(
            wrap,
            [("description", "Description", 300), ("qty", "Qty", 60),
             ("rate", "Rate", 100), ("amount", "Amount", 110)],
            height=7,
        )
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        for line in self.preview["lines"]:
            tree.insert("", "end", values=(
                line["description"], f"{line['qty']:g} {line['unit']}",
                ui.money(line["unit_price"]),
                ui.money(round(line["qty"] * line["unit_price"], 2)),
            ))

        totals = self.preview["totals"]
        summary = ttk.Frame(self.body)
        summary.pack(fill="x", pady=(10, 0))
        for label, value in (
            ("Subtotal", totals["subtotal"]),
            ("Service charge", totals["service_charge"]),
            ("VAT", totals["vat"]),
            ("Total", totals["total"]),
        ):
            line = ttk.Frame(summary)
            line.pack(fill="x")
            ttk.Label(line, text=label, style="Muted.TLabel").pack(side="left")
            ttk.Label(line, text=ui.money(value),
                      style="Total.TLabel" if label == "Total" else "TLabel").pack(side="right")

        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(10, 0))
        self.method = tk.StringVar(value="Cash")
        self.paid = tk.StringVar(value=f"{totals['total']:.2f}")
        ui.field(row, "Payment method", self.method, width=18, card=False).pack(side="left")
        ui.field(row, "Amount received", self.paid, width=16, card=False).pack(side="left", padx=8)
        ttk.Label(row, text="Bill type", style="Muted.TLabel").pack(side="left", padx=(8, 4))
        box = ttk.Combobox(row, textvariable=self.bill_type, state="readonly", width=14,
                           values=["tax", "supply"])
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda _e: self._refresh())

        self.add_buttons(self.save, "Check out & bill")

    def _refresh(self) -> None:
        room = rooms.list_rooms(self.conn)
        stay_id = next(
            (r["stay_id"] for r in room if r["room_no"] == self.room_no and r["stay_id"]), None
        )
        if stay_id:
            self.preview = rooms.folio_preview(self.conn, stay_id, self.bill_type.get())
            self.paid.set(f"{self.preview['totals']['total']:.2f}")

    def save(self) -> None:
        room = rooms.list_rooms(self.conn)
        stay_id = next(
            (r["stay_id"] for r in room if r["room_no"] == self.room_no and r["stay_id"]), None
        )
        if not stay_id:
            raise rooms.RoomError(f"Room {self.room_no} has no guest in house.")
        bill_no = rooms.check_out(
            self.conn,
            stay_id,
            payment_method=self.method.get(),
            paid=float(self.paid.get() or 0),
            bill_type=self.bill_type.get(),
            user_id=self.user["user_id"],
            username=self.user["full_name"] or self.user["username"],
        )
        self.on_done()
        self.destroy()
        messagebox.showinfo(
            "Checked out",
            f"Room {self.room_no} checked out.\nInvoice {bill_no} created.",
            parent=self.master,
        )


class ChargeDialog(_Dialog):
    def __init__(self, master, room_no, conn, user, on_done):
        super().__init__(master, f"Add a charge to room {room_no}")
        self.conn = conn
        self.user = user
        self.on_done = on_done
        self.room_no = room_no

        ttk.Label(self.body, text=f"Add a charge to room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        self.info("Food, beverages and other services are posted to the folio "
                  "and billed with the room invoice.")

        self.description = tk.StringVar()
        self.category = tk.StringVar(value="service")
        self.qty = tk.StringVar(value="1")
        self.price = tk.StringVar()

        row1 = ttk.Frame(self.body)
        row1.pack(fill="x", pady=(12, 0))
        ui.field(row1, "Description", self.description, card=False).pack(side="left", fill="x", expand=True)
        ttk.Label(row1, text="Category", style="Muted.TLabel").pack(side="left", padx=(8, 4))
        ttk.Combobox(row1, textvariable=self.category, state="readonly", width=12,
                     values=list(CHARGE_CATEGORIES)).pack(side="left")

        row2 = ttk.Frame(self.body)
        row2.pack(fill="x", pady=(8, 0))
        ui.field(row2, "Quantity", self.qty, width=12, card=False).pack(side="left")
        ui.field(row2, "Unit price", self.price, width=14, card=False).pack(side="left", padx=8)

        self.add_buttons(self.save, "Add charge")

    def save(self) -> None:
        room = rooms.list_rooms(self.conn)
        stay_id = next(
            (r["stay_id"] for r in room if r["room_no"] == self.room_no and r["stay_id"]), None
        )
        if not stay_id:
            raise rooms.RoomError(f"Room {self.room_no} has no guest in house.")
        qty = float(self.qty.get() or 1)
        price = float(self.price.get() or 0)
        rooms.add_charge(
            self.conn,
            stay_id,
            self.description.get(),
            amount=qty * price,
            category=self.category.get(),
            qty=qty,
            unit_price=price,
            user_id=self.user["user_id"],
        )
        self.on_done()
        self.destroy()


class ExtendDialog(_Dialog):
    def __init__(self, master, room_no, conn, user, on_done):
        super().__init__(master, f"Extend the stay in room {room_no}")
        self.conn = conn
        self.user = user
        self.on_done = on_done
        self.room_no = room_no

        ttk.Label(self.body, text=f"Extend the stay in room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        self.info("The expected check-out date and time can be changed or "
                  "extended. Past stays cannot be changed.")
        self.new_checkout = tk.StringVar(
            value=(date.today() + timedelta(days=2)).isoformat() + " 11:00"
        )
        ui.field(self.body, "New check-out (YYYY-MM-DD HH:MM)", self.new_checkout,
                 card=False).pack(fill="x", pady=(12, 0))
        self.add_buttons(self.save, "Update")

    def save(self) -> None:
        room = rooms.list_rooms(self.conn)
        stay_id = next(
            (r["stay_id"] for r in room if r["room_no"] == self.room_no and r["stay_id"]), None
        )
        if not stay_id:
            raise rooms.RoomError(f"Room {self.room_no} has no guest in house.")
        rooms.extend_stay(self.conn, stay_id, self.new_checkout.get().strip(),
                          user_id=self.user["user_id"])
        self.on_done()
        self.destroy()


class RateDialog(_Dialog):
    def __init__(self, master, room_no, conn, user, on_done):
        super().__init__(master, f"Room rate — {room_no}")
        self.conn = conn
        self.user = user
        self.on_done = on_done
        self.room_no = room_no

        ttk.Label(self.body, text=f"Nightly rate for room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        self.info("The nightly rate is what the folio charges for each night.")
        room = db.get_room(conn, room_no)
        self.rate = tk.StringVar(value=f"{float(room['nightly_rate'] or 0):g}" if room else "")
        ui.field(self.body, "Rate per night", self.rate, card=False).pack(fill="x", pady=(12, 0))
        self.add_buttons(self.save, "Save rate")

    def save(self) -> None:
        rooms.set_rate(self.conn, self.room_no, float(self.rate.get() or 0),
                       user_id=self.user["user_id"])
        self.on_done()
        self.destroy()


class HousekeepingDialog(_Dialog):
    def __init__(self, master, room_no, conn, user, on_done):
        super().__init__(master, f"Housekeeping — room {room_no}")
        self.conn = conn
        self.user = user
        self.on_done = on_done
        self.room_no = room_no

        ttk.Label(self.body, text=f"Housekeeping for room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        self.info("A room that needs cleaning or is under maintenance is never "
                  "handed to a new guest.")
        self.state = tk.StringVar(value="clean")
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(12, 0))
        ttk.Combobox(row, textvariable=self.state, state="readonly", width=22,
                     values=[("clean", "Ready"), ("needs_cleaning", "Needs cleaning"),
                             ("maintenance", "Under maintenance")]).pack(side="left")
        self.add_buttons(self.save, "Save")

    def save(self) -> None:
        state = self.state.get()
        if state == "maintenance":
            try:
                permissions.require(self.user, "room.maintenance", "take a room out of service")
            except permissions.PermissionError_ as exc:
                raise exc
        rooms.set_housekeeping(self.conn, self.room_no, state, user_id=self.user["user_id"])
        self.on_done()
        self.destroy()


class InventoryDialog(_Dialog):
    def __init__(self, master, conn, user, on_done):
        super().__init__(master, "Room list", width=560)
        self.conn = conn
        self.user = user
        self.on_done = on_done

        ttk.Label(self.body, text="Room list", style="H2.TLabel").pack(anchor="w")
        self.info("The hotel's room numbers. Rooms that are removed are only "
                  "deactivated, never deleted, so historic bills keep their "
                  "room number. The default is 101-125.")
        self.numbers = tk.StringVar(
            value=db.get_settings(conn).get("room_numbers")
            or ", ".join(rooms.default_room_numbers())
        )
        ui.field(self.body, "Room numbers (e.g. 101-125, 201, 202)", self.numbers,
                 card=False).pack(fill="x", pady=(12, 0))
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(10, 0))
        self.deactivate = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Deactivate rooms that are not in this list",
                        variable=self.deactivate).pack(side="left")
        self.add_buttons(self.save, "Apply")

    def save(self) -> None:
        numbers = rooms.parse_room_numbers(self.numbers.get())
        if not numbers:
            raise rooms.RoomError("Enter at least one room number.")
        if self.deactivate.get() and not ui.ask(
            "Rooms that are not in this list will be deactivated. They are "
            "not deleted, and their history is kept. Continue?"
        ):
            return
        result = rooms.set_inventory(self.conn, numbers, deactivate_extra=self.deactivate.get())
        db.set_setting(self.conn, "room_numbers", ", ".join(numbers))
        conn.commit()
        db.log_audit(self.conn, "room.inventory", "room", "",
                     f"{len(result['created'])} created, "
                     f"{len(result.get('deactivated', []))} deactivated",
                     self.user["user_id"], self.user["username"])
        self.on_done()
        self.destroy()


class HistoryDialog(_Dialog):
    def __init__(self, master, room_no, conn):
        super().__init__(master, f"Room history — {room_no}", width=720)
        ttk.Label(self.body, text=f"Past stays in room {room_no}",
                  style="H2.TLabel").pack(anchor="w")
        wrap = ttk.Frame(self.body)
        wrap.pack(fill="both", expand=True, pady=(10, 0))
        tree = ui.table(
            wrap,
            [("guest", "Guest", 160), ("check_in", "Check-in", 130),
             ("check_out", "Check-out", 130), ("nights", "Nights", 60),
             ("bill", "Invoice", 110), ("rate", "Rate", 90)],
            height=12,
        )
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        rows = rooms.room_history(conn, room_no)
        for row in rows:
            tree.insert("", "end", values=(
                row["guest_name"], row["check_in"], row["check_out"] or "—",
                row["nights"], row["bill_no"] or "—", ui.money(row["nightly_rate"]),
            ))
        if not rows:
            ttk.Label(self.body, text="This room has no past stays.",
                      style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Button(self.body, text="Close", style="Ghost.TButton",
                   command=self.destroy).pack(anchor="e", pady=(10, 0))


class FolioDialog(_Dialog):
    """The live folio of the guest in the room, with print and PDF actions."""

    def __init__(self, master, room_no, conn, app):
        super().__init__(master, f"Folio — room {room_no}", width=660)
        self.conn = conn
        self.app = app
        self.room_no = room_no

        room = next(
            (r for r in rooms.list_rooms(conn) if r["room_no"] == room_no), None
        )
        stay_id = room["stay_id"] if room else None
        ttk.Label(self.body, text=f"Room {room_no} folio", style="H2.TLabel").pack(anchor="w")
        if not stay_id:
            self.info("No guest is in this room right now.")
            ttk.Button(self.body, text="Close", style="Ghost.TButton",
                       command=self.destroy).pack(anchor="e", pady=(10, 0))
            return

        preview = rooms.folio_preview(conn, stay_id)
        self.info(
            f"{preview['nights']} night(s) at {ui.money(preview['rate'])} per night · "
            f"{len(preview['charges'])} extra charge(s). "
            "The invoice is raised at check-out."
        )
        wrap = ttk.Frame(self.body)
        wrap.pack(fill="both", expand=True, pady=(10, 0))
        tree = ui.table(
            wrap,
            [("description", "Description", 320), ("qty", "Qty", 60),
             ("rate", "Rate", 100), ("amount", "Amount", 110)],
            height=8,
        )
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        for line in preview["lines"]:
            tree.insert("", "end", values=(
                line["description"], f"{line['qty']:g} {line['unit']}",
                ui.money(line["unit_price"]),
                ui.money(round(line["qty"] * line["unit_price"], 2)),
            ))

        totals = preview["totals"]
        summary = ttk.Frame(self.body)
        summary.pack(fill="x", pady=(10, 0))
        for label, value in (
            ("Subtotal", totals["subtotal"]),
            ("Service charge", totals["service_charge"]),
            ("VAT", totals["vat"]),
            ("Total", totals["total"]),
        ):
            line = ttk.Frame(summary)
            line.pack(fill="x")
            ttk.Label(line, text=label, style="Muted.TLabel").pack(side="left")
            ttk.Label(line, text=ui.money(value),
                      style="Total.TLabel" if label == "Total" else "TLabel").pack(side="right")

        ttk.Button(self.body, text="Close", style="Ghost.TButton",
                   command=self.destroy).pack(anchor="e", pady=(10, 0))


class StayHistoryDialog(_Dialog):
    def __init__(self, master, room_no, conn):
        super().__init__(master, f"Room {room_no} history", width=720)
        ttk.Label(self.body, text=f"Room {room_no} history", style="H2.TLabel").pack(anchor="w")
        wrap = ttk.Frame(self.body)
        wrap.pack(fill="both", expand=True, pady=(10, 0))
        tree = ui.table(
            wrap,
            [("guest", "Guest", 160), ("check_in", "Check-in", 130),
             ("check_out", "Check-out", 130), ("nights", "Nights", 60),
             ("bill", "Invoice", 110), ("rate", "Rate", 90)],
            height=12,
        )
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        rows = rooms.room_history(conn, room_no)
        for row in rows:
            tree.insert("", "end", values=(
                row["guest_name"], row["check_in"], row["check_out"] or "—",
                row["nights"], row["bill_no"] or "—", ui.money(row["nightly_rate"]),
            ))
        if not rows:
            ttk.Label(self.body, text="This room has no past stays.",
                      style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Button(self.body, text="Close", style="Ghost.TButton",
                   command=self.destroy).pack(anchor="e", pady=(10, 0))
