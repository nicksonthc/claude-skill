---
name: socketio-realtime-hooks
description: React hook suite for a Socket.IO realtime feed — one authenticated app-wide connection in a context provider, useSocketEvent (listeners that never rebind), useSocketRoom (auto re-join after reconnect), an echo-suppression contract so a tab is never told to re-fetch its own change (X-Client-Id header ↔ skip_sid), live presence (who is at which station/terminal), and the "socket is the fast path, a slow poll self-heals" composition. Use when adding Socket.IO / websocket realtime updates to a React app, live data that should push instead of poll, room-scoped subscriptions, "other users see changes instantly", duplicate refreshes after a user's own mutation, or presence / who's-online rosters.
---

# Socket.IO Realtime Hooks

Harvested from a production multi-terminal shop-floor app. Proven on React 19
· socket.io-client v4 · python-socketio on FastAPI (mounted at `/ws`), Vite
dev proxy + nginx in prod. The server side is sketched for FastAPI but the
contract is stack-agnostic.

## Moving parts

1. **`SocketProvider`** — ONE connection for the whole authenticated app,
   created on sign-in, closed on sign-out. Same-origin with an explicit
   `path`; the session token rides the handshake `auth` payload.
2. **`useSocket` / `useSocketConnected`** — the raw socket, and honest
   connection state (see the `system-status-popover` skill, which consumes
   both for its status popover and LiveBadge).
3. **`useSocketEvent(event, handler)`** — subscribe for the component's
   lifetime; the handler lives in a ref so it always sees fresh render state
   without ever rebinding the listener.
4. **`useSocketRoom(data)`** — join room(s) while mounted, automatically
   re-joining after a reconnect; conditional join is a no-op.
5. **Echo suppression** — each tab tags its REST calls with its socket id
   (`X-Client-Id`); the server passes it as `skip_sid` when emitting, so the
   originating tab (which already refreshed off the HTTP response) is never
   told to re-fetch its own change.
6. **Presence** (optional) — a terminal announces what it is manning
   (`useAnnounceStation`); the server keeps an in-memory roster keyed by sid
   and pushes the full roster on every change.
7. **Fast path + self-heal** — consumers take socket events as the fast path
   and keep a *slow* poll (30s+) that seeds the first render and heals a
   client whose socket silently dropped (`useStationPresence` shows the
   composition; `usePolling` lives in `system-status-popover`'s REFERENCE).

## Workflow

1. Read `REFERENCE.md` — blocks numbered as above.
2. Mount `SocketProvider` inside the auth boundary so the token exists and
   the socket dies with the session.
3. Proxy the socket path in dev (`ws: true` in Vite) and prod (nginx with
   upgrade headers) so the browser connects same-origin — no CORS.
4. Define the room vocabulary (extension point): what a client can join —
   per-record, per-terminal, an overview room — and the join payload shape.
   Server-side, `join`/`leave` handlers map payload → room names.
5. Wire echo suppression end to end: provider tags/untags the client id on
   connect/disconnect → API client sends the header → routes hand it to the
   emit helpers → emits pass `skip_sid`.
6. Consumers: `useSocketRoom` + `useSocketEvent` for the fast path, plus a
   slow poll of the matching REST read for seed + self-heal.
7. Presence if wanted: announce hook in the app shell, roster hook wherever
   the roster shows.

## Principles

- **One socket per app, not per component.** Components share it via context
  and scope themselves with rooms and event subscriptions.
- **The socket is an optimization, never the source of truth.** Every
  realtime view must render correctly from REST alone; events only make it
  fast. That's what the slow poll guarantees.
- **Realtime is best-effort on the server too**: emit helpers never raise —
  the DB change is already committed; a lost event costs one poll interval.
- **Rooms follow meaning, not pages** (e.g. presence follows the terminal's
  *lock*, not the page on screen — a user who navigates away still shows as
  manning their station). Decide what each room means before wiring it.

## Pitfalls (each already paid for once)

- **Handler in a ref, listener bound once.** Binding the handler directly
  re-subscribes on every render; capturing state in a bound-once listener
  goes stale. The ref pattern (`ref.current = handler` each render, listener
  calls `ref.current`) gets both right.
- **Everything re-joins on `"connect"`, not just on mount** — a reconnect is
  a *new session* server-side (new sid, room memberships gone). Rooms
  re-join, presence re-announces; anything emitted only on mount silently
  dies at the first network blip.
- **Object deps need a stable key**: `useSocketRoom` keys its effect on
  `JSON.stringify(data)` — an inline `{ station_code }` object is a fresh
  reference every render and would join/leave in a loop.
- **Leave on unmount, but skip the goodbye when the socket is already
  gone** — the server drops the sid on disconnect anyway, and emitting on a
  dead socket buffers junk.
- **The client id is null before the socket connects** — then everyone,
  the originator included, gets the echo. That must be harmless: design the
  echo as "re-fetch", never "apply this delta twice".
- **The id changes on every reconnect** — tag on `"connect"`, untag on
  `"disconnect"`; a stale id would suppress someone else's refresh.
- **Vite proxy needs `ws: true`** on the socket path or the upgrade fails
  and the client silently stays on HTTP long-polling; nginx needs the
  `Upgrade`/`Connection` headers for the same reason.
- **The `path` must match the server mount** (`/ws` mount → client path
  `/ws/socket.io`). A mismatch isn't an error — just an endless 404 retry.
- **Authenticate the handshake** (`auth: { token }`, validated in the
  server's `connect` handler) — a socket that skips REST middleware is
  otherwise an open door to every room.
