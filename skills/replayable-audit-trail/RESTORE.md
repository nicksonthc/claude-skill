# replayable-audit-trail — the restore script

SKILL.md moving part 5, disclosed here because only the restore branch needs
it. It assumes the event table, `record()` and the payload conventions of
REFERENCE.md §1–§3; the blocks below read in order and assemble into one
script plus a Makefile target.

---

## 5. Restore script

```python
# scripts/restore_aggregate.py
"""Rebuild one aggregate from the audit trail (models/audit_event.py).

Run with:  uv run python -m scripts.restore_aggregate ORD-0042            # dry run
           uv run python -m scripts.restore_aggregate ORD-0042 --apply    # write it

Replays the aggregate's events oldest-first — the order, its items, and
everything recorded against them — in **one transaction**: either the whole
order comes back or nothing is written. The dry run does the same inserts and
flushes, then rolls back, and reports what would be restored and what can't be.

Values are re-linked by name, never by id (Resolver) — that is what makes a
restore work after a reseed gave the reference data new ids. Whatever the
current reference data no longer has is reported and skipped; the rest of the
order still restores. People are matched by their natural key; an event whose
user no longer exists is attributed to --fallback-actor (default: the first
admin).

Refuses if any of the order's item keys already exists, or if the order exists
and still has items — a restore only fills a gap, it never merges or
overwrites. Records made before the trail existed have no events to restore.
"""

import argparse
import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_app_env, get_settings
from app.db.session import async_session_maker
from app.models import (
    AuditEvent, FieldValue, Item, ItemStatus, Order, Output, Parent, Place,
    Product, Record, RecordStatus, Step, StepField, Ticket, User, Visit,
)
from app.services import order_service

ORDER_CREATED = "order.created"
ORDER_UPDATED = "order.updated"
ORDER_CLEARED = "order.items_cleared"
ORDER_DELETED = "order.deleted"
ITEM_CREATED = "item.created"
ITEM_DELETED = "item.deleted"
# The order's scalar fields copied from its events. Every payload key needs a
# home here, in a handler, or a stated reason to skip it — a key nobody
# replays is silently lost.
ORDER_FIELDS = ("customer", "notes", "reference_no")


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class Report:
    events: Counter = field(default_factory=Counter)
    restored: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
```

**Lifetime selection.** Which events belong to the order as it should come
back:

```python
def _starts_lifetime(e: AuditEvent) -> bool:
    """A key's lifetime starts when it is created, or when a rename moves an
    aggregate onto it (a key can only be renamed onto while it is free)."""
    return e.event == ORDER_CREATED or (
        e.event == ORDER_UPDATED and bool((e.payload or {}).get("previous_key"))
    )


async def _key_lifetime(session: AsyncSession, key: str, upto: int | None) -> list[AuditEvent]:
    """`key`'s events (up to event id `upto`), trimmed to its latest lifetime."""
    stmt = select(AuditEvent).where(AuditEvent.aggregate_key == key)
    if upto is not None:
        stmt = stmt.where(AuditEvent.id <= upto)
    rows = list((await session.exec(stmt.order_by(col(AuditEvent.id)))).all())
    starts = [n for n, e in enumerate(rows) if _starts_lifetime(e)]
    return rows[starts[-1]:] if starts else rows


async def lifetime_events(session: AsyncSession, key: str) -> list[AuditEvent]:
    """The order's events, oldest first.

    - Under every key it has carried: a rename (recorded under the new key with
      `previous_key`) pulls in the old key's events up to the rename — not
      after it, when that key may have been reused by another order.
    - Per key, from its latest lifetime start on: a deleted order's key can be
      reused, and the new order must not inherit the old one's items. Trimming
      per key (not across the merged list) keeps an order renamed onto a
      once-deleted key whole.
    - Minus the item events before its latest `order.items_cleared`: those
      items were cleared on purpose.
    - Minus an item's events up to its `item.deleted` (deleted on purpose).
      The deletion event itself stays, so the report can say why the item is
      not restored.
    """
    events: list[AuditEvent] = []
    queue: list[tuple[str, int | None]] = [(key, None)]
    seen = {key}
    while queue:
        code, upto = queue.pop()
        rows = await _key_lifetime(session, code, upto)
        events.extend(rows)
        for e in rows:  # only renames inside this lifetime are followed
            prev = (e.payload or {}).get("previous_key") if e.event == ORDER_UPDATED else None
            if prev and prev not in seen:
                seen.add(prev)
                queue.append((prev, e.id))
    events.sort(key=lambda e: e.id)

    cleared = [n for n, e in enumerate(events) if e.event == ORDER_CLEARED]
    if cleared:
        events = [e for n, e in enumerate(events) if n >= cleared[-1] or not e.item_key]
    deleted_at: dict[str, int] = {}  # item key -> id of its last deletion
    for e in events:
        if e.event == ITEM_DELETED and e.item_key:
            deleted_at[e.item_key] = e.id
    if deleted_at:
        events = [
            e for e in events
            if e.event == ITEM_DELETED
            or e.item_key not in deleted_at
            or e.id > deleted_at[e.item_key]
        ]
    return events
```

