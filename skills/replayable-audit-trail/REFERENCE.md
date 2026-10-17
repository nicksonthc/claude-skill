# replayable-audit-trail — building blocks

Genericized from the source project. Sections are numbered to match SKILL.md's
"Moving parts" (§9 is the rule to paste into the target repo's agent guide).

Generic names used throughout — rename to the target domain:

| Generic | Meaning | In the source |
|---|---|---|
| `Order` / `aggregate_key` | the aggregate, the unit of restore | a batch / job order, keyed by its code |
| `Item` / `item_key` | a child with its own natural key | a unit, keyed by its serial |
| `Place` / `place_code` | where a child event happened | a station, by code |
| `Parent` → `Step` → `StepField` | reference data a reseed rebuilds | activity → step → field |
| `Visit`, `Record`, `FieldValue`, `Ticket`, `Output` | runtime rows under an item | station visit, step record, captured value, rework ticket, label print |
| `actor_ref` | a person's stable natural key | employee no. |

Python blocks assume FastAPI + SQLModel on async SQLAlchemy; `app.*` imports are
the target repo's own modules.

## 1. Event table

```python
# app/core/time.py
from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """UTC now as a naive datetime — for TIMESTAMP WITHOUT TIME ZONE columns
    (asyncpg rejects mixing tz-aware values into naive columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
```

```python
# app/models/audit_event.py
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.time import utcnow_naive


class AuditEvent(SQLModel, table=True):
    """Append-only audit trail of every write — the record a lost aggregate is
    rebuilt from (scripts/restore_aggregate.py).

    Deliberately self-contained: no foreign keys, and the payload names
    reference data by **code / name**, never by id, so it stays readable and
    replayable after the transactional tables are wiped or the reference data
    is reseeded with new ids. It is not in any purge list for the same reason.

    Written in the same transaction as the change it describes (see
    audit_service.record), so a committed change always has its event."""

    id: int | None = Field(default=None, primary_key=True)
    # "<noun>.<past-tense verb>", e.g. "order.created", "item.tracked_in"
    event: str = Field(index=True)
    aggregate_key: str | None = Field(default=None, index=True)
    item_key: str | None = Field(default=None, index=True)
    place_code: str | None = Field(default=None)
    # Plain ints/strings, no FK: the trail must outlive the rows it names.
    actor_id: int | None = Field(default=None)
    actor_ref: str | None = Field(default=None)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_naive, index=True)
```

The migration. If the app also runs `SQLModel.metadata.create_all` on startup (a
first-setup convenience that only creates missing tables), a new image can start
before `alembic upgrade head` and create the table itself — so the migration
checks first:

```python
"""audit event — append-only audit trail (models/audit_event.py)

The backend's startup create_all (checkfirst) creates this table on its own if
the new image starts before this migration runs, so both steps check for it."""
import sqlalchemy as sa
import sqlmodel
from alembic import op

_INDEXED = ("event", "aggregate_key", "item_key", "created_at")


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("auditevent"):
        return
    op.create_table(
        "auditevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("aggregate_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("item_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("place_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_ref", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in _INDEXED:
        op.create_index(op.f(f"ix_auditevent_{column}"), "auditevent", [column])


def downgrade() -> None:
    for column in _INDEXED:
        op.drop_index(op.f(f"ix_auditevent_{column}"), table_name="auditevent")
    op.drop_table("auditevent")
```

## 2. `record()` — staged in the caller's transaction

```python
# app/services/audit_service.py
"""The audit trail (models/audit_event.py).

`record` stages one AuditEvent on the caller's session, so it commits — or
rolls back — together with the change it describes. Call it after the change
is staged and flushed (ids/defaults assigned) and before the commit.

Payload conventions, so scripts/restore_aggregate.py can replay an aggregate:
places by `code`, steps by parent + step `name`, fields by item `code` or
`title`, people by their natural key; timestamps as naive-UTC ISO strings."""

from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditEvent, Item, Order, Place, User


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def aggregate_key_of(session: AsyncSession, item: Item) -> str | None:
    order = await session.get(Order, item.order_id)
    return order.code if order else None


async def place_code(session: AsyncSession, place_id: int | None) -> str | None:
    if place_id is None:
        return None
    place = await session.get(Place, place_id)
    return place.code if place else None


def record(
    session: AsyncSession,
    event: str,
    *,
    actor: User | None,
    payload: dict[str, Any],
    aggregate_key: str | None = None,
    item_key: str | None = None,
    place_code: str | None = None,
) -> AuditEvent:
    """Stage one audit event on `session` (the caller commits)."""
    row = AuditEvent(
        event=event,
        aggregate_key=aggregate_key,
        item_key=item_key,
        place_code=place_code,
        actor_id=actor.id if actor else None,
        actor_ref=actor.employee_no if actor else None,
        payload=payload,
    )
    session.add(row)
    return row
```

**Aggregate events carry the full current definition**, so a restore can rebuild
the aggregate from any one of them:

```python
# app/services/order_service.py
async def audit_order(
    session: AsyncSession,
    event: str,
    order: Order,
    actor: User | None,
    extra: dict | None = None,
) -> None:
    """Stage the order's audit event — its full current definition. `extra`
    carries what is particular to the event (a rename's `previous_key`, a
    removal's reason and snapshots, a creation's `via`)."""
    product = await session.get(Product, order.product_id) if order.product_id else None
    audit_service.record(
        session,
        event,
        actor=actor,
        aggregate_key=order.code,
        payload={
            "code": order.code,
            "customer": order.customer,
            "product_code": product.code if product else None,  # a code, never the id
            "quantity_planned": order.quantity_planned,
            "status": order.status.value,
            "active": order.active,
            "notes": order.notes,
            "created_at": audit_service.iso(order.created_at),
            **(extra or {}),
        },
    )


async def stage_order(session, *, actor, via: str | None = None, **fields) -> Order:
    """Add one already-checked order and its audit event — flushed, not
    committed (the caller owns the transaction). `via` records where it came
    from when not the main form (e.g. "ai_assistant"); provenance only — the
    actor is still the person who pressed Create, and the restore ignores it."""
    order = Order(**fields)
    session.add(order)
    await session.flush()  # ids and defaults exist from here
    await audit_order(session, "order.created", order, actor, {"via": via} if via else None)
    return order
```

**A rename is recorded under the new key**, carrying the old one:

```python
    if new_code != order.code:
        if (await session.exec(select(Order).where(Order.code == new_code))).first():
            raise HTTPException(409, f"Order {new_code} already exists")
        extra["previous_key"] = order.code
        order.code = new_code
    # ... other amended fields ...
    session.add(order)
    await session.flush()
    await audit_order(session, "order.updated", order, actor, extra)
    await session.commit()
```

**A child event** names its item, aggregate and place, and the natural key a
replay will look the row up by (here: the attempt number):

```python
    visit = Visit(item_id=item.id, place_id=place.id, actor_id=actor.id, attempt=attempt)
    session.add(visit)
    await session.flush()
    audit_service.record(
        session,
        "item.tracked_in",
        actor=actor,
        aggregate_key=await audit_service.aggregate_key_of(session, item),
        item_key=item.key,
        place_code=place.code,
        payload={"attempt": attempt, "tracked_in_at": audit_service.iso(visit.started_at)},
    )
    await session.commit()
    await emit_item_updated(...)  # realtime after the commit, never before
```

**A rejected attempt that must be kept** (a failed retry is evidence) commits
its record and event, then raises — raising first would roll both back:

```python
    if outcome == "mismatch":
        record.status = RecordStatus.failed
        record.completed_at = utcnow_naive()
        audit_record()            # stages the event
        await session.commit()    # the failed attempt stays on file
        raise HTTPException(409, "Value does not match the reference; re-scan and retry")
```

**Several creates, all or none**, with the caller's own bookkeeping in the same
transaction; a key taken in the meantime fails the commit, so no event survives:

```python
    created = [await stage_order(session, actor=user, via="ai_assistant", **d) for d in drafts]
    conversation.status = "created"     # caller's bookkeeping, same transaction
    session.add(conversation)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "A key was taken a moment ago — check and try again") from exc
```

## 3. Payload conventions and the event catalogue

- Reference data by **code or name** — a place by code, a step by its parent's
  name + step name, a field by its form item code (+ the flag that tells a value
  field from its remark field) or else its title.
- People by their **natural key** in the top-level `actor_ref`; never a user id
  inside the payload.
- Timestamps as naive-UTC ISO strings (`iso()`); a replay parses them back with
  `datetime.fromisoformat`, falling back to the event's own `created_at`.
- Captured values **verbatim**, with their verdicts:
  `{"code", "title", "is_remark", "value_text", "value_num", "passed"}`.
- A child row's identity is a **natural key**: a visit by (item key, place code,
  attempt); a ticket by (item key, place code, raised_at) — "ids do not survive a
  restore".
