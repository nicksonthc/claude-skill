---
name: request-error-logging
description: Database-backed request and error logging for a FastAPI / Starlette app, with an admin System Log page — an access-log middleware that records who called what (status, timing, user) and turns any unhandled exception into a clean 500 while the logger itself can never break a request; app-level handlers that record every HTTPException and validation error and answer unchanged; a log-and-reraise decorator for socket handlers and background jobs; user attribution from the bearer token, sign-ins included; a runtime switch that keeps polling GETs out; and a filterable, paged viewer with expandable tracebacks. Use when adding an access log or request logging, "who changed what and when", logging errors or crashes to the database, an admin error-log / system-log page, attributing errors to users, or when a log table is drowning in polling and health-check rows.
---

# Request & Error Logging

Harvested from a production shop-floor app whose admins answer "who changed
what, and when?" and "what broke, for whom?" from a browser. Proven on FastAPI
0.139 · Starlette 1.3 · SQLModel 0.0.39 + async SQLAlchemy 2.0 (asyncpg) ·
PostgreSQL · React 19 · Vite 6 · Tailwind v4 · shadcn/ui. The blocks are
FastAPI-specific; the contract — two tables, writes that never raise, one
identity resolver, a noise gate — carries to any stack.

## Moving parts

1. **Two append-only tables.** `requestlog`: one row per request — method, path,
   query, status, duration, client IP, user id, the repr if it 500'd. `errorlog`:
   one row per error — `kind` (`http` = a refusal the app meant to give,
   `exception` = a bug), source, status, type, message, traceback, path, user id.
   Plain-int `user_id`, no foreign keys.
2. **Writers that never raise** — `log_error()`, `write_request_log()`: own
   session, broad try/except, fall back to a stdlib warning.
3. **Access-log middleware + 500 guard.** Times the request, writes the row, and
   catches whatever escaped the app: traceback to `errorlog`, a plain
   `500 {"detail": "Internal Server Error"}` to the client.
4. **App-level handlers** (Starlette `HTTPException`, `RequestValidationError`):
   log, then delegate to FastAPI's defaults, so every response is exactly what
   the app would have sent. Routes carry no try/except of their own.
5. **`@log_exceptions`** — log-and-reraise for code outside a request (socket
   handlers, background jobs, scripts), on a function or a whole class.
6. **User attribution.** One `resolve_user_id(token)` shared by both logs, built
   on the auth module's own resolver; the login route names its user on
   `request.state`; a user the auth gate already resolved is reused.
7. **Noise gate.** `should_log(path, method, status)`: never-log paths (health)
   never; failures and writes always; successful GETs only while a cached flag is
   on — admin-only to change.
8. **Read API** (admin). Errors by kind and user; requests by user, method,
   failed-only, path, local-day range, paged with a total. Each row carries the
   user's current name, resolved in one batch.
9. **System Log page.** HTTP requests | Errors, with filters, polling on the
   newest page only, and error rows that expand to message + traceback.

## Workflow

1. Read `REFERENCE.md` (numbered as above); `templates/` holds the page and tests.
2. Migrate the two tables with their indexes (REFERENCE §1).
3. Add `error_logging.py` and `http_logging.py`; point `user_id_for_token` at the
   function your auth gate uses.
4. Wire `main.py`: handlers on the bare app → auth gate → access-log middleware →
   CORS last. The last registered runs first: CORS → access log → auth → router.
5. Set `request.state.log_user_id` in the login route after a good sign-in.
6. Choose the noise policy: never-log paths, the flag's default, who flips it.
7. Decorate socket handlers and background classes; streamed replies and
   fire-and-forget tasks call `log_error` themselves with the originating token.