A key renamed away leaves its old events looking like a live order. Before a
restore, make sure no `order.updated` names the key as `previous_key` after its
last lifetime start — if one does, the order lives on under the new key; restore
that key instead (the item-key clash check below catches the common case).

**The resolver** — names to today's rows, cached:

```python
class Resolver:
    """Name -> current-row lookups, cached — the only place ids come from."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self._places: dict[str, Place] = {}
        self._products: dict[str, Product] = {}
        self._people: dict[str, int] = {}
        self._steps: dict[tuple, Step | None] = {}
        self._fields: dict[int, list[StepField]] = {}

    async def load(self) -> None:
        for p in (await self.s.exec(select(Place))).all():
            self._places[p.code] = p
        for p in (await self.s.exec(select(Product))).all():
            self._products[p.code] = p
        for u in (await self.s.exec(select(User))).all():
            self._people[u.employee_no] = u.id

    def place(self, code: str | None) -> Place | None:
        return self._places.get(code) if code else None

    def product(self, code: str | None) -> Product | None:
        return self._products.get(code) if code else None

    def person(self, ref: str | None) -> int | None:
        return self._people.get(ref or "")

    async def step(self, place: Place, item: Item, parent_name: str, step_name: str) -> Step | None:
        key = (place.id, item.family, parent_name, step_name)
        if key not in self._steps:
            parents = (await self.s.exec(
                select(Parent).where(Parent.place_id == place.id, Parent.family == item.family)
            )).all()
            # Prefer the parent with the recorded name; any of the place's
            # parents for this family will do if it was renamed.
            parents = sorted(parents, key=lambda a: a.name != parent_name)
            found = None
            for parent in parents:
                found = (await self.s.exec(
                    select(Step).where(Step.parent_id == parent.id, Step.name == step_name)
                )).first()
                if found:
                    break
            self._steps[key] = found
        return self._steps[key]

    async def field(self, step: Step, value: dict[str, Any]) -> StepField | None:
        if step.id not in self._fields:
            self._fields[step.id] = list((await self.s.exec(
                select(StepField).where(StepField.step_id == step.id)
            )).all())
        fields = self._fields[step.id]
        code, is_remark = value.get("code"), bool(value.get("is_remark"))
        if code:  # one form item code can own a value field and its remark field
            for f in fields:
                if f.code == code and bool(f.is_remark) == is_remark:
                    return f
        for f in fields:
            if f.title == value.get("title"):
                return f
        return None
```

**Replay context and handlers.** One handler per child event; an event without
one is reported, never silently dropped:

