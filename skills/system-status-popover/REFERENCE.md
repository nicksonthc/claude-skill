# system-status-popover — building blocks

Genericized from the source project. `@/` is a Vite path alias to `src/`;
`cn` is the usual clsx+tailwind-merge helper; Popover/Button are shadcn/ui —
swap for the target repo's equivalents. Sections are numbered to match
SKILL.md's "Moving parts".

## 1. Backend health endpoint

FastAPI shown; any stack works if it returns this JSON shape.

```python
# app/api/routes/health.py
from fastapi import APIRouter, Depends
from sqlalchemy import text

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    """Liveness + DB connectivity probe, plus build provenance.

    Returns 200 even when the DB is down — the UI needs the degraded payload
    to render details; only a dead process is a non-200. Unauthenticated."""
    settings = get_settings()
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok",
        "database": "up" if db_ok else "down",
        "version": get_app_version(),       # package manifest (below)
        "commit": settings.GIT_SHA,         # env var, default "dev"
        "build_time": settings.BUILD_TIME,  # env var, ISO 8601 UTC, "" in dev
        "environment": get_app_env(),       # e.g. APP_ENV: local|staging|prod
    }
```

```python
# app/core/config.py
@lru_cache
def get_app_version() -> str:
    """Semantic version from pyproject.toml (`[project] version`) — bump it
    there per release. Read from the file directly (anchored on __file__, so
    CWD-independent): uv treats a build-system-less project as virtual and
    never installs it, so importlib.metadata can't see it."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with pyproject.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0"
```

Node backend: `version` from `require("./package.json").version`, commit and
build time from `process.env.GIT_SHA` / `process.env.BUILD_TIME`.

