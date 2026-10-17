import { useCallback, useEffect, useMemo, useState } from "react"
import { Bug, ChevronDown, ChevronLeft, ChevronRight, Globe, Search, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { usePolling } from "@/hooks/usePolling"
import { api } from "@/lib/api"
import { fmtTime } from "@/lib/format"
import type { ErrorLog, RequestLog, RequestLogFilters } from "@/lib/types"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 50
const POLL_MS = 15000
const ALL = "all"
const METHODS = ["POST", "PUT", "PATCH", "DELETE", "GET"] as const

/** The filter's view of a user — map the app's own User onto it. */
interface LogUser {
  id: number
  name: string
  code?: string | null
}

function statusTone(status: number | null): string {
  if (status == null || status >= 500) return "bg-rose-500/15 text-rose-600 dark:text-rose-400"
  if (status === 422) return "bg-violet-500/15 text-violet-600 dark:text-violet-400"
  if (status >= 400) return "bg-amber-500/15 text-amber-600 dark:text-amber-400"
  return "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
}

const METHOD_TONE: Record<string, string> = {
  GET: "text-sky-600 dark:text-sky-400",
  POST: "text-emerald-600 dark:text-emerald-400",
  PUT: "text-amber-600 dark:text-amber-400",
  PATCH: "text-amber-600 dark:text-amber-400",
  DELETE: "text-rose-600 dark:text-rose-400",
}

/** The user behind a row, or "anonymous" for a request without a session
 *  (a failed sign-in, the login page itself). */
function Who({ name, code }: { name: string | null; code: string | null }) {
  if (!name) return <span className="text-muted-foreground italic">anonymous</span>
  return (
    <span className="whitespace-nowrap">
      {name}
      {code && <span className="ml-1.5 font-mono text-[11px] text-muted-foreground">{code}</span>}
    </span>
  )
}

function UserFilter({
  users,
  value,
  onChange,
}: {
  users: LogUser[]
  value: number | null
  onChange: (id: number | null) => void
}) {
  return (
    <div className="space-y-1.5">
      <Label>User</Label>
      <Select
        value={value == null ? ALL : String(value)}
        onValueChange={(v) => onChange(v === ALL ? null : Number(v))}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Everyone</SelectItem>
          {users.map((u) => (
            <SelectItem key={u.id} value={String(u.id)}>
              {u.name}
              {u.code ? ` · ${u.code}` : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

// ---- HTTP requests --------------------------------------------------------- //

function RequestsView({ users }: { users: LogUser[] }) {
  const [userId, setUserId] = useState<number | null>(null)
  const [method, setMethod] = useState<string>(ALL)
  const [failed, setFailed] = useState(false)
  const [search, setSearch] = useState("")
  const [q, setQ] = useState("")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [page, setPage] = useState(1)

  // Debounce the path box; any filter change starts again at the newest page.
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(t)
  }, [search])
  useEffect(() => setPage(1), [userId, method, failed, q, dateFrom, dateTo])

  const filters = useMemo<RequestLogFilters>(
    () => ({
      user_id: userId ?? undefined,
      method: method === ALL ? undefined : (method as RequestLogFilters["method"]),
      failed: failed || undefined,
      q: q || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
    [userId, method, failed, q, dateFrom, dateTo, page],
  )
  const fetcher = useCallback(() => api.requestLogs(filters), [filters])
  // Only the newest page refreshes itself — an older page holds still while it
  // is being read (new rows would shift it under the reader).
  const { data } = usePolling(fetcher, POLL_MS, { paused: page > 1 })
  const rows: RequestLog[] = data?.items ?? []
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-4">
      <Card className="gap-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[1.3fr_0.8fr_1.4fr_0.9fr_0.9fr] lg:items-end">
          <UserFilter users={users} value={userId} onChange={setUserId} />
          <div className="space-y-1.5">
            <Label>Method</Label>
            <Select value={method} onValueChange={setMethod}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Any</SelectItem>
                {METHODS.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="log-q">Path</Label>
            <div className="relative">
              <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="log-q"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="e.g. /api/orders"
                className="pr-8 pl-9 font-mono"
              />
              {search && (
                <button
                  type="button"
                  aria-label="Clear path filter"
                  onClick={() => setSearch("")}
                  className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              )}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="log-from">From</Label>
            <Input id="log-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="log-to">To</Label>
            <Input id="log-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4 text-xs text-muted-foreground">
          <label className="flex cursor-pointer items-center gap-2 select-none">
            <input
              type="checkbox"
              checked={failed}
              onChange={(e) => setFailed(e.target.checked)}
              className="size-3.5 accent-rose-500"
            />
            Failed requests only (status 400 and above)
          </label>
          {/* Say what the log leaves out, or a missing GET reads as a bug. */}
          <span>
            Every write and every failure is recorded; successful GETs only while
            request logging is switched on.
          </span>
        </div>
      </Card>

      <Card className="p-0">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Method</TableHead>
              <TableHead>Path</TableHead>
              <TableHead className="text-center">Status</TableHead>
              <TableHead className="text-right">ms</TableHead>
              <TableHead>IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data === null &&
              Array.from({ length: 6 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {rows.map((r) => (
              <TableRow key={r.id} className="align-top">
                <TableCell className="font-mono whitespace-nowrap text-muted-foreground">
                  {fmtTime(r.created_at)}
                </TableCell>
                <TableCell>
                  <Who name={r.user_name} code={r.user_code} />
                </TableCell>
                <TableCell className={cn("font-mono font-semibold", METHOD_TONE[r.method])}>
                  {r.method}
                </TableCell>
                <TableCell className="max-w-md font-mono whitespace-normal">
                  <span className="break-all">{r.path}</span>
                  {r.query_string && (
                    <span className="break-all text-muted-foreground">?{r.query_string}</span>
                  )}
                  {r.error && (
                    <div className="mt-0.5 break-all text-rose-600 dark:text-rose-400">{r.error}</div>
                  )}
                </TableCell>
                <TableCell className="text-center">
                  <Badge className={statusTone(r.status_code)}>{r.status_code}</Badge>
                </TableCell>
                <TableCell className="text-right font-mono text-muted-foreground tabular-nums">
                  {r.duration_ms}
                </TableCell>
                <TableCell className="font-mono text-muted-foreground">{r.client_ip ?? "—"}</TableCell>
              </TableRow>
            ))}
            {data && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  <Globe className="mx-auto mb-2 size-5" />
                  No request matches these filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      {data && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="font-mono text-xs text-muted-foreground">
            {(page - 1) * PAGE_SIZE + 1}–{(page - 1) * PAGE_SIZE + rows.length} of{" "}
            {total.toLocaleString()} requests · newest first
          </span>
          {pages > 1 && (
            <div className="flex items-center gap-1.5">
              <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft className="size-4" /> Newer
              </Button>
              <span className="px-2 font-mono text-xs text-muted-foreground">
                {page} / {pages}
              </span>
              <Button variant="outline" size="sm" disabled={page === pages} onClick={() => setPage((p) => p + 1)}>
                Older <ChevronRight className="size-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---- Errors ---------------------------------------------------------------- //

const KIND_FILTERS = [
  { key: undefined, label: "All" },
  { key: "http", label: "HTTP" },
  { key: "exception", label: "Crashes" },
] as const

/** Every row expands — into the full message, plus the traceback when there is
 *  one. (Expanding only rows with a traceback left long messages clipped to
 *  two lines for good.) */
function ErrorRow({ log }: { log: ErrorLog }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <TableRow
        className="cursor-pointer"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key !== "Enter" && e.key !== " ") return
          e.preventDefault()
          setOpen((o) => !o)
        }}
      >
        <TableCell className="font-mono text-xs whitespace-nowrap text-muted-foreground">
          {fmtTime(log.created_at)}
        </TableCell>
        <TableCell className="text-xs">
          <Who name={log.user_name} code={log.user_code} />
        </TableCell>
        <TableCell>
          <Badge className={statusTone(log.status_code)}>{log.status_code ?? "—"}</Badge>
        </TableCell>
        <TableCell>
          {log.kind === "exception" ? (
            <Badge className="bg-rose-500/15 text-rose-600 dark:text-rose-400">crash</Badge>
          ) : (
            <Badge variant="secondary">
              {log.exception_type === "RequestValidationError" ? "validation" : "http"}
            </Badge>
          )}
        </TableCell>
        <TableCell className="max-w-56 truncate font-mono text-xs">{log.source}</TableCell>
        <TableCell className="max-w-md">
          <span className="line-clamp-2 break-all text-sm">{log.message}</span>
        </TableCell>
        <TableCell className="w-8 text-muted-foreground">
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </TableCell>
      </TableRow>
      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={7} className="bg-muted/40 p-0">
            {/* break-all + pre-wrap: long unbroken strings (URLs, payloads) wrap. */}
            <div className="max-h-80 space-y-4 overflow-auto p-4 text-xs">
              <div>
                <div className="mb-1 font-medium text-muted-foreground">Message</div>
                <div className="break-all whitespace-pre-wrap">{log.message}</div>
              </div>
              <div className="text-muted-foreground">
                {log.path && <span className="font-mono">{log.method} {log.path} · </span>}
                {log.client_ip ? `from ${log.client_ip}` : "no client address"}
              </div>
              {log.traceback && (
                <div>
                  <div className="mb-1 font-medium text-muted-foreground">Traceback</div>
                  <pre className="break-all font-mono leading-relaxed whitespace-pre-wrap">{log.traceback}</pre>
                </div>
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

function ErrorsView({ users }: { users: LogUser[] }) {
  const [kind, setKind] = useState<"http" | "exception" | undefined>(undefined)
  const [userId, setUserId] = useState<number | null>(null)
  const fetcher = useCallback(() => api.errorLogs(kind, 200, userId ?? undefined), [kind, userId])
  const { data: logs } = usePolling(fetcher, POLL_MS)

  return (
    <div className="space-y-4">
      <Card className="gap-4 p-5">
        <div className="grid gap-4 sm:grid-cols-[minmax(0,20rem)_auto] sm:items-end">
          <UserFilter users={users} value={userId} onChange={setUserId} />
          <div className="flex gap-1 justify-self-start rounded-lg border p-1 sm:justify-self-end">
            {KIND_FILTERS.map((f) => (
              <button
                key={f.label}
                type="button"
                onClick={() => setKind(f.key)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                  kind === f.key ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <p className="border-t pt-4 text-xs text-muted-foreground">
          The newest 200. Crashes are bugs; HTTP rows are refusals the app meant to give.
        </p>
      </Card>

      <Card className="overflow-x-auto p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Message</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {logs === null &&
              Array.from({ length: 5 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {(logs ?? []).map((log) => (
              <ErrorRow key={log.id} log={log} />
            ))}
            {logs && logs.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  <Bug className="mx-auto mb-2 size-5" />
                  No errors recorded for this filter.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  )
}

// ---- the page body --------------------------------------------------------- //

const VIEWS = [
  { key: "requests", label: "HTTP requests", icon: Globe },
  { key: "errors", label: "Errors", icon: Bug },
] as const

/** Admin → System Log: the HTTP access log (who changed what, and when) and
 *  the error / crash log, each row naming its user. */
export function SystemLogTab() {
  const [view, setView] = useState<(typeof VIEWS)[number]["key"]>("requests")
  const [users, setUsers] = useState<LogUser[]>([])
  useEffect(() => {
    // Deactivated accounts included: a departed user's rows stay filterable.
    void api
      .users(true)
      .then((list) =>
        setUsers(
          list
            .map((u) => ({ id: u.id, name: u.name, code: u.employee_no })) // EXTENSION POINT
            .sort((a, b) => a.name.localeCompare(b.name)),
        ),
      )
      .catch(() => {})
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex w-fit gap-1 rounded-lg border p-1" role="tablist" aria-label="Log">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            type="button"
            role="tab"
            aria-selected={view === v.key}
            onClick={() => setView(v.key)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              view === v.key ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <v.icon className="size-4" />
            {v.label}
          </button>
        ))}
      </div>
      {view === "requests" ? <RequestsView users={users} /> : <ErrorsView users={users} />}
    </div>
  )
}
