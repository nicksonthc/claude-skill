// System Log DTOs — mirror app/api/routes/system_log.py by hand; change both
// together. Merge into the app's src/lib/types.ts.

// Stand-ins for types the app already has — delete these and import its own.
export interface User {
  id: number
  name: string
  employee_no: string
}
export interface Setting {
  key: string
  value: string
  description: string | null
  updated_at: string
}

/** One row of the error log (System Log → Errors). */
export interface ErrorLog {
  id: number
  /** "http" = a raised HTTPException / 422; "exception" = a crash (a bug). */
  kind: "http" | "exception"
  /** "POST /api/orders/{code}/close", or "module.func" for decorated code. */
  source: string
  status_code: number | null
  exception_type: string | null
  message: string
  traceback: string | null
  method: string | null
  path: string | null
  client_ip: string | null
  user_id: number | null
  /** Naive UTC from the server — no offset; see fmtTime. */
  created_at: string
  /** Who made the request; null when anonymous (a failed sign-in) or the
   *  account no longer exists. */
  user_name: string | null
  user_code: string | null
}

/** One row of the HTTP access log (System Log → HTTP requests). */
export interface RequestLog {
  id: number
  method: string
  path: string
  query_string: string | null
  status_code: number
  duration_ms: number
  client_ip: string | null
  user_id: number | null
  /** The exception repr of a request that 500'd. */
  error: string | null
  created_at: string
  user_name: string | null
  user_code: string | null
}

export interface RequestLogPage {
  items: RequestLog[]
  total: number
  limit: number
  offset: number
}

/** Filters of GET /api/system-log/requests — dates are local days (YYYY-MM-DD). */
export interface RequestLogFilters {
  user_id?: number
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
  failed?: boolean
  q?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}