Frontend type + API call (adapt to the repo's fetch wrapper):

```ts
export interface Health {
  status: string
  database: "up" | "down"
  version?: string
  commit?: string
  build_time?: string   // ISO 8601 UTC
  environment?: string
}

export const api = {
  health: () => request<Health>("GET", "/api/health"),
}
```

## 2. Build-provenance pipeline

Build script (on the host — the Docker build context has no `.git`):

```bash
# Build provenance: short git SHA (-dirty if the project dir has uncommitted
# changes) and ISO 8601 UTC build time. Baked into both images via
# --build-arg and surfaced in the SystemStatus popover + /api/health.
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ -n "$(git status --porcelain -- . 2>/dev/null)" ]; then
  GIT_SHA="${GIT_SHA}-dirty"
fi
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

docker build \
  --build-arg GIT_SHA="$GIT_SHA" --build-arg BUILD_TIME="$BUILD_TIME" \
  -t "$REGISTRY/$IMAGE:$TAG" .
```

Backend Dockerfile:

```dockerfile
# Build provenance, passed by the build script (defaults for direct builds).
# Read by the config module and exposed via /api/health.
ARG GIT_SHA=dev
ARG BUILD_TIME=""
ENV GIT_SHA=$GIT_SHA \
    BUILD_TIME=$BUILD_TIME
```

Frontend Dockerfile — **order matters**, Vite inlines `VITE_*` at build time:

```dockerfile
# Vite inlines VITE_* env vars into the bundle at build time, so these
# must be set BEFORE the build step.
ARG GIT_SHA=dev
ARG BUILD_TIME=""
ENV VITE_GIT_SHA=$GIT_SHA \
    VITE_BUILD_TIME=$BUILD_TIME

RUN npm run build
```

vite.config.ts:

```ts
import pkg from "./package.json"

// Where the dev server forwards /api (and /ws). Also inlined as
// __API_PROXY_TARGET__ so the SystemStatus popover can name the real backend
// instead of the proxy the browser actually talks to.
const DEV_PROXY_TARGET = "http://localhost:8000" // ← the backend dev port

export default defineConfig(({ command }) => ({
  // Compile-time constants: the app's own semver from package.json and (dev
  // serve only) the proxy upstream. Both shown in the SystemStatus popover.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __API_PROXY_TARGET__: JSON.stringify(
      command === "serve" ? DEV_PROXY_TARGET : "",
    ),
  },
  server: {
    proxy: {
      "/api": { target: DEV_PROXY_TARGET, changeOrigin: true },
      // Socket.IO — ws:true upgrades the connection. Omit if no realtime.
      "/ws": { target: DEV_PROXY_TARGET, changeOrigin: true, ws: true },
    },
  },
}))
```

vite-env.d.ts:

```ts
/// <reference types="vite/client" />

/** Injected by the `define` block in vite.config.ts (package.json version). */
declare const __APP_VERSION__: string

/** Dev-server proxy upstream for /api, injected by vite.config.ts.
 *  Empty string in a production build — there nginx does the proxying. */
declare const __API_PROXY_TARGET__: string

interface ImportMetaEnv {
  /** Baked in as Docker build args by the build script; absent in dev. */
  readonly VITE_GIT_SHA?: string
  readonly VITE_BUILD_TIME?: string
}
```

## 3. usePolling

```ts
// src/hooks/usePolling.ts
import { useCallback, useEffect, useRef, useState } from "react"

type PollingResult<T> = {
  data: T | null
  error: string | null
  loading: boolean
  refetch: () => Promise<void>
}

/**
 * Re-fetch `fetcher` on an interval. Pass a `fetcher` memoized with useCallback
 * (keyed on its inputs). While `paused` is true the interval skips fetching so
 * an open dialog / in-progress edit isn't clobbered; call `refetch()` after a
 * mutation to refresh immediately.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  opts?: { enabled?: boolean; paused?: boolean },
): PollingResult<T> {
  const { enabled = true, paused = false } = opts ?? {}
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Monotonic sequence: an older in-flight response that lands after a newer
  // one is dropped instead of overwriting it.
  const seq = useRef(0)
  // Read via ref inside setInterval so toggling pause doesn't reset the timer.
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  const refetch = useCallback(async () => {
    const mySeq = ++seq.current
    setLoading(true)
    try {
      const result = await fetcher()
      if (mySeq === seq.current) {
        setData(result)
        setError(null)
      }
    } catch (e) {
      if (mySeq === seq.current) setError((e as Error).message)
    } finally {
      if (mySeq === seq.current) setLoading(false)
    }
  }, [fetcher])

  useEffect(() => {
    if (!enabled) return
    void refetch()
    const id = setInterval(() => {
      if (!pausedRef.current) void refetch()
    }, intervalMs)
    return () => clearInterval(id)
  }, [enabled, intervalMs, refetch])

  return { data, error, loading, refetch }
}
```

## 4. Socket hooks (optional — delete if the app has no realtime feed)

`useSocket()` is however the target repo exposes its shared socket.io-client
instance (usually a context provider). These two build on it:

```ts
/**
 * Live connection state, so UI that claims "Live" can be honest about it.
 * Tracks connect/disconnect for the lifetime of the calling component.
 */
export function useSocketConnected(): boolean {
  const socket = useSocket()
  const [connected, setConnected] = useState(socket?.connected ?? false)
  useEffect(() => {
    if (!socket) return
    setConnected(socket.connected)
    const up = () => setConnected(true)
    const down = () => setConnected(false)
    socket.on("connect", up)
    socket.on("disconnect", down)
    return () => {
      socket.off("connect", up)
      socket.off("disconnect", down)
    }
  }, [socket])
  return connected
}

/** Transport currently carrying the Socket.IO connection ("websocket" after
 * the upgrade, "polling" before it / as fallback). */
function useSocketTransport(): string | null {
  const socket = useSocket()
  const connected = useSocketConnected()
  const [transport, setTransport] = useState<string | null>(null)
  useEffect(() => {
    if (!socket || !connected) {
      setTransport(null)
      return
    }
    const engine = socket.io.engine
    const update = () => setTransport(engine.transport.name)
    update()
    engine.on("upgrade", update)
    return () => {
      engine.off("upgrade", update)
    }
  }, [socket, connected])
  return transport
}
```

## 5. Status language — tones + StatusChip

```ts
// src/lib/format.ts — status palette. Status is the one place the UI spends
// color (the rest of the theme stays neutral). Swap the Tailwind classes for
// the target design system's tokens; keep the five tones.
export interface StatusStyle {
  chip: string
  dot: string
  label: string
}

const TONES = {
  ready: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25",
  live: "bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-500/25",
  hold: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25",
  fault: "bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25",
  idle: "bg-muted text-muted-foreground border-border",
}
const DOT = {
  ready: "bg-emerald-500",
  live: "bg-sky-500",
  hold: "bg-amber-500",
  fault: "bg-rose-500",
  idle: "bg-muted-foreground/40",
}

/** Ad-hoc StatusStyle from a palette tone — for indicators (e.g. connection
 * health) that don't map to a domain enum. */
export function statusStyle(
  tone: keyof typeof TONES,
  label: string,
): StatusStyle {
  return { chip: TONES[tone], dot: DOT[tone], label }
}

/** Coarse relative time ("just now", "5m ago", "2h ago", "3d ago"). */
export function fmtAgo(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return "just now"
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
```

Format `build_time` with the repo's existing date helper (it's ISO 8601 UTC).

```tsx
// src/components/StatusChip.tsx
import { cn } from "@/lib/utils"
import type { StatusStyle } from "@/lib/format"

export function StatusChip({
  status,
  pulse = false,
  className,
}: {
  status: StatusStyle
  pulse?: boolean
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        status.chip,
        className,
      )}
    >
      <span
        className={cn("size-1.5 rounded-full", status.dot, pulse && "status-beat")}
      />
      {status.label}
    </span>
  )
}
```