- Provenance keys (`via`) are recorded and never replayed.

Keep this catalogue in the repo next to the restore script — it is the contract
both sides honour. The child rows below are the source's production-line shape;
swap in your domain's.

| Event | Keys | Payload | Replay |
|---|---|---|---|
| `order.created` | aggregate | full definition (+ `via`) | the first order event seeds the row |
| `order.updated` | aggregate (the **new** key) | full definition (+ `previous_key` on a rename) | the last order event's fields win; a rename splices the old key in |
| `order.activated` | aggregate | full definition | none — restored inactive |
| `order.items_cleared` | aggregate | full definition + `reason`, `items_cleared`, `item_keys`, `items` (snapshots) | cut: item events before it are dropped |
| `order.deleted` | aggregate | same as items_cleared | a warning — this is the loss a restore undoes |
| `item.created` | aggregate, item, place | product code, ordinal, flags, status, starting place, created_at | insert the item |
| `item.tracked_in` | + place | attempt, tracked_in_at | insert the visit |
| `step.recorded` | + place | attempt, parent + step name, status, started/completed, `values[]`, `ticket?` | insert record + values (+ ticket, close visit, hold) |
| `item.tracked_out` | + place | attempt, tracked_out_at, next place, status, milestone stamps | close the visit, move the item |
| `ticket.resolved` | + origin place | raised_at (identity), disposition, notes, return place, resolved_at, item status, current place | update the matching ticket |
| `output.printed` | aggregate, item | what was produced, verbatim (e.g. the printed label's fields) | insert |
| `item.deleted` | aggregate, item, place | `reason` + snapshot + deleted_at | cut: the item's earlier events go; a warning |

## 4. Deletion contract

Server side — reason, snapshot, capture-before-delete:

```python
# app/services/order_service.py
def require_reason(reason: str | None) -> str:
    """Every deletion states why — it is the line of the audit trail and the
    Deletion log a reviewer reads first."""
    text = (reason or "").strip()
    if not text:
        raise HTTPException(
            400, "Give a reason for the deletion — it is kept in the audit trail and the Deletion log"
        )
    return text


# Field code -> slot name, for the parts bound to an item (extension point).
BINDING_FIELDS = {"PART-A-SN": "part_a", "PART-B-SN": "part_b"}


async def snapshots(session: AsyncSession, items: list[Item]) -> list[dict]:
    """What each item was at the moment it was deleted — kept in the audit
    event, because the rows themselves go. Name-based like every payload
    (codes and keys, no ids): its state and place, where it is tracked in right
    now, how much work was recorded, open tickets, outputs and bound parts.
    A fixed handful of grouped queries however many items there are."""
    if not items:
        return []
    ids = [i.id for i in items]
    places = {p.id: p.code for p in (await session.exec(select(Place))).all()}
    products = {p.id: p.code for p in (await session.exec(select(Product))).all()}

    def counts(rows) -> dict[int, int]:
        return {iid: int(n) for iid, n in rows}

    async def per_item(model, *where) -> dict[int, int]:
        return counts((await session.exec(
            select(model.item_id, func.count())
            .where(col(model.item_id).in_(ids), *where)
            .group_by(model.item_id)
        )).all())

    visits = await per_item(Visit)
    records = await per_item(Record)
    open_tickets = await per_item(Ticket, Ticket.status == TicketStatus.open)
    outputs = await per_item(Output)
    working_at = {
        v.item_id: places.get(v.place_id)
        for v in (await session.exec(
            select(Visit).where(col(Visit.item_id).in_(ids), col(Visit.ended_at).is_(None))
        )).all()
    }
    bindings: dict[int, dict[str, str]] = {}
    for value, code, iid in (await session.exec(
        select(FieldValue.value_text, StepField.code, Record.item_id)
        .join(Record, FieldValue.record_id == Record.id)
        .join(StepField, FieldValue.field_id == StepField.id)
        .where(
            col(Record.item_id).in_(ids),
            col(StepField.code).in_(list(BINDING_FIELDS)),
            Record.status == RecordStatus.done,  # a failed retry holds a mis-scan
        )
        .order_by(FieldValue.id)
    )).all():
        if value:  # oldest first, so the binding that stands wins
            bindings.setdefault(iid, {})[BINDING_FIELDS[code]] = value

    return [
        {
            "key": i.key,
            "status": i.status.value,
            "current_place_code": places.get(i.current_place_id),
            "working_at": working_at.get(i.id),
            "product_code": products.get(i.product_id),
            "ordinal": i.ordinal,
            "created_at": audit_service.iso(i.created_at),
            "visits": visits.get(i.id, 0),
            "records": records.get(i.id, 0),
            "open_tickets": open_tickets.get(i.id, 0),
            "outputs": outputs.get(i.id, 0),
            "bindings": bindings.get(i.id, {}),
        }
        for i in items
    ]


def removal_payload(reason: str, snaps: list[dict]) -> dict:
    return {
        "reason": reason,
        "items_cleared": len(snaps),
        "item_keys": [s["key"] for s in snaps],
        "items": snaps,
    }


async def _clear(session, order) -> tuple[list[dict], list[dict]]:
    """Stage the deletion of every item under `order` (not committed). Returns
    their snapshots and their realtime payloads — both captured before the
    delete, since the rows are gone by the time either is used."""
    items = list((await session.exec(
        select(Item).where(Item.order_id == order.id).order_by(Item.id)
    )).all())
    snaps = await snapshots(session, items)
    gone = await realtime_payloads(session, items)
    await delete_items(session, [i.id for i in items])  # children first; shared with any wipe
    return snaps, gone
```

The three flows. The order of operations is the contract — capture, delete,
re-derive, record, commit, emit:

```python
async def delete_item(session, key, reason, actor, client_id=None) -> dict:
    """One item (e.g. a mistyped serial that scan-to-create turned into a real
    record). Audited as `item.deleted`; a restore never brings it back."""
    reason = require_reason(reason)
    item = (await session.exec(select(Item).where(Item.key == key))).first()
    if item is None:
        raise HTTPException(404, f"No item {key}")
    order = await session.get(Order, item.order_id)
    snap = (await snapshots(session, [item]))[0]
    gone = await realtime_payloads(session, [item])
    await delete_items(session, [item.id])
    if order is not None:
        await rederive_status(session, order)  # its slot is free again
    audit_service.record(
        session,
        "item.deleted",
        actor=actor,
        aggregate_key=order.code if order else None,
        item_key=item.key,
        place_code=snap["current_place_code"],
        payload={"reason": reason, **snap, "deleted_at": audit_service.iso(utcnow_naive())},
    )
    await session.commit()
    await emit_items_removed(gone, skip_sid=client_id)  # the deleting tab handles its own response
    return {**snap, "aggregate_key": order.code if order else None}


async def clear_items(session, code, reason, actor) -> int:
    """Every item of an order, the order kept (back to open). The restore drops
    anything recorded before this event, so the items never come back."""
    reason = require_reason(reason)
    order = await get_order(session, code)
    snaps, gone = await _clear(session, order)
    await rederive_status(session, order)  # the event records the order as it now stands
    await audit_order(session, "order.items_cleared", order, actor, removal_payload(reason, snaps))
    await session.commit()
    await emit_items_removed(gone)
    return len(snaps)


async def delete_order(session, code, reason, actor) -> int:
    """An order at any stage, with its items. Recoverable from the trail until
    its key is reused."""
    reason = require_reason(reason)
    order = await get_order(session, code)
    snaps, gone = await _clear(session, order)
    # Other rows that reference the order go in the same transaction. Anything
    # deleted here without an event of its own is NOT restorable (the source
    # drops saved report remarks this way) — audit it or accept the loss.
    for row in (await session.exec(select(OrderNote).where(OrderNote.order_id == order.id))).all():
        await session.delete(row)
    # Before session.delete(order): audit_order reads the order's fields.
    await audit_order(session, "order.deleted", order, actor, removal_payload(reason, snaps))
    await session.delete(order)
    await session.commit()
    await emit_items_removed(gone)
    return len(snaps)
```

Routes take the reason in a JSON body — DELETE included (`fetch` sends a DELETE
body; FastAPI reads it):

```python
class DeletionIn(BaseModel):
    """Body of every deletion. The reason is required (blank → 400) and kept in
    the audit trail / Deletion log."""
    reason: str


@router.delete("/api/items/{key}", response_model=ItemDeletedOut)
async def delete_item_route(
    key: str,
    body: DeletionIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_roles(Role.supervisor, Role.admin)),
    sid: str | None = Depends(client_id),  # X-Client-Id, for skip_sid
):
    return await order_service.delete_item(session, key, body.reason, actor=user, client_id=sid)
```

Client side — the reason box and the typed confirmation:

```tsx
// src/components/DeleteItemDialog.tsx (essentials)
/** Who may delete an item — mirrors the backend gate; the backend decides. */
const CAN_DELETE_ITEM: ReadonlySet<Role> = new Set(["supervisor", "admin"])

/**
 * Why a deletion is happening — required on every delete. It is the first
 * thing someone reviewing the audit trail or the Deletion log reads, so the
 * box asks for it in plain words.
 */
export function ReasonField({ value, onChange, placeholder, autoFocus = false }: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  autoFocus?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor="deletion-reason">
        Reason <span className="text-destructive">*</span>
      </Label>
      <Textarea id="deletion-reason" rows={2} value={value} placeholder={placeholder}
        autoFocus={autoFocus} onChange={(e) => onChange(e.target.value)} />
      <p className="text-xs text-muted-foreground">
        Kept in the audit trail and the Deletion log, with your name and the time.
      </p>
    </div>
  )
}

export function DeleteItemDialog({ target, onClose, onDeleted }: {
  target: { key: string; aggregateKey: string | null; status: string; workingAt?: string | null } | null
  onClose: () => void
  onDeleted: (result: ItemDeleted) => void
}) {
  const [reason, setReason] = useState("")
  const [typed, setTyped] = useState("")
  const [busy, setBusy] = useState(false)
  // Keyed on the item key, not the object: the screens behind this re-render
  // on every live update, and a half-typed reason must survive that.
  const key = target?.key
  useEffect(() => {
    setReason("")
    setTyped("")
  }, [key])

  if (!target) return null
  // The key typed (or scanned) again, so a stray Enter can't do it.
  const ready = !!reason.trim() && typed.trim() === target.key

  async function remove() {
    if (!target || !ready) return
    setBusy(true)
    try {
      onDeleted(await api.deleteItem(target.key, reason.trim()))
      toast.success(`Item ${target.key} deleted`, { description: "recorded in the Deletion log" })
      onClose()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not delete the item")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent>
        {/* title, what goes with it, and amber warnings when it is tracked in
            somewhere right now or already finished (it leaves the reports too) */}
        <ReasonField value={reason} onChange={setReason} autoFocus
          placeholder="e.g. Serial mistyped at the first station — the real one is …" />
        <Label htmlFor="confirm-key">Type or scan <b className="font-mono">{target.key}</b> to confirm</Label>
        <Input id="confirm-key" value={typed} className="font-mono" autoComplete="off" spellCheck={false}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void remove() } }} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="destructive" disabled={busy || !ready} onClick={() => void remove()}>
            Delete item
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- The aggregate dialogs reuse `ReasonField`; deleting an order asks for its key
  typed only when it has items (nothing to lose otherwise), clearing always does.
- Show what will go before the button: a tally of the items by state, and an
  amber note when the order is the active one.
- The opening button sits off any scan-gun focus chain (`data-skip-autofocus` in
  `keyboard-first-hotkeys`) and renders nothing for roles that cannot delete.
- While a destructive dialog is open, pause the page's polling (or key the reset
  on a stable id as above), so a refresh never resets the form mid-sentence.

## 5. Restore script

The restore script — lifetime selection, the merge refusal, the name resolver, the replay registry and the CLI — lives in [`RESTORE.md`](RESTORE.md): only the restore branch needs it.

---

## 6. Deletion log

```python
# app/services/deletion_log_service.py
"""Deletion log — every item and order deletion, read from the audit trail.

Deleting removes the rows themselves, so the record of a deletion lives only
in the audit table, which is never purged. Three events count, each written
in the same transaction as the delete it describes:

- `item.deleted`        — one item
- `order.items_cleared` — every item of an order, the order kept
- `order.deleted`       — an order and its items

Each carries who, when, the stated reason and a snapshot of what went.
Events written before reasons and snapshots existed show those columns blank.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlmodel import col, select

from app.core.time import local_to_utc, utc_to_local  # the plant's timezone
from app.models import AuditEvent, User

ACTIONS = {  # audit event -> the action as the log names it
    "item.deleted": "Item deleted",
    "order.items_cleared": "Order items cleared",
    "order.deleted": "Order deleted",
}
STATUS_WORDS = {"in_progress": "in progress", "on_hold": "on hold", "completed": "completed", "scrapped": "scrapped"}


@dataclass
class DeletionRow:
    time_utc: datetime
    event: str
    action: str
    aggregate_key: str | None
    item_keys: list[str]
    state: str   # what the item(s) were when deleted
    detail: str  # product, recorded work, bindings / order facts
    actor: str   # "Name (natural key)"
    reason: str | None
    units: int = 0
    snapshots: list[dict] = field(default_factory=list)


def item_state(snap: dict) -> str:
    """"in progress at P1 (tracked in)" / "completed"."""
    status = STATUS_WORDS.get(snap.get("status") or "", snap.get("status") or "?")
    where = snap.get("working_at") or snap.get("current_place_code")
    text = status
    if where and snap.get("status") in ("in_progress", "on_hold"):
        text += f" at {where}"
        if snap.get("working_at"):
            text += " (tracked in)"
    return text


def item_detail(snap: dict) -> str:
    parts = [snap["product_code"]] if snap.get("product_code") else []
    visits, records = snap.get("visits"), snap.get("records")
    if visits is not None:  # absent on events older than snapshots
        parts.append("no work recorded" if not visits else f"{visits} visit(s), {records or 0} record(s)")
    if snap.get("open_tickets"):
        parts.append(f"{snap['open_tickets']} open ticket(s)")
    if snap.get("outputs"):
        parts.append(f"{snap['outputs']} output(s)")
    if bindings := snap.get("bindings"):
        parts.append(", ".join(f"{slot} {value}" for slot, value in bindings.items()))
    return " · ".join(parts)


def order_state(payload: dict) -> str:
    snaps = payload.get("items") or []
    if not snaps:  # deleted before snapshots existed: a count, or nothing at all
        n = payload.get("items_cleared")
        return f"{n} item(s)" if n else "no items"
    tally: dict[str, int] = {}
    for s in snaps:
        label = STATUS_WORDS.get(s.get("status") or "", s.get("status") or "?")
        tally[label] = tally.get(label, 0) + 1
    return ", ".join(f"{n} {label}" for label, n in tally.items())


def order_detail(payload: dict, event: str) -> str:
    parts = [
        p for p in (
            payload.get("product_code"),
            f"planned {payload['quantity_planned']}" if payload.get("quantity_planned") else None,
            payload.get("customer"),
        ) if p
    ]
    if event == "order.deleted" and payload.get("active"):
        parts.append("was the active order")
    return " · ".join(parts)


async def query(session, date_from: date | None = None, date_to: date | None = None,
                aggregate_key: str | None = None, q: str | None = None) -> list[DeletionRow]:
    """Deletions, newest first. `date_from` / `date_to` are plant-local days
    (inclusive); `aggregate_key` is exact; `q` matches an item key or an order
    key anywhere in the row (case-insensitive)."""
    stmt = select(AuditEvent).where(col(AuditEvent.event).in_(list(ACTIONS)))
    if date_from is not None:
        stmt = stmt.where(AuditEvent.created_at >= local_to_utc(datetime.combine(date_from, time.min)))
    if date_to is not None:
        stmt = stmt.where(
            AuditEvent.created_at < local_to_utc(datetime.combine(date_to, time.min)) + timedelta(days=1)
        )
    if aggregate_key:
        stmt = stmt.where(AuditEvent.aggregate_key == aggregate_key)
    events = list((await session.exec(
        stmt.order_by(col(AuditEvent.created_at).desc(), col(AuditEvent.id).desc())
    )).all())

    # Name the actor as they are now; the event keeps the natural key even if
    # the account is gone.
    refs = {e.actor_ref for e in events if e.actor_ref}
    names = {
        u.employee_no: u.name
        for u in (await session.exec(select(User).where(col(User.employee_no).in_(refs)))).all()
    } if refs else {}

    rows: list[DeletionRow] = []
    for e in events:
        p = e.payload or {}
        if e.event == "item.deleted":
            keys = [e.item_key] if e.item_key else []
            state, detail, snaps = item_state(p), item_detail(p), [p]
        else:
            keys = list(p.get("item_keys") or [])
            state, detail = order_state(p), order_detail(p, e.event)
            snaps = list(p.get("items") or [])
        who = e.actor_ref
        rows.append(DeletionRow(
            time_utc=e.created_at, event=e.event, action=ACTIONS[e.event],
            aggregate_key=e.aggregate_key, item_keys=keys, state=state, detail=detail,
            actor=f"{names[who]} ({who})" if who in names else (who or "—"),
            reason=p.get("reason"), units=len(keys), snapshots=snaps,
        ))

    # Item keys live inside the payload, so the free-text match runs on the rows.
    needle = (q or "").strip().lower()
    if needle:
        rows = [
            r for r in rows
            if needle in (r.aggregate_key or "").lower() or any(needle in k.lower() for k in r.item_keys)
        ]
    return rows


# --- Export: hand these to the repo's report layer -------------------------- #

COLUMNS = ["Date / Time", "Action", "Order", "Item(s)", "State when deleted", "Details", "Deleted by", "Reason"]


def cells(r: DeletionRow) -> list[str]:
    return [
        utc_to_local(r.time_utc).strftime("%d-%m-%Y %H:%M"),
        r.action, r.aggregate_key or "", ", ".join(r.item_keys),
        r.state, r.detail, r.actor, r.reason or "",
    ]


def period_label(date_from: date | None, date_to: date | None) -> str:
    f = date_from.strftime("%d-%m-%Y") if date_from else "the start"
    t = date_to.strftime("%d-%m-%Y") if date_to else "today"
    return f"{f} – {t}"


def filename(date_from: date | None, date_to: date | None, ext: str) -> str:
    tag = "_".join(d.strftime("%Y%m%d") for d in (date_from, date_to) if d) or "all"
    safe = re.sub(r"[^\w.-]+", "_", tag)  # outside the f-string: no backslash there before 3.12
    return f"Deletion_Log_{safe}.{ext}"


def render_csv(rows: list[DeletionRow], period: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Deletion log", period])
    w.writerow([])
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow(cells(r))
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel opens it as UTF-8
```

The PDF is the same `COLUMNS` / `cells` as a landscape table with the header row
repeated on every page and a "no deletions in this period" row spanning the
table when empty — built by whatever renders the repo's other reports.

Endpoints — one query helper, three representations, the same filters, managers
only (the PDF and CSV must list exactly what the page shows):

```python
_MANAGERS = require_roles(Role.supervisor, Role.admin)


@router.get("/api/reports/deletions", response_model=DeletionLogOut)
async def deletion_log(
    date_from: date | None = Query(default=None, description="plant-local day, inclusive"),
    date_to: date | None = Query(default=None, description="plant-local day, inclusive"),
    aggregate_key: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=64, description="Item or order key"),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_MANAGERS),
) -> DeletionLogOut:
    rows = await deletion_log_service.query(session, date_from, date_to, aggregate_key, q)
    return DeletionLogOut(period=deletion_log_service.period_label(date_from, date_to), rows=[...])

# /api/reports/deletions.pdf and .csv: same parameters, same query(), then the
# renderer, with Content-Disposition: attachment; filename="<filename(...)>".
```

The page (essentials):

```tsx
/** YYYY-MM-DD of a plant-local day `daysAgo` before today — the plant's
 *  calendar, not the browser's. */
function plantDay(daysAgo = 0, utcOffsetHours = PLANT_UTC_OFFSET_HOURS): string {
  return new Date(Date.now() + utcOffsetHours * 3600_000 - daysAgo * 86_400_000)
    .toISOString()
    .slice(0, 10)
}

const ACTION_STYLE: Record<DeletionRow["event"], string> = {
  "item.deleted": "border-amber-500/40 bg-amber-500/10 text-amber-700",
  "order.items_cleared": "border-orange-500/40 bg-orange-500/10 text-orange-700",
  "order.deleted": "border-rose-500/40 bg-rose-500/10 text-rose-700",
}

/** An order-wide deletion can name dozens of keys — show a few, the rest on
 *  hover (the PDF / CSV list them all). */
function Keys({ keys }: { keys: string[] }) {
  if (!keys.length) return <span className="text-muted-foreground">—</span>
  const shown = keys.slice(0, 3)
  return (
    <div title={keys.join(", ")}>
      {shown.map((k) => <div key={k} className="font-mono text-xs whitespace-nowrap">{k}</div>)}
      {keys.length > shown.length && (
        <div className="text-xs text-muted-foreground">+{keys.length - shown.length} more</div>
      )}
    </div>
  )
}
```

- Opens on the last 30 plant days straight away; filters: From, To, key search.
- A summary line: "N deletion(s) · M item(s) removed · <period>", then PDF
  preview and CSV download.
- Columns: When · Action (chip by event) · Order · Item(s) · State when deleted ·
  Details · By · Reason (an em dash when absent).
- One sentence under the summary: read from the audit trail, which keeps every
  deletion though the records are gone; deletions made before reasons were
  required show no reason.
- It lives where managers look (an admin hub tab — see `console-app-shell`).

Pure tests pin the wording and the tolerance for old events — no database:

```python
from datetime import datetime

from app.services import deletion_log_service as dl

SNAP = {"key": "K-001", "status": "in_progress", "current_place_code": "P1", "working_at": None,
        "product_code": "X1", "visits": 0, "records": 0, "open_tickets": 0, "outputs": 0, "bindings": {}}


def test_item_state_names_place_and_track_in():
    assert dl.item_state(SNAP) == "in progress at P1"
    assert dl.item_state({**SNAP, "working_at": "P1"}) == "in progress at P1 (tracked in)"
    # A finished item has no place to name.
    assert dl.item_state({**SNAP, "status": "completed", "current_place_code": None}) == "completed"


def test_order_state_tolerates_old_events():
    assert dl.order_state({"items": [{"status": "completed"}, {"status": "completed"}]}) == "2 completed"
    assert dl.order_state({"items_cleared": 4}) == "4 item(s)"  # before snapshots existed
    assert dl.order_state({}) == "no items"


def test_csv_has_bom_and_blank_reason_on_old_events():
    row = dl.DeletionRow(time_utc=datetime(2026, 1, 15, 1, 30), event="item.deleted", action="Item deleted",
                         aggregate_key="ORD-1", item_keys=["A", "B"], state="", detail="", actor="—", reason=None)
    data = dl.render_csv([row], "p").decode("utf-8")
    assert data.startswith("﻿")
    assert data.splitlines()[3].endswith(",")  # the empty Reason cell
```

## 7. Read API

```python
@router.get("/api/audit", response_model=list[AuditEventOut])
async def list_audit_events(
    aggregate_key: str | None = Query(default=None),
    item_key: str | None = Query(default=None),
    event: str | None = Query(default=None, description="Exact event, e.g. step.recorded"),
    limit: int = Query(default=1000, ge=1, le=10000),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(Role.supervisor, Role.admin)),
) -> list[AuditEventOut]:
    """The timeline of an aggregate and/or an item, oldest first. One of the
    two keys is required — the trail is never listed wholesale."""
    if not aggregate_key and not item_key:
        raise HTTPException(400, "Give an aggregate_key, an item_key, or both")
    stmt = select(AuditEvent)
    if aggregate_key:
        stmt = stmt.where(AuditEvent.aggregate_key == aggregate_key)
    if item_key:
        stmt = stmt.where(AuditEvent.item_key == item_key)
    if event:
        stmt = stmt.where(AuditEvent.event == event)
    res = await session.exec(stmt.order_by(col(AuditEvent.id)).limit(limit))
    return [AuditEventOut.model_validate(e) for e in res.all()]
```

`AuditEventOut` mirrors the table with `model_config = ConfigDict(from_attributes=True)`
and `payload: dict`.

## 8. Purge exclusion

```python
# scripts/seed.py — the reset / fresh-reseed purge.
# Children before parents, so TRUNCATE needs no CASCADE (which could silently
# take out a table added later). Every table with an FK into one of these is
# itself in one of the two lists.

# What running the system produced. AuditEvent is deliberately absent: it is
# the trail a wiped aggregate is rebuilt from, so it must survive a reseed.
TRANSACTIONAL_MODELS = [Output, FieldValue, Ticket, Record, Visit, Item, OrderNote, Order]

# Reference data, rebuilt wholesale by a fresh reseed. Only droppable once the
# transactional tables above are gone — records point here.
REFERENCE_MODELS = [StepField, Step, Parent]


async def purge(session: AsyncSession, *, reference: bool = True) -> dict[str, int]:
    """Truncate the transactional tables (and, by default, the reference data),
    restarting their identity sequences. Returns the rows deleted per table."""
    models = TRANSACTIONAL_MODELS + (REFERENCE_MODELS if reference else [])
    deleted = {
        m.__tablename__: (await session.exec(select(func.count()).select_from(m))).one()
        for m in models
    }
    await session.execute(text(f"TRUNCATE {', '.join(m.__tablename__ for m in models)} RESTART IDENTITY"))
    await session.commit()
    return deleted
```

- Every wipe path gets the same treatment: the reset endpoint, the fresh reseed,
  a demo-data wipe.
- Generated demo data that bypasses the services writes no events and its wipe
  is unaudited — it is scenery, not records. Keep it on a reserved key prefix and
  refuse renames into or out of that prefix, so real records never fall under
  the wipe and demo rows never enter the trail.
- Ordinals: issue `max(ordinal) + 1`, so deleting items never hands a number out
  twice; the restore re-inserts the number recorded at creation.

## 9. The rule for the project's agent guide

Paste into the target repo's CLAUDE.md / AGENTS.md conventions, with the real
names filled in:

```markdown
- Audit trail: every write calls `audit_service.record(...)` after its flush and
  before its commit (same transaction) with a name-based payload — codes and
  names, no ids — so `scripts/restore_aggregate.py` can replay it after a wipe or
  a reseed. A deletion also takes a required `reason` and records a snapshot of
  what it removed — it is all the Deletion log has. A **new** write path must do
  the same, and a new event or payload key needs a matching branch in the restore
  script, proven by a dry run on staging. `auditevent` stays out of every purge list.
```
