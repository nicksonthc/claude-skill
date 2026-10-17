// System Log calls — merge `query` (if the app lacks one) and the entries of
// `api` into the app's src/lib/api.ts.
import type {
  ErrorLog,
  RequestLogFilters,
  RequestLogPage,
  Setting,
  User,
} from "@/lib/types"

// Stand-in — use the app's own fetch wrapper (bearer header, error detail,
// 401 handling). Kept here only so the template compiles on its own.
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status}`)
  return (await res.json()) as T
}

/** `?a=b&…` from a filter object, dropping undefined and "" — so pass
 *  `failed || undefined`, not `false`, to leave a flag off the URL. */
function query<T extends object>(params: T): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ""
}

export const api = {
  // Stand-ins for calls the app likely has already.
  users: (includeInactive = false) =>
    request<User[]>("GET", `/api/users${query({ include_inactive: includeInactive || undefined })}`),
  updateSetting: (key: string, value: string) =>
    request<Setting>("PUT", `/api/settings/${encodeURIComponent(key)}`, { value }),

  // System Log (admin)
  errorLogs: (kind?: "http" | "exception", limit = 100, user_id?: number) =>
    request<ErrorLog[]>("GET", `/api/system-log/errors${query({ limit, kind, user_id })}`),
  requestLogs: (filters: RequestLogFilters) =>
    request<RequestLogPage>("GET", `/api/system-log/requests${query({ ...filters })}`),
}