Beat animation (was `ecg-beat` in the medical-flavored source — rename freely
to fit the target's motion vocabulary):

```css
@keyframes status-beat {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50%      { opacity: 1; transform: scale(1.35); }
}
.status-beat { animation: status-beat 1.4s ease-in-out infinite; transform-origin: center; }

/* Kiosk / shop-floor PCs often run with OS animations off. */
@media (prefers-reduced-motion: reduce) {
  .status-beat { animation: none; }
}
```

## 6. SystemStatus popover

```tsx
// src/components/SystemStatus.tsx
import { useCallback } from "react"
import { Monitor, RefreshCw, Radio, Server } from "lucide-react"
import { StatusChip } from "@/components/StatusChip"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { useSocket, useSocketConnected } from "@/context/SocketContext"
import { usePolling } from "@/hooks/usePolling"
import { api } from "@/lib/api"
import { fmtAgo, fmtTime, statusStyle } from "@/lib/format"
import { cn } from "@/lib/utils"

const HEALTH_POLL_MS = 15_000
// Display-only; must match the `path` passed to io() where the socket is made.
const SOCKET_PATH = "/ws/socket.io"

// Frontend build provenance. __APP_VERSION__ is inlined from package.json by
// the `define` block in vite.config.ts; the VITE_ vars are baked in by the
// Docker build (absent in dev).
const FE_VERSION = __APP_VERSION__
const FE_COMMIT = import.meta.env.VITE_GIT_SHA || "dev"
const FE_BUILD_TIME = import.meta.env.VITE_BUILD_TIME || ""

// Every API call is same-origin and relative, so the browser really does talk
// to this origin — but in dev that's the Vite server, which forwards to the
// backend, and in prod it's nginx doing the same. Show the origin we call
// plus the upstream actually serving it, so neither is a lie.
// __API_PROXY_TARGET__ is inlined by vite.config.ts (dev serve only).
const API_ENDPOINT = `${window.location.origin}/api`
const API_UPSTREAM = __API_PROXY_TARGET__
  ? `${__API_PROXY_TARGET__}/api` // dev: the Vite proxy target
  : "nginx → http://backend:8000/api" // prod: match your nginx.conf

function DetailRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 text-xs">
      <dt className="shrink-0 text-muted-foreground">{k}</dt>
      <dd className="truncate font-mono" title={v}>
        {v}
      </dd>
    </div>
  )
}

/**
 * Backend connectivity indicator: a compact trigger (dot + overall state) that
 * opens a popover detailing the REST API (endpoint, DB, latency, last check)
 * and the Socket.IO feed (path, transport, socket id). Polls `/api/health`;
 * realtime state comes straight from the shared socket.
 */
export function SystemStatus({ compact = false }: { compact?: boolean }) {
  const fetchHealth = useCallback(async () => {
    const t0 = performance.now()
    const health = await api.health()
    return {
      ...health,
      // Floor at 1: a sub-ms round-trip showing "0 ms" reads as broken.
      latencyMs: Math.max(1, Math.round(performance.now() - t0)),
      checkedAt: Date.now(),
    }
  }, [])
  const {
    data: health,
    error,
    loading,
    refetch,
  } = usePolling(fetchHealth, HEALTH_POLL_MS)

  const socket = useSocket()
  const wsConnected = useSocketConnected()
  const transport = useSocketTransport()

  // Three states, not two: null data + null error = first probe still out.
  const checking = health === null && error === null
  const apiOk = error === null && health !== null
  const dbOk = apiOk && health.database === "up"
  const allOk = apiOk && dbOk && wsConnected

  const apiChip = !apiOk
    ? statusStyle(
        checking ? "idle" : "fault",
        checking ? "Checking" : "Unreachable",
      )
    : dbOk
      ? statusStyle("ready", "Online")
      : statusStyle("hold", "DB down")
  const wsChip = wsConnected
    ? statusStyle("ready", "Connected")
    : statusStyle("hold", "Reconnecting")
  const overall = checking
    ? statusStyle("idle", "Checking…")
    : allOk
      ? statusStyle("ready", "Operational")
      : !apiOk && !wsConnected
        ? statusStyle("fault", "Offline") // everything gone
        : statusStyle("hold", "Degraded") // partially up

  const dot = (
    <span
      aria-hidden
      className={cn(
        "size-1.5 rounded-full",
        overall.dot,
        allOk && "status-beat",
        !allOk && !checking && "animate-pulse",
      )}
    />
  )

  return (
    <Popover>
      <PopoverTrigger asChild>
        {compact ? (
          // Header form: icon button with the status dot pinned to its corner.
          <Button
            variant="ghost"
            size="icon"
            aria-label={`System status: ${overall.label}`}
            title={`System status: ${overall.label}`}
          >
            <span className="relative">
              <Server className="size-4" />
              <span className="absolute -top-1 -right-1">{dot}</span>
            </span>
          </Button>
        ) : (
          // Sidebar-footer form: full-width row with the state spelled out.
          <button
            type="button"
            aria-label={`System status: ${overall.label}`}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 font-mono text-[10px] tracking-widest uppercase transition-colors hover:bg-secondary/60"
          >
            {dot}
            <span className="text-muted-foreground">System</span>
            <span
              className={cn(
                "ml-auto",
                allOk || checking
                  ? "text-muted-foreground"
                  : !apiOk && !wsConnected
                    ? "text-rose-600 dark:text-rose-400"
                    : "text-amber-600 dark:text-amber-400",
              )}
            >
              {overall.label}
            </span>
          </button>
        )}
      </PopoverTrigger>

      <PopoverContent
        side={compact ? "bottom" : "top"}
        align={compact ? "end" : "start"}
        className="w-80 p-0"
      >
        <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
          <div className="leading-tight">
            <div className="text-sm font-semibold">System status</div>
            <div className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
              Backend · Realtime · Build
            </div>
          </div>
          <StatusChip status={overall} pulse={allOk} />
        </div>

        <div className="space-y-4 px-4 py-3">
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <Server className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="flex-1 text-xs font-medium">Backend API</span>
              <StatusChip status={apiChip} />
            </div>
            <dl className="space-y-1">
              <DetailRow k="Endpoint" v={API_ENDPOINT} />
              <DetailRow k="Upstream" v={API_UPSTREAM} />
              <DetailRow k="Database" v={apiOk ? health.database : "—"} />
              <DetailRow
                k="Environment"
                v={apiOk ? (health.environment ?? "—") : "—"}
              />
              <DetailRow
                k="Version"
                v={
                  apiOk && health.version
                    ? `${health.version} (${health.commit ?? "?"})`
                    : "—"
                }
              />
              <DetailRow
                k="Built"
                v={
                  apiOk && health.build_time ? fmtTime(health.build_time) : "—"
                }
              />
              <DetailRow
                k="Latency"
                v={apiOk ? `${health.latencyMs} ms` : "—"}
              />
              <DetailRow
                k="Checked"
                v={health ? fmtAgo(health.checkedAt) : "—"}
              />
            </dl>
            {error && (
              <p className="text-xs text-rose-600 dark:text-rose-400">
                {error}
              </p>
            )}
          </section>

          {/* Delete this section (and the socket hooks) if the app has no
              realtime feed. */}
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <Radio className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="flex-1 text-xs font-medium">
                Realtime · Socket.IO
              </span>
              <StatusChip status={wsChip} pulse={wsConnected} />
            </div>
            <dl className="space-y-1">
              <DetailRow k="Path" v={SOCKET_PATH} />
              <DetailRow k="Transport" v={transport ?? "—"} />
              <DetailRow k="Socket ID" v={socket?.id ?? "—"} />
            </dl>
          </section>

          {/* Static build info — no StatusChip, it's not a health state. */}
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <Monitor className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="flex-1 text-xs font-medium">Frontend</span>
            </div>
            <dl className="space-y-1">
              <DetailRow k="Version" v={`${FE_VERSION} (${FE_COMMIT})`} />
              <DetailRow
                k="Built"
                v={FE_BUILD_TIME ? fmtTime(FE_BUILD_TIME) : "—"}
              />
            </dl>
          </section>
        </div>

        <div className="flex items-center justify-between border-t px-4 py-2">
          <span className="text-[11px] text-muted-foreground">
            Re-checks every {HEALTH_POLL_MS / 1000} s
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={loading}
            onClick={() => void refetch()}
          >
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
            Check now
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
```

## 7. LiveBadge

```tsx
// src/components/LiveBadge.tsx
import { useSocketConnected } from "@/context/SocketContext"

/**
 * Honest realtime indicator: a beating dot while the Socket.IO feed is up,
 * an amber pulse while it reconnects. Replaces static "Live" chips.
 */
export function LiveBadge() {
  const connected = useSocketConnected()
  if (connected) {
    return (
      <span className="flex items-center gap-1.5 font-mono text-xs tracking-widest text-muted-foreground uppercase">
        <span className="status-beat size-1.5 rounded-full bg-emerald-500" />
        Live
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1.5 font-mono text-xs tracking-widest text-amber-600 uppercase dark:text-amber-400">
      <span className="size-1.5 animate-pulse rounded-full bg-amber-500" />
      Reconnecting
    </span>
  )
}
```
