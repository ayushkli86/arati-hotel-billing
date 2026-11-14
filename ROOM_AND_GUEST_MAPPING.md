# ROOM_AND_GUEST_MAPPING

## Resolution rules (local authority)
1. Cloud table name `Room <n>` → `order_type = room`, `room_number = n`.
2. Look up `rooms` by `number` (never by id across systems).
3. Find an active stay: `stays.room_id = room.id`, `status = 'checked_in'`, `check_out IS NULL`.
4. Guest = `guests` row referenced by `stay.guest_id`; must be `active`.
5. If no room → `unknown_room` (exception queue, no charge).
6. If no active stay but a prior checked-out stay exists → `checked_out`.
7. If room exists but no stay → `vacant`.
8. Inactive guest → treated as `checked_out`.

## Billing attachment
- Resolved room-service ticket → `RoomCharge` rows posted to the stay folio.
- Posted exactly once (`billing_status pending → billed`).
- Vacant/checked-out/unknown → `review`, no charge, preserved in exception queue.
- Restaurant dine-in / takeaway → `not_applicable` (desk bills via existing flow).
EOF