```python
@dataclass
class Replay:
    session: AsyncSession
    res: Resolver
    rep: Report
    order: Order
    fallback: int
    items: dict[str, Item] = field(default_factory=dict)
    # Natural keys — ids do not survive a restore.
    visits: dict[tuple[str, str, int], Visit] = field(default_factory=dict)
    tickets: list[tuple[str, str, str, Ticket]] = field(default_factory=list)

    def who(self, e: AuditEvent) -> int:
        return self.res.person(e.actor_ref) or self.fallback

    def target(self, e: AuditEvent) -> tuple[Item, Place | None] | None:
        """The item and place an event is about, or None with a warning."""
        item = self.items.get(e.item_key or "")
        if item is None:
            if e.item_key:
                self.rep.warnings.append(f"{e.event} for {e.item_key} has no {ITEM_CREATED} — skipped")
            return None
        place = self.res.place(e.place_code)
        if e.place_code and place is None:
            self.rep.warnings.append(f"{e.item_key}: place {e.place_code} no longer exists — {e.event} skipped")
            return None
        return item, place


async def on_item_created(ctx: Replay, e: AuditEvent) -> None:
    p = e.payload or {}
    product = ctx.res.product(p.get("product_code"))
    if product is None:
        ctx.rep.warnings.append(f"{e.item_key}: unknown product — item skipped")
        return
    start = ctx.res.place(p.get("current_place_code"))
    item = Item(
        key=e.item_key,
        order_id=ctx.order.id,
        product_id=product.id,
        family=product.family,
        status=ItemStatus.in_progress,
        ordinal=p.get("ordinal") or 0,  # as issued — never re-numbered
        current_place_id=start.id if start else None,
        created_at=_ts(p.get("created_at")) or e.created_at,
    )
    ctx.session.add(item)
    await ctx.session.flush()
    ctx.items[e.item_key] = item
    ctx.rep.restored["items"] += 1


async def on_item_deleted(ctx: Replay, e: AuditEvent) -> None:
    reason = (e.payload or {}).get("reason") or "no reason given"
    ctx.rep.warnings.append(
        f"{e.item_key}: deleted on purpose ({reason}) — nothing recorded before the deletion is restored"
    )


async def on_tracked_in(ctx: Replay, e: AuditEvent) -> None:
    if (t := ctx.target(e)) is None:
        return
    item, place = t
    p = e.payload or {}
    visit = Visit(
        item_id=item.id, place_id=place.id, actor_id=ctx.who(e),
        attempt=p.get("attempt") or 1,
        started_at=_ts(p.get("tracked_in_at")) or e.created_at,
    )
    ctx.session.add(visit)
    await ctx.session.flush()
    ctx.visits[(item.key, place.code, visit.attempt)] = visit
    item.status = ItemStatus.in_progress
    item.current_place_id = place.id
    ctx.rep.restored["visits"] += 1


async def on_step_recorded(ctx: Replay, e: AuditEvent) -> None:
    if (t := ctx.target(e)) is None:
        return
    item, place = t
    p = e.payload or {}
    visit = ctx.visits.get((item.key, place.code, p.get("attempt") or 1))
    if visit is None:
        ctx.rep.warnings.append(f"{item.key} {place.code}: '{p.get('step_name')}' without its track-in — skipped")
        return
    step = await ctx.res.step(place, item, p.get("parent_name", ""), p.get("step_name", ""))
    if step is None:
        ctx.rep.warnings.append(
            f"{item.key} {place.code}: step '{p.get('step_name')}' not in the current definition — skipped"
        )
        return
    record = Record(
        item_id=item.id, step_id=step.id, visit_id=visit.id, actor_id=ctx.who(e),
        status=RecordStatus(p.get("status") or "done"),
        started_at=_ts(p.get("started_at")) or e.created_at,
        completed_at=_ts(p.get("completed_at")),
    )
    ctx.session.add(record)
    await ctx.session.flush()
    ctx.rep.restored["records"] += 1
    for v in p.get("values") or []:
        f = await ctx.res.field(step, v)
        if f is None:
            ctx.rep.warnings.append(
                f"{item.key} {place.code} '{step.name}': field '{v.get('code') or ''} "
                f"{v.get('title')}' not in the current definition — value skipped"
            )
            continue
        ctx.session.add(FieldValue(
            record_id=record.id, field_id=f.id,
            value_text=v.get("value_text"), value_num=v.get("value_num"), passed=v.get("passed"),
            created_at=record.completed_at or record.started_at,
        ))
        ctx.rep.restored["values"] += 1
    if tk := p.get("ticket"):  # the step failed: a ticket, the visit closed, the item held
        ticket = Ticket(
            item_id=item.id, origin_place_id=place.id, origin_record_id=record.id,
            root_cause=tk.get("root_cause"), raised_by=ctx.who(e),
            raised_at=_ts(tk.get("raised_at")) or e.created_at,
        )
        ctx.session.add(ticket)
        ctx.tickets.append((item.key, place.code, tk.get("raised_at") or "", ticket))
        visit.ended_at = _ts(tk.get("visit_closed_at")) or record.completed_at
        item.status = ItemStatus.on_hold
        if hold := ctx.res.place(tk.get("hold_place_code")):
            item.current_place_id = hold.id
        ctx.rep.restored["tickets"] += 1


async def on_tracked_out(ctx: Replay, e: AuditEvent) -> None:
    if (t := ctx.target(e)) is None:
        return
    item, place = t
    p = e.payload or {}
    if visit := ctx.visits.get((item.key, place.code, p.get("attempt") or 1)):
        visit.ended_at = _ts(p.get("tracked_out_at")) or e.created_at
    nxt = ctx.res.place(p.get("next_place_code"))
    item.current_place_id = nxt.id if nxt else None
    item.status = ItemStatus(p.get("status") or item.status.value)
    item.done_at = _ts(p.get("done_at")) or item.done_at  # milestone stamps as recorded


async def on_ticket_resolved(ctx: Replay, e: AuditEvent) -> None:
    if (t := ctx.target(e)) is None:
        return
    item, place = t
    p = e.payload or {}
    # The ticket is identified by where and when it was raised.
    match = next(
        (tk for k, code, raised, tk in ctx.tickets
         if k == item.key and code == place.code and raised == p.get("raised_at")),
        None,
    )
    if match is None:
        ctx.rep.warnings.append(f"{item.key}: resolution for an unknown ticket at {place.code} — skipped")
        return
    match.disposition = p["disposition"]  # + the status it implies (domain rule)
    match.resolution_notes = p.get("resolution_notes")
    ret = ctx.res.place(p.get("return_place_code"))
    match.return_place_id = ret.id if ret else None
    match.resolved_by = ctx.who(e)
    match.resolved_at = _ts(p.get("resolved_at")) or e.created_at
    item.status = ItemStatus(p.get("item_status") or item.status.value)
    cur = ctx.res.place(p.get("current_place_code"))
    item.current_place_id = cur.id if cur else None


async def on_output(ctx: Replay, e: AuditEvent) -> None:
    if (t := ctx.target(e)) is None:
        return
    item, _ = t
    p = e.payload or {}
    ctx.session.add(Output(
        item_id=item.id, kind=p["kind"], content=p.get("content") or "",
        made_by=ctx.who(e), made_at=_ts(p.get("made_at")) or e.created_at,
    ))
    ctx.rep.restored["outputs"] += 1


HANDLERS: dict[str, Callable[[Replay, AuditEvent], Awaitable[None]]] = {
    ITEM_CREATED: on_item_created,
    ITEM_DELETED: on_item_deleted,
    "item.tracked_in": on_tracked_in,
    "step.recorded": on_step_recorded,
    "item.tracked_out": on_tracked_out,
    "ticket.resolved": on_ticket_resolved,
    "output.printed": on_output,
}
```

