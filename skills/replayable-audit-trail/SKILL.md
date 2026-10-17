---
name: replayable-audit-trail
description: Audit trail that can rebuild what it records — one append-only event per write, staged in the same transaction; name-based payloads (codes and names, never ids, no foreign keys) so a restore script replays a wiped record and its children onto reference data reseeded with new ids; deletions that take a required reason and a snapshot of what went; and a Deletion log read back from those events. Use when adding an audit trail, audit log or change history to a backend, recording who did what, making deletes, wipes or reseeds recoverable ("restore the batch from the audit log"), requiring a reason to delete, or building a "what was deleted, by whom and why" page.
---

# Replayable Audit Trail

Harvested from a production shop-floor app, where an admin may delete or clear a
whole production batch and a reseed renumbers the reference data — and neither may
lose a record for good. Proven on Python 3.12 · FastAPI 0.136 · SQLModel 0.0.38
(async SQLAlchemy, asyncpg) · Alembic · PostgreSQL · React 19 + shadcn/ui; the
contract ports to any ORM.

Words used below: the **aggregate** is the unit of restore (in the source: a
batch, keyed by its job order no.); **items** are its children with their own
natural key (a unit, keyed by serial); **reference data** is what a reseed rebuilds
(stations, steps, fields); **people** carry a stable natural key (employee no.).

## Moving parts

1. **Event table** — append-only, no foreign keys in or out. Indexed filter keys
   (event, aggregate key, item key, created_at), the actor as a plain id plus their
   natural key, a JSON payload.
2. **`record()`** — stages one event on the caller's session after the change is
   flushed, before the caller commits. Committed change ⇔ event.
3. **Payload conventions** — codes and names only; aggregate events carry the full
   current definition; child rows carry natural keys (item + place + attempt; a
   ticket by where and when it was raised); UTC ISO times; values and verdicts
   verbatim; provenance keys (`via`) that replay ignores.
4. **Deletion contract** — a required reason, a snapshot of every item as it was
   and the realtime "gone" payload, both built before the rows go; the UI asks for
   the reason plus the key typed (or scanned) again.
5. **Restore script** — selects the aggregate's current lifetime, refuses to merge,
   re-links names to today's ids, replays through an event → handler registry,
   recomputes derived state, restores inactive. Dry run by default.
6. **Deletion log** — the deletion events read back as rows: when, action,
   aggregate, keys, state when deleted, detail, who, reason; page + exports.
7. **Read API** — the timeline of one aggregate or item, oldest first, managers only.
8. **Purge exclusion** — the audit table stays out of every reset / reseed / wipe,
   and its migration tolerates a startup `create_all` that got there first.

## Workflow

1. Name the aggregate, items, reference data and people keys; pick a natural key
   for every child row a replay must find again.
2. Table + migration (REFERENCE §1), `record()` (§2).
3. Grep the services for every `commit` and give each write path one `record()`.
   Fill in the event catalogue (§3): event → payload keys → replay handler.
4. Deletions (§4): reason, snapshot, capture-before-delete — server and UI.
5. Restore script + CLI target (`RESTORE.md`). Rehearse on a staging copy: delete an
   aggregate, dry-run, apply, compare with a backup.
6. Deletion log (§6), read API (§7), purge exclusion (§8).
7. Paste the write-path rule (§9) into the project's CLAUDE.md / AGENTS.md so the
   next feature keeps the contract.

## Principles

- **Same transaction or it is fiction** — after the commit it can miss, before it can lie.
- **Names outlive ids** — a reseed renumbers rows; codes survive and re-resolve.
- **A restore fills a gap, never merges** — any existing key refuses the whole run.
- **The aggregate comes back; removals inside it stay removed** — an item deleted or
  cleared with a reason is never resurrected.
- **The snapshot is the only memory of a delete** — record what a reviewer needs.
- **Derived state is recomputed, never replayed** (statuses that follow from counts).
- **Append, don't edit** — corrections append rows; only whole mistaken records go.
- **It is not a backup.** Same database: dropping it takes the trail along.

## Pitfalls (each already paid for once)

- **Stage after the flush, before the commit** — ids and defaults the payload
  needs exist only after `flush()`; the commit belongs to the caller.
- **A rejected attempt worth keeping commits before it raises.** A failed retry is
  evidence: commit its record and event, then raise the 409, or the rollback
  erases both.
- **Renames are recorded under the new key** with `previous_key`. The restore walks
  back and takes the old key's events only up to the rename — after it, the old
  key may belong to another aggregate.
- **Keys get reused.** Each key's lifetime starts at its latest create or rename
  onto it; `RESTORE.md` trims per key. The source trimmed across all keys at once, cutting an
  aggregate renamed onto a once-deleted key (harvest finding).
- **A key renamed away has no closing event under its own name** (harvest
  finding) — before restoring a key, check no later rename names it `previous_key`.
- **Removals cut by position**: item events before the latest "items cleared" go;
  an item's events up to its deletion go, but the deletion event stays so the
  report can say why the item is not coming back.
- **Capture, delete, record, commit, emit.** Snapshots (grouped queries, never one
  per item) and realtime payloads come first; the emit goes after the commit, so a
  rollback announces nothing.
- **A payload key without a replay branch is silently lost** — a later-added
  reference no. came back blank until its branch was added. Writes with no event
  at all (saved report remarks deleted with their batch) cannot be restored.
- **First event seeds, last event wins**: the first aggregate event builds the row,
  the last one's fields apply, and it comes back inactive — a singleton flag (the
  active batch) is never stolen. Pre-trail aggregates rebuild from their first item.
- **Resolve with fallbacks, skip with a warning** — a step by its recorded parent
  name, else any parent at the same place (renamed); a field by code, else title.
- **People by natural key**; since-deleted users go to a named fallback actor, and
  the run lists who was missing.
- **Refuse on existing item keys and on an existing aggregate with items.** The
  source checks only the item keys, though its docs promise both (harvest finding).
- **The dry run is the real code path** — every insert and flush, then a rollback.
  `--apply` prints the environment and host (credentials stripped), wants `yes`.
- **Purge lists leave the audit table out**, truncating children before parents
  with no `CASCADE`, which would silently take out a table added later.
- **Migration vs startup `create_all`**: check `has_table` first, or the deploy
  fails when the new image starts before the migration.
- **Ordinals from `max()+1`, never `count()+1`** — a deletion would reissue one.
- **Old events lack new keys**: every reader defaults (blank reason, no snapshot).

## Extension points

- The four key kinds above, and the place code on child events.
- The event catalogue, the replay handlers, the aggregate's replayed fields and
  the derived-state recompute.
- Resolver lookups and fallbacks; the snapshot builder's counts and bindings.
- Roles: who reads the trail, who deletes an item vs an aggregate.
- Deletion log wording, plant timezone, PDF/CSV via the repo's report layer.

Composes with `request-error-logging` (HTTP traffic and failures — separate
tables, separate purpose), `console-app-shell` (its management hub hosts the
Deletion log), `socketio-realtime-hooks` (the removal emit skips the deleting tab)
and `keyboard-first-hotkeys` (delete buttons stay off the scan-gun focus chain).
