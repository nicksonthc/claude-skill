---
name: system-status-popover
description: Honest system-status indicator for a SPA + API app — a small beating status dot in the shell that opens a popover detailing backend health (endpoint, real upstream, DB, environment, version + commit, build time, latency, last check), realtime Socket.IO state (connected, transport, socket id), and frontend build provenance, backed by a /health endpoint and a git-SHA/build-time pipeline through Docker build args. Use when asked to show the backend / socket.io version and status in the frontend, add a health or connection indicator, display build info / app version in the UI, add an honest "Live" badge, or wire version + commit from git through Docker into both backend and frontend.
---

# System Status Popover

Harvested from a production shop-floor SPA. Proven on React 19 · Vite 6 ·
Tailwind v4 · shadcn/ui (Popover/Button) · socket.io-client v4 · FastAPI
backend — but any backend that returns the health JSON shape works, and the
popover primitive is swappable.

## Moving parts

1. **`GET /api/health`** — unauthenticated liveness + DB probe + build
   provenance (`status, database, version, commit, build_time, environment`).
2. **Provenance pipeline** — git SHA + ISO build time computed on the build
   host → Docker `--build-arg` → backend env vars and Vite `VITE_*` vars →
   surfaced by both the endpoint and the bundle.
3. **`usePolling`** — interval fetch with a race guard, pause, manual refetch.
4. **Socket hooks** — `useSocketConnected` + `useSocketTransport`. Optional:
   an app with no realtime feed drops the whole Realtime section. The full
   realtime suite (provider, rooms, echo suppression) is its own skill:
   `socketio-realtime-hooks`.
5. **Status language** — five tones (`ready / live / hold / fault / idle`) +
   `StatusChip`; status is the one place the UI spends color.
6. **`SystemStatus`** — compact trigger (dot beats when all-OK, pulses when
   not) → popover with Backend API / Realtime / Frontend sections and a
   footer showing the poll cadence + a "Check now" button.
7. **`LiveBadge`** — the same honesty reused anywhere else ("Live" only while
   the socket really is connected; "Reconnecting" otherwise).

## Workflow

1. Read `REFERENCE.md` — numbered building blocks matching the list above.
2. Backend: add the health endpoint. Version comes from the package manifest,
   commit + build time from env vars (defaults `"dev"` / `""` for local dev).
3. Build pipeline: compute `GIT_SHA` / `BUILD_TIME` in the build script **on
   the host** and pass as `--build-arg`; in the frontend Dockerfile the
   `ARG`→`ENV` lines go **before** `npm run build`.
4. Vite: `define` `__APP_VERSION__` (package.json) and `__API_PROXY_TARGET__`
   (dev serve only); declare both in `vite-env.d.ts`.
5. Frontend: drop in `usePolling`, the status tokens (or map to the repo's
   existing design tokens), `StatusChip`, `SystemStatus`, `LiveBadge`.
   No socket? Delete the Realtime section and the socket hooks.
6. Mount the trigger in the app shell — full row in a sidebar footer,
   `compact` icon button in a header.
7. Verify all three states: dev shows the proxy upstream and commit `dev`;
   kill the backend → "Unreachable"/"Offline"; stop the DB → "DB down"/
   "Degraded"; reconnect and watch it recover on the next poll.

## Principles

- **Honest, never decorative.** Every value shown is measured or derived —
  connection state from real socket events, latency from a real round-trip,
  upstream from real config. If it can't be known, show "—", not a guess.
- **Three states, not two.** `health === null && error === null` is
  "Checking", distinct from both OK and failed — the UI never claims "down"
  before the first probe returns.
- **Degraded ≠ offline.** API up but DB down or socket reconnecting →
  "Degraded" (amber); API and socket both gone → "Offline" (rose).
- **Build info is not a health state** — the Frontend section gets no
  StatusChip; a version can't be "up".
- Extension points a new repo fills in: the health-field mapping, the status
  palette classes, the popover primitive, where the socket lives (or that
  there is none), the poll interval, the dev proxy target.

## Pitfalls (each already paid for once)

- **Vite inlines `VITE_*` at build time** — the `ARG`→`ENV` lines must sit
  above `RUN npm run build` in the Dockerfile, or prod silently shows "dev".
- **The Docker build context has no `.git`** — compute the SHA/time in the
  build script on the host, never inside the Dockerfile. Append `-dirty`
  when the tree has uncommitted changes so a hotfix build is identifiable.
- **Python + uv:** `importlib.metadata` can't see a build-system-less
  (virtual) project — read `pyproject.toml` directly, anchored on `__file__`
  so it's CWD-independent, and `lru_cache` it.
- **Environment can lie:** if the prod compose doesn't set `APP_ENV` (or your
  equivalent), the endpoint reports the local default. Set it in the compose
  file; keep the image itself environment-neutral.
- **Polling races:** an older in-flight response can land after a newer one —
  the `seq` counter in `usePolling` drops stale results. The fetcher must be
  `useCallback`-memoized or the effect tears down every render.
- **Pause without resetting:** the interval reads `pausedRef.current`, not
  the prop, so toggling pause doesn't restart the timer.
- **Transport upgrades:** Socket.IO starts on `"polling"` and upgrades — read
  `socket.io.engine.transport.name` and re-read on `engine.on("upgrade")`;
  reset to `null` on disconnect.
- **Don't lie about the endpoint:** the browser always calls same-origin
  (Vite proxy in dev, nginx in prod). Show both the calling origin *and* the
  true upstream — `__API_PROXY_TARGET__` is inlined only on dev serve and is
  `""` in a build, which selects the prod ("nginx → backend") label.
- **Display constants drift:** the `SOCKET_PATH` shown in the popover is
  display-only — keep it next to a comment naming the real `io({ path })` it
  must match.
- **Health returns 200 even when the DB is down** — the popover needs the
  degraded payload to render details; only a dead process is a non-200. Keep
  the endpoint unauthenticated.
- **Reduced motion:** the beat animation must be disabled under
  `prefers-reduced-motion: reduce` — shop-floor PCs often have animations off.
- Floor measured latency at 1 ms — `performance.now()` deltas can round to 0
  and "0 ms" reads as broken.