8. Add the read routes and the page; say on the page what the log leaves out.
9. Verify with the smoke tests (§10), then by hand: a 404 raised in a route (an
   `http` row, response unchanged); a bare exception (plain 500 with CORS headers,
   traceback row, request row with the repr); a sign-in (credited); the database
   stopped (requests answer on their own merits); the IP column (clients, not the
   proxy — uvicorn trusts forwarded headers from 127.0.0.1 only, so set
   `--forwarded-allow-ips` to the proxy's address).

## Principles

- **The logger never breaks a request.** Log writes stay out of the request's
  transaction, so a rolled-back request keeps its row — exactly when you need it.
- **Two logs, two questions.** `requestlog`: who called what, when, how it ended.
  `errorlog`: the error itself. What changed in the data, staged in the same
  transaction as the change, is a third record: `replayable-audit-trail`.
- **`kind` sorts refusals from bugs.** Expected failures are raised as
  HTTPExceptions with a message (404, 409) and land as `http`; guard every lookup
  that can miss, and the Crashes filter stays a list of real bugs.
- **Metadata only.** Bodies stay unread; a 422 keeps `loc: msg`, never the
  submitted values. Query strings are stored verbatim — keep secrets out of them.

## Pitfalls (each already paid for once)

- **Identity drift.** The error log once matched the raw bearer token against
  session rows keyed by the JWT's `jti`, found nobody, and logged every error as
  anonymous. Both logs now call one resolver built on the auth module's own.
- **A sign-in carries no token**, so without `request.state.log_user_id` every
  sign-in is anonymous. A failed one stays anonymous, correctly.
- **Polling buried the writes.** One row per request let terminal polling drown
  the writes worth auditing; health checks were most of the table. Only reads
  that worked are ever dropped, so the gate costs no diagnostics.
- **The flag sits on the hot path.** Cache it per process (15 s TTL), drop the
  entry on write, fall back to the default when the DB is down. A change made
  through another worker arrives within the TTL.
- **Register Starlette's `HTTPException`.** A handler on FastAPI's subclass sees
  only what routes raise; the router's own 404 and 405 slip past. Delegate to
  FastAPI's handler so headers such as `WWW-Authenticate` survive.
- **A response a middleware returns skips the handlers** — the auth gate's 401 is
  in the access log only. An Errors view with no 401s is correct.
- **Order is the guarantee.** Auth innermost, so its 401s are logged and get CORS
  headers; CORS outermost, so the logger's own 500 carries them too — otherwise
  the browser reports a CORS failure instead of the 500.
- **Streams, background work and sockets fall outside both nets.** `call_next`
  returns at the headers: a streamed reply is timed to its first byte, and a crash
  mid-stream is logged as a 200 with no error row. Socket.IO wrapping the ASGI
  app skips the middleware entirely. Such code logs its own failures, minus the
  expected upstream ones (rate limits, dropped connections) the user is shown.
- **`str(exc)` can be empty** (`KeyError()`) — fall back to `repr`. Truncate
  everything: message 2 000, traceback 20 000, source 500, repr 1 000.
- **The viewer.** Only rows with a traceback used to expand, so long messages
  stayed clipped at two lines — every row expands now, with `break-all` so URLs
  wrap. Only the newest page polls (older pages hold still under the reader), and
  any filter change resets to page 1. Naive-UTC strings get a `Z` before
  `new Date()`, or times read as browser-local. The user filter loads
  deactivated accounts, so a departed user's rows stay reachable.

## Extension points

- `user_id_for_token(session, token)` — your auth's token → user id.
- `NEVER_LOG_PATHS`, `should_log`, and where the GET flag lives.
- `SITE_TZ` / `SITE_TIME_ZONE` — the wall clock for day filters and times.
- `require_admin`; `_who()` — the two things people know a user by.
- **Retention.** The source keeps everything; choose a window per table and a
  scheduler (`created_at` is indexed, so a dated delete is cheap).
- **Other readers.** "What went wrong for this user lately" — the source attaches
  a user's last two hours of errors and failed requests to bug reports (§11).
- **Hosting.** An admin-only tab in a management hub (`console-app-shell`); polls
  with `usePolling` from `system-status-popover`; switch toasts can go through
  `toast-notification-history`.
