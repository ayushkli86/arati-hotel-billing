# BILLING_WORKFLOW

## Ownership
- Cloud owns kitchen/payment status of the ticket.
- Local owns rooms, guests, stays, invoices, room charges, menu.

## Flow
1. Waiter cuts KOT in cloud app (room or table).
2. Local poller pulls ticket into `kot_orders` (cursor-based, idempotent).
3. Room service → resolve room/stay/guest; post `RoomCharge` to stay folio once.
4. Walk-in/table → mirrored only; desk bills via existing `/mobile` or billing flow.
5. Cloud status changes (preparing/ready/served/paid) mirrored into `kot_orders`.
6. Payment status never auto-marks local invoice paid; local payment flow remains authoritative.
7. `link_billing` records `local_invoice_id/number` when a local KOT is linked to an invoice.

## Duplicate prevention
- Unique constraints on `cloud_kot_id`, `order_uuid`, queue `dedupe_key`.
- Cursor committed atomically with rows.
- Billing only touches `pending`/`review` tickets; flips to `billed`.
- Ten deliveries → one `kot_orders` row and one set of `RoomCharge` rows.
EOF