**The run.** Refuse → resolve people → the order (first seeds, last wins) →
replay → derived state → commit or roll back:

```python
async def _fallback_actor(session, res: Resolver, ref: str | None, rep: Report) -> int | None:
    if ref:
        uid = res.person(ref)
        if uid is None:
            rep.warnings.append(f"REFUSED: no user {ref}")
        return uid
    admin = (await session.exec(
        select(User).where(User.role == "admin").order_by(col(User.id))
    )).first()
    if admin is None:
        rep.warnings.append("REFUSED: no admin user to attribute unknown actors to")
        return None
    return admin.id


async def _rebuild_order(session, res: Resolver, key: str, events, item_keys, rep) -> Order:
    order_events = [e for e in events if e.event.startswith("order.")]
    first_item = next((e for e in events if e.event == ITEM_CREATED), None)
    base = order_events[0].payload if order_events else None
    if base is None:
        rep.warnings.append(
            "No order events (created before the audit trail?) — order rebuilt "
            "from its first item; check its fields after"
        )
    src = base or {
        "product_code": (first_item.payload or {}).get("product_code") if first_item else None,
        "quantity_planned": len(item_keys),
    }
    product = res.product(src.get("product_code"))
    order = Order(
        code=key,
        product_id=product.id if product else None,
        quantity_planned=src.get("quantity_planned") or len(item_keys),
        active=False,  # never steal the line's active slot
        created_at=_ts(src.get("created_at")) or events[0].created_at,
        **{f: src.get(f) for f in ORDER_FIELDS},
    )
    session.add(order)
    await session.flush()
    rep.restored["orders"] += 1
    return order


def _apply_last(order: Order, res: Resolver, events, rep: Report) -> None:
    """The order as it last stood — an admin may have amended any field.
    Provenance keys (`via`) are not replayed."""
    order_events = [e for e in events if e.event.startswith("order.")]
    if not order_events:
        return
    last = order_events[-1].payload or {}
    order.quantity_planned = last.get("quantity_planned") or order.quantity_planned
    for f in ORDER_FIELDS:
        if f in last:
            setattr(order, f, last[f])
    if product := res.product(last.get("product_code")):
        order.product_id = product.id
    if any(e.event == ORDER_DELETED for e in order_events):
        rep.warnings.append("The order was deleted at some point in its history")
    if any(e.event == ORDER_CLEARED for e in order_events):
        rep.warnings.append("Its items were cleared at some point — only items created after the last clear are restored")


async def restore(session: AsyncSession, key: str, *, apply: bool, fallback_ref: str | None) -> Report:
    rep = Report()
    events = await lifetime_events(session, key)
    if not events:
        rep.warnings.append(f"No audit events for {key} — nothing to restore")
        return rep
    rep.events.update(e.event for e in events)

    # --- refuse to merge into existing data ------------------------------ #
    existing = (await session.exec(select(Order).where(Order.code == key))).first()
    if existing is not None:
        n = (await session.exec(
            select(func.count()).select_from(Item).where(Item.order_id == existing.id)
        )).one()
        if n:
            rep.warnings.append(f"REFUSED: {key} exists with {n} item(s) — a restore never merges")
            return rep
    item_keys = [e.item_key for e in events if e.event == ITEM_CREATED]
    clash = (await session.exec(
        select(Item.key).where(col(Item.key).in_(item_keys))
    )).all() if item_keys else []
    if clash:
        rep.warnings.append(
            f"REFUSED: {len(clash)} item key(s) already exist "
            f"({', '.join(sorted(clash)[:5])}…) — a restore never overwrites"
        )
        return rep

    res = Resolver(session)
    await res.load()
    fallback = await _fallback_actor(session, res, fallback_ref, rep)
    if fallback is None:
        return rep
    missing = sorted({e.actor_ref for e in events if e.actor_ref and res.person(e.actor_ref) is None})
    if missing:
        rep.warnings.append(f"Users no longer present, attributed to the fallback: {', '.join(missing)}")

    order = existing or await _rebuild_order(session, res, key, events, item_keys, rep)
    _apply_last(order, res, events, rep)

    # --- replay ----------------------------------------------------------- #
    ctx = Replay(session, res, rep, order, fallback)
    for e in events:
        if e.event.startswith("order."):
            continue  # applied above: the first seeds the row, the last one wins
        handler = HANDLERS.get(e.event)
        if handler is None:
            rep.warnings.append(f"{e.event}: no replay branch — skipped")
            continue
        await handler(ctx, e)

    for item in ctx.items.values():
        session.add(item)
    await session.flush()
    await order_service.rederive_status(session, order)  # derived, never replayed
    order.active = False
    session.add(order)

    if apply:
        await session.commit()
    else:
        await session.rollback()  # the dry run rehearsed every insert and constraint
    return rep


def _print(rep: Report, key: str, *, applied: bool) -> None:
    print(f"\nAudit events for {key}:")
    for name, n in sorted(rep.events.items()):
        print(f"  {name:<22} {n}")
    print("\nRestored:" if applied else "\nWould restore:")
    for name, n in rep.restored.items():
        print(f"  {name:<22} {n}")
    if rep.warnings:
        print(f"\nWarnings ({len(rep.warnings)}):")
        for w in rep.warnings:
            print(f"  - {w}")
    print()
    if not applied and rep.restored:
        print("Dry run — nothing written. Re-run with --apply.")
    elif applied and rep.restored:
        print("Written. The order is restored inactive — make it active again if work should continue on it.")


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild one order from the audit trail.")
    parser.add_argument("key")
    parser.add_argument("--apply", action="store_true", help="Write it (default: dry run)")
    parser.add_argument("--fallback-actor", help="Natural key of the user that events of since-deleted users go to (default: first admin)")
    parser.add_argument("--yes", action="store_true", help="Skip the --apply confirmation")
    args = parser.parse_args()

    env = get_app_env()
    host = get_settings().DATABASE_URL.rsplit("@", 1)[-1]  # never print the credentials
    print(f"Target: {env} ({host})")
    if args.apply and not args.yes:
        answer = input(f"Restore {args.key} into {env} ({host})? Type 'yes': ")
        if answer.strip().lower() != "yes":
            print("Aborted.")
            return
    async with async_session_maker() as session:
        rep = await restore(session, args.key, apply=args.apply, fallback_ref=args.fallback_actor)
    _print(rep, args.key, applied=args.apply)


if __name__ == "__main__":
    asyncio.run(_main())
```

```make
# Rebuild one order from the audit trail (scripts/restore_aggregate.py).
# Dry run by default; APPLY=1 writes it (asks for confirmation). Refuses if any
# of its keys already exist.   make restore KEY=ORD-0042 ENV=prod APPLY=1
restore:
	cd backend && APP_ENV=$(ENV) uv run python -m scripts.restore_aggregate $(KEY) $(if $(APPLY),--apply,)
```
