# socketio-realtime-hooks — building blocks

Genericized from the source project. `@/` is a Vite alias to `src/`. The room
payload (`station_code` / `main_sn` / `overview` in the source) is the
extension point — rename to the target domain's rooms. Sections numbered to
match SKILL.md's "Moving parts".

## 1 + 2 + 3 + 4. SocketContext — provider and hooks

```tsx
// src/context/SocketContext.tsx
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { io, type Socket } from "socket.io-client"
import { getToken, setClientId } from "@/lib/api"

// One Socket.IO connection for the whole authenticated app. The backend
// mounts Socket.IO at `/ws`, so we connect same-origin with path
// `/ws/socket.io`; the Vite proxy (dev) and nginx (prod) forward it to the
// backend. The session Bearer token is sent in the handshake `auth` payload
// and validated by the server's `connect` handler.
const SocketContext = createContext<Socket | null>(null)

export function SocketProvider({ children }: { children: ReactNode }) {
  const [socket, setSocket] = useState<Socket | null>(null)

  useEffect(() => {
    const token = getToken()
    if (!token) return
    const s = io({
      path: "/ws/socket.io",
      transports: ["websocket", "polling"],
      auth: { token },
    })
    setSocket(s)
    // Tag our REST calls with this connection so the backend can leave us out
    // of the events we ourselves caused. The id changes on every reconnect.
    const tag = () => setClientId(s.id ?? null)
    const untag = () => setClientId(null)
    s.on("connect", tag)
    s.on("disconnect", untag)
    return () => {
      s.off("connect", tag)
      s.off("disconnect", untag)
      setClientId(null)
      s.close()
      setSocket(null)
    }
  }, [])

  return (
    <SocketContext.Provider value={socket}>{children}</SocketContext.Provider>
  )
}

export function useSocket(): Socket | null {
  return useContext(SocketContext)
}

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

/**
 * Subscribe to a socket event for the lifetime of the calling component. The
 * handler is kept in a ref so it always sees the latest render state without
 * re-binding the listener on every render.
 */
export function useSocketEvent<T = unknown>(
  event: string,
  handler: (payload: T) => void,
) {
  const socket = useSocket()
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    if (!socket) return
    const fn = (payload: T) => ref.current(payload)
    socket.on(event, fn)
    return () => {
      socket.off(event, fn)
    }
  }, [socket, event])
}

/**
 * Join the given Socket.IO room(s) while this component is mounted, re-joining
 * automatically after a reconnect. The payload shape is the app's room
 * vocabulary — e.g. `{ record_id }` while a record is open on screen, or
 * `{ overview: true }` for app-wide listeners (dashboards, pickers).
 * Passing nothing is a no-op, so a caller can join conditionally.
 */
export function useSocketRoom(data: {
  station_code?: string
  record_id?: string
  overview?: boolean
}) {
  const socket = useSocket()
  // Stable key: an inline object is a fresh reference every render and would
  // join/leave in a loop.
  const key = JSON.stringify(data)
  useEffect(() => {
    if (!socket) return
    if (!data.station_code && !data.record_id && !data.overview) return
    const join = () => socket.emit("join", data)
    if (socket.connected) join()
    socket.on("connect", join) // re-join after a reconnect
    return () => {
      socket.off("connect", join)
      socket.emit("leave", data)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [socket, key])
}
```

Mount inside the auth boundary so the token exists and the socket dies with
the session:

```tsx
<AuthProvider>
  {user ? <SocketProvider>{app}</SocketProvider> : <LoginScreen />}
</AuthProvider>
```

## 5. Echo suppression — the X-Client-Id ↔ skip_sid contract

The problem: a tab mutates via REST, refreshes itself off the HTTP response,
then receives the realtime event *about its own change* and refreshes again.

Client side (in the API client module):

```ts
/** This tab's Socket.IO connection id, kept in sync by `SocketProvider`. Sent
 * as `X-Client-Id` on every request so the backend can skip echoing a
 * realtime event back to the tab that caused it (it refreshes off the
 * response instead). Null before the socket connects — then everyone, us
 * included, gets the echo, which is merely a redundant re-fetch. */
let clientId: string | null = null

export function setClientId(id: string | null) {
  clientId = id
}

// inside request():
if (clientId) headers["X-Client-Id"] = clientId
```

Server side (FastAPI + python-socketio shown; the contract is the point):

```python
# api/deps.py — routes take it as an optional header dependency
def client_id(
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
) -> str | None:
    return x_client_id


# realtime.py — emit helpers accept and forward it
async def emit_record_updated(..., skip_sid: str | None = None) -> None:
    """Announce a change to every OTHER browser watching this record.

    ``skip_sid`` is the originating tab's socket id: it refreshed itself off
    the HTTP response, so it is excluded here. Best-effort — never raises
    (the change is already committed)."""
    try:
        await sio.emit("record_updated", payload, to=room, skip_sid=skip_sid)
    except Exception:
        logger.exception("failed to emit record_updated")
```

Design rule that makes the null-before-connect window safe: events mean
**"re-fetch this"**, never "apply this delta" — a duplicate is then just one
redundant GET.

## 6. Presence (optional)

Server keeps an in-memory roster keyed by sid (dropped on disconnect) and
pushes the whole roster on every change. Client:

```ts
/**
 * Announce that this terminal is manned at `code` (null once it is
 * released). Mounted once, in the app shell, for the whole session.
 * Re-announces on reconnect because the socket id — the server's key for
 * this tab — changes.
 */
export function useAnnounceStation(code: string | null) {
  const socket = useSocket()
  useEffect(() => {
    if (!socket) return
    const announce = () => socket.emit("presence", { station_code: code })
    if (socket.connected) announce()
    socket.on("connect", announce)
    return () => {
      socket.off("connect", announce)
      // Stand down before the next value is announced. Skipped when the
      // socket is already gone — the server drops us on disconnect anyway.
      if (code && socket.connected) socket.emit("presence", {})
    }
  }, [socket, code])
}
```

Presence follows the *lock*, not the page: announce from the app shell with
the terminal's assignment, so navigating away doesn't clear it.

## 7. Fast path + self-heal composition

The canonical consumer shape — socket events are the fast path; a *slow* REST
poll seeds the first render and heals a client whose socket silently dropped.
(`usePolling` is in the `system-status-popover` skill's REFERENCE, §3.)

```ts
/**
 * The live roster, keyed by station code. Socket events are the fast path;
 * the REST read seeds the first render and self-heals a client whose socket
 * dropped.
 */
export function useStationPresence(): StationPresence {
  const [roster, setRoster] = useState<StationPresence>({})
  const fetcher = useCallback(() => api.stationPresence(), [])
  const { data } = usePolling(fetcher, 30_000) // slow — the socket is fast

  useEffect(() => {
    if (data) setRoster(data)
  }, [data])
  useSocketEvent<{ stations: StationPresence }>("station_presence", (e) =>
    setRoster(e.stations ?? {}),
  )

  return roster
}
```

## Proxying (dev + prod)

```ts
// vite.config.ts — ws:true upgrades the connection; without it the client
// silently stays on long-polling.
server: {
  proxy: {
    "/api": { target: DEV_PROXY_TARGET, changeOrigin: true },
    "/ws": { target: DEV_PROXY_TARGET, changeOrigin: true, ws: true },
  },
},
```

```nginx
# nginx.conf (prod SPA container)
location /ws/ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```
