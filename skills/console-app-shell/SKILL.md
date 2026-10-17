---
name: console-app-shell
description: App shell for a multi-role internal tool, operator console or shared kiosk in React — one nav registry behind a role-filtered sidebar and phone strip, per-terminal page reordering that survives releases, collapsible groups that re-open for the active page, registry-fed hub pages at stable URLs, a hover-intent account menu that stays click-only on touch, and settings split into validated server-side line settings and clamped per-terminal preferences behind one dialog with scope badges and a guarded close. Use when building or restructuring an internal app's sidebar or navigation, letting each terminal arrange its own pages, adding a management/admin hub with sub-pages, adding a settings dialog or runtime-editable settings, or deciding whether a knob is a per-device preference or a shared setting.
---

# Console App Shell

Harvested from a production shop-floor app whose kiosks are shared by
operators, supervisors and admins. Proven on React 19 · react-router 7 ·
shadcn/ui (Radix) · Tailwind v4 · FastAPI + SQLModel for the settings store.

## The idea in one line

**One registry, many renderings; one decision per knob.** The nav, the phone
strip, the reorder list and the hub pages all read one list, and every
setting is placed by *who it affects*: this browser (a preference in
localStorage) or everyone (a validated row on the server).

## Moving parts

1. **Nav registry** — entries `{to, label, icon, end, badge?, roles?/adminOnly?,
   children?}`, where a child is a page or an action (a tour); `canSee(user,
   gate)` filters, and a group with no visible child hides itself.
2. **Per-terminal order** (`navOrder.ts`) — an external store of route keys in
   localStorage; `applyNavOrder` merges it forgivingly; a Reorder mode with
   live drag-and-drop plus up/down buttons, saved on every move, Reset and Esc.
3. **Groups** — open by default, fold remembered per terminal, re-opened by
   the active route, animated with `grid-template-rows`; flattened on phones.
4. **Hub pages** — a registry `{slug, title, icon, subtitle, adminOnly?}` feeds
   the sidebar group and `/hub/:slug`; lock cards for typed URLs, redirects
   for unknown slugs and old addresses.
5. **Account menu** — identity, hover intent (140 ms open / 240 ms close),
   click-only on touch, no focus theft when hover-opened; entries follow the
   backend's gates; sign-out wipes the session's local history.
6. **Settings, two stores** (`SETTINGS.md`) — line-wide: a key/value string table with typed
   accessors, defaults in code, per-key validation that normalises, per-key
   role gates, a cached hot-path flag. Per-terminal: a spec'd, clamped
   localStorage store. One dialog: a section list showing current values,
   scope badges, mounted-but-hidden sections, a save bar, a guarded close.
7. **Terminal identity** (optional) — the work position a PC is locked to, and
   view choices kept per screen.

## Workflow

1. **Write the registry** from the route table and both gates (route guard +
   backend role check) — REFERENCE §1.
2. **Render it** three ways: desktop sidebar with groups (§3), phone strip,
   reorder list (§2). Put the brand, a status row (`system-status-popover`) and
   the account menu (§5) in the aside.
3. **Hubs** (§4): one registry entry plus one body per page; redirect old URLs.
4. **Settings** (`SETTINGS.md`): for each knob ask "does it change anything for another
   terminal, a record or a document?" Yes → server setting with a validator
   and a role gate. No → terminal preference with a spec.
5. **Verify** as every role: the nav shows exactly what the backend allows; a
   typed URL to a forbidden page shows a lock card; a page added after an
   order was saved still appears; a fresh database (no settings rows) renders
   every default; closing with an edit pending asks first.

## Principles

- **Frontend gates are a courtesy; the backend gate is the truth.** Mirror it,
  and say so in a comment beside each gate.
- **Per terminal is a real scope.** On a shared kiosk, layout, poll rates and
  view choices belong to the device, not the account; sign-out wipes what
  belongs to the person.
- **Forgiving persistence.** Stored state never hides a page a release added;
  malformed storage falls back to defaults; every storage call is wrapped, so a
  locked-down profile still works for the session.
- **Defaults live in code.** A setting works before its row exists; the list
  endpoint returns what exists and the client fills the rest.
- **The list is the overview.** Most visits to Settings are to check a value, so
  each section shows its current value beside its name.

## Pitfalls (each already paid for once)

- **Save the hidden entries too.** Append the role-hidden entries after the
  visible ones when saving an order, or an operator's reorder shuffles an
  admin's view of the same terminal.
- **Match reorder entries by identity**, not copies, and render no links in
  reorder mode, or a drag turns into a navigation.
- **Reorder live in `onDragOver`** so what the user sees on drop is what gets
  saved.
- **Re-open a group whenever its child route is current**, or a folded group
  hides the active page.
- **Animate folds with `grid-rows-[0fr]` → `[1fr]`**, not measured heights.
- **A menu that opened on hover must not steal the caret** from the field the
  operator is typing in — `preventDefault` on open-autofocus for hover opens.
- **Touch has no hover**: gate the intent timers on `pointerType === "mouse"`.
- **`GET /settings/{key}` 404s on a fresh database** — load the list; a missing
  row is a default, not an error.
- **Keep every section mounted and toggle `hidden`** — unmounting one loses a
  half-typed edit.
- **Inline `onDirty` callbacks loop the sections' effects** — build stable
  per-section setters once (`useMemo`) that no-op when nothing changed.
- **Normalise at the boundary.** Store `"true"`/`"false"` after a strict parse,
  so hot-path readers never guess at what was typed.
- **A per-request flag read must be cached** (in-process, TTL, dropped on
  write) **and must never raise**; with several workers the TTL is the
  worst-case lag — keep it short (the source used 15 s). The access-log switch
  in `request-error-logging` is the canonical consumer.
- **Clamp preferences on load as well as on set** — an old release or a hand
  edit can leave a stored value out of range.
- **`storage` events fire only in other tabs** — the locked-position setter
  also dispatches its own window event for the current tab.

## Extension points a new repo fills in

- **The registry:** routes, icons, gates, badges, group actions.
- **Roles:** the union, `canSee`, the hub's role set, which settings are
  admin-only.
- **Hub items and bodies;** the legacy URLs to redirect.
- **Setting keys:** defaults, descriptions, validators, typed accessors.
- **Preference specs:** label, help, default, min, max, presets.
- **Storage namespace** (`app.ui.*`) and what sign-out wipes.
- **Hosted pieces:** the status row (`system-status-popover`), the bell
  (`toast-notification-history`), hotkeys (`keyboard-first-hotkeys`), the tour
  action (`guided-product-tour`), motion (`ui-motion-system`).
