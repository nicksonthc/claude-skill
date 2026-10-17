# request-error-logging — building blocks

Genericized from the source project, then re-verified: the backend modules below
pass `templates/test_request_error_logging.py` (16 tests, no database), and the
frontend templates typecheck under `strict`. Assumed layout: `app/core/`,
`app/models/`, `app/api/routes/`, `app/services/`, an async SQLModel session
factory at `app.db.session.async_session_maker`, and timestamps stored as naive
UTC (`TIMESTAMP WITHOUT TIME ZONE`; asyncpg rejects aware values in naive
columns). Sections are numbered to match SKILL.md's "Moving parts"; a section
that serves several parts carries all their numbers.

## 1. Tables

```python
# app/core/time.py
from datetime import datetime, timezone


def naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
```

```python
# app/models/request_log.py
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import naive_utcnow


class RequestLog(SQLModel, table=True):
    """One row per HTTP request that earns one, written by the access-log
    middleware. Append-only. `user_id` is a plain int (no FK) so the log stays
    independent of the users table and a bad value can never block a write.
    `error` holds the exception repr when the request 500'd."""

    id: int | None = Field(default=None, primary_key=True)
    method: str
    path: str = Field(index=True)
    query_string: str | None = Field(default=None)
    status_code: int = Field(index=True)
    duration_ms: int
    client_ip: str | None = Field(default=None)
    user_id: int | None = Field(default=None, index=True)
    error: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=naive_utcnow, index=True)
```

```python
# app/models/error_log.py
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import naive_utcnow


class ErrorLog(SQLModel, table=True):
    """One row per HTTP error or program exception, written by
    app.core.error_logging. Unlike `requestlog` (metadata only), this holds the
    exception itself: the detail a service raised, or the type + full traceback
    of a crash. `user_id` is a plain int (no FK), as in `requestlog`."""

    id: int | None = Field(default=None, primary_key=True)
    # "http" = a raised HTTPException / 422 (deliberate flow);
    # "exception" = an unhandled program error (a bug).
    kind: str = Field(index=True)
    # Where: "POST /api/orders/{code}/close" (the route template) for HTTP
    # errors, "module.func" or a given label for decorated non-request code.
    source: str = Field(index=True)
    status_code: int | None = Field(default=None, index=True)
    exception_type: str | None = Field(default=None)
    message: str
    traceback: str | None = Field(default=None)
    method: str | None = Field(default=None)
    path: str | None = Field(default=None, index=True)  # the concrete path
    client_ip: str | None = Field(default=None)
    user_id: int | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=naive_utcnow, index=True)
```

Migrate with Alembic autogenerate, then check the indexes made it:
`requestlog(created_at, path, status_code, user_id)` and
`errorlog(kind, source, status_code, path, user_id, created_at)`. There are no
foreign keys, on purpose. The source's reset/reseed purge lists leave both tables
out, so the record of a bad day survives the cleanup after it.

## 2 + 4 + 5 + 6. `app/core/error_logging.py` — writer, handlers, decorator, identity

`user_id_for_token(session, token) -> int | None` is the extension point: the
same token → user mapping the auth gate uses. In the source the bearer was a JWT
whose `jti` named an `authsession` row, so the mapping was
`select(AuthSession.user_id).where(AuthSession.token == jti_of(token))`.

```python
"""Centralised exception logging into the `errorlog` table.

Endpoints and services need no try/except of their own:

* `register_error_logging(app)` installs app-level handlers, so every deliberate
  4xx a route or service raises — and every 422 — is recorded while the
  response stays exactly what FastAPI would have sent.
* Unhandled program errors on the HTTP path are recorded by the access-log
  middleware (http_logging.py), which calls `log_request_error` with the full
  traceback and answers a plain 500.
* `log_exceptions` is an opt-in decorator for code that runs OUTSIDE a request
  (Socket.IO handlers, background jobs, scripts): log, then re-raise.

Writes use their own DB session and never raise: logging can't break the app.
"""

import asyncio
import functools
import inspect
import logging
import traceback as tb

from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import (
    http_exception_handler as fastapi_http_exception_handler,
    request_validation_exception_handler as fastapi_validation_handler,
)
from fastapi.exceptions import RequestValidationError
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.db.session import async_session_maker
from app.models.error_log import ErrorLog
from app.services.auth_service import user_id_for_token  # EXTENSION POINT

logger = logging.getLogger("app.errors")

MESSAGE_MAX = 2000
TRACEBACK_MAX = 20_000
SOURCE_MAX = 500


# --------------------------------------------------------------------------- #
# Who: one resolver, shared by both logs
# --------------------------------------------------------------------------- #


async def resolve_user_id(session: AsyncSession, token: str | None) -> int | None:
    """The user behind a bearer token — through the SAME function the auth gate
    uses, never a lookup of its own. (In the source the bearer was a JWT whose
    `jti` named the session row; the error log matched the raw token instead,
    found nobody, and logged every error as anonymous until both logs shared
    the auth module's resolver.) Never raises."""
    if not token:
        return None
    try:
        return await user_id_for_token(session, token)
    except Exception:
        return None


def request_user_id(request: Request) -> int | None:
    """A user someone already named on `request.state`, if any: `log_user_id`
    (set by the login route — a sign-in carries no token yet) wins over
    `auth_user_id` (cached by the auth gate, if yours caches one). Middleware,
    handlers and routes share `scope["state"]`, so a value set further in is
    visible out here once `call_next` returns."""
    for attr in ("log_user_id", "auth_user_id"):
        value = getattr(request.state, attr, None)
        if value is not None:
            return value
    return None


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    return None


def request_source(request: Request) -> str:
    """"POST /api/orders/{code}/close" — the route template when the request
    matched one (rows group by endpoint), else the concrete path (an
    unmatched 404, or a failure before routing)."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return f"{request.method} {template or request.url.path}"


# --------------------------------------------------------------------------- #
# The writer
# --------------------------------------------------------------------------- #


async def log_error(
    *,
    kind: str,
    source: str,
    message: str,
    status_code: int | None = None,
    exception_type: str | None = None,
    traceback_text: str | None = None,
    method: str | None = None,
    path: str | None = None,
    client_ip: str | None = None,
    token: str | None = None,
    user_id: int | None = None,
) -> None:
    """Persist one error row in its own session. Never raises. Pass `user_id`
    when known; otherwise `token` is resolved to one."""
    try:
        async with async_session_maker() as session:
            if user_id is None:
                user_id = await resolve_user_id(session, token)
            session.add(
                ErrorLog(
                    kind=kind,
                    source=source[:SOURCE_MAX],
                    status_code=status_code,
                    exception_type=exception_type,
                    message=(message or "")[:MESSAGE_MAX],
                    traceback=traceback_text[:TRACEBACK_MAX] if traceback_text else None,
                    method=method,
                    path=path,
                    client_ip=client_ip,
                    user_id=user_id,
                )
            )
            await session.commit()
    except Exception:  # logging must never break the app
        logger.warning("failed to write error log", exc_info=True)


async def log_request_error(request: Request, exc: BaseException) -> None:
    """Record an exception that happened while handling `request`."""
    is_http = isinstance(exc, StarletteHTTPException)
    await log_error(
        kind="http" if is_http else "exception",
        source=request_source(request),
        # str() of some exceptions is empty (KeyError(), TimeoutError()) — fall
        # back to repr so the row says something.
        message=str(exc.detail) if is_http else (str(exc) or repr(exc)),
        status_code=exc.status_code if is_http else 500,
        exception_type=type(exc).__name__,
        traceback_text=(
            None
            if is_http
            else "".join(tb.format_exception(type(exc), exc, exc.__traceback__))
        ),
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host if request.client else None,
        token=bearer_token(request),
        user_id=request_user_id(request),
    )


# --------------------------------------------------------------------------- #
# App-level handlers: log, then answer exactly as FastAPI would have
# --------------------------------------------------------------------------- #


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> Response:
    if exc.status_code >= 400:
        await log_request_error(request, exc)
    return await fastapi_http_exception_handler(request, exc)


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """A 422: keep `loc: msg` of the first five errors — short, and free of the
    submitted values (a malformed login body holds a password)."""
    summary = "; ".join(
        f"{'.'.join(str(p) for p in e.get('loc', []))}: {e.get('msg', '')}"
        for e in exc.errors()[:5]
    )
    await log_error(
        kind="http",
        source=request_source(request),
        message=summary or "Request validation failed",
        status_code=422,
        exception_type="RequestValidationError",
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host if request.client else None,
        token=bearer_token(request),
        user_id=request_user_id(request),
    )
    return await fastapi_validation_handler(request, exc)


def register_error_logging(app: FastAPI) -> None:
    """Install the handlers. Call once on the bare FastAPI app.

    Registered on Starlette's HTTPException (FastAPI's subclasses it), so the
    router's own 404/405 are caught as well as the ones routes raise. Unhandled
    (non-HTTP) exceptions are not handled here — the access-log middleware
    catches those first and calls `log_request_error` before answering 500."""
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)


# --------------------------------------------------------------------------- #
# Opt-in decorator for non-request code (sockets, scripts, background jobs)
# --------------------------------------------------------------------------- #

# The event loop holds tasks only weakly: keep a reference until each log
# write has finished, or it can be collected mid-flight.
_pending: set[asyncio.Task] = set()


def _fire(coro) -> None:
    """Run a log write from sync code: schedule it on the running loop when
    there is one, else run it to completion in a fresh loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop: a sync script. A pooled asyncpg engine cannot be reused
        # across loops — give such scripts an engine with NullPool.
        asyncio.run(coro)
        return
    task = loop.create_task(coro)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def log_exceptions(source: str | None = None):
    """Log-and-reraise decorator for code outside the HTTP request cycle.

    Apply to a function (sync or async) or a class (wraps the public functions
    defined on that class). Any exception is written to `errorlog`, then
    re-raised unchanged. HTTPExceptions pass through silently — the app-level
    handler owns those, so nothing is double-logged when the code runs inside
    a route. Generators and async generators are not covered: the wrapper
    returns them before their body runs.

        @log_exceptions()
        async def on_scan(sid, data): ...

        @log_exceptions("plc-sync")
        class PlcSync: ...
    """

    def decorate(target):
        if inspect.isclass(target):
            for name, member in list(vars(target).items()):
                if not name.startswith("_") and inspect.isfunction(member):
                    setattr(target, name, decorate(member))
            return target

        label = source or f"{target.__module__}.{target.__qualname__}"

        def _entry(exc: BaseException) -> dict:
            return dict(
                kind="exception",
                source=label,
                message=str(exc) or repr(exc),
                exception_type=type(exc).__name__,
                traceback_text=tb.format_exc(),
            )

        if inspect.iscoroutinefunction(target):

            @functools.wraps(target)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await target(*args, **kwargs)
                except HTTPException:
                    raise
                except Exception as exc:
                    await log_error(**_entry(exc))
                    raise

            return async_wrapper

        @functools.wraps(target)
        def sync_wrapper(*args, **kwargs):
            try:
                return target(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                _fire(log_error(**_entry(exc)))
                raise

        return sync_wrapper

    return decorate
```

## 2 + 3 + 7. `app/core/http_logging.py` — noise gate, access writer, middleware

```python
"""HTTP access log — one `requestlog` row per request that earns one.

Two hard guarantees:

* **The logger never breaks a request.** The row is written in its own DB
  session inside a broad try/except; any failure there is swallowed.
* **An unhandled handler exception becomes a plain 500.** Anything the app
  raised that is not an HTTPException (FastAPI turned those into 4xx responses
  further in) is logged with its traceback and answered as
  `500 {"detail": "Internal Server Error"}` instead of propagating.

The request body is never read: consuming the receive stream in a
BaseHTTPMiddleware can starve the endpoint, and bodies hold secrets (login
passwords). Method/path/query/status/timing/user is enough for an access log.

Not every request earns a row (`should_log`): NEVER_LOG_PATHS never do, and
successful GETs only while the `log_get_requests` flag is on, because polling
clients bury the writes worth auditing. Anything that failed always does.
"""

import logging
import time

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.error_logging import (
    bearer_token,
    log_request_error,
    request_user_id,
    resolve_user_id,
)
from app.db.session import async_session_maker
from app.models.request_log import RequestLog
from app.services import settings_service

logger = logging.getLogger("app.http")

# Never logged, whatever the flag says. Health is hit by the container
# healthcheck and by every open status popover: most of the table, telling
# nobody anything they can act on. Add readiness / metrics probes here.
NEVER_LOG_PATHS = frozenset({"/api/health"})
ERROR_REPR_MAX = 1000


async def should_log(path: str, method: str, status_code: int) -> bool:
    """Whether this request earns a row."""
    if path in NEVER_LOG_PATHS:
        return False
    # A request that failed is always worth keeping — the noise argument only
    # applies to reads that worked.
    if status_code >= 400 or method.upper() != "GET":
        return True
    return await settings_service.log_get_requests()


async def write_request_log(
    *,
    method: str,
    path: str,
    query: str,
    status_code: int,
    duration_ms: int,
    client_ip: str | None,
    error: str | None,
    user_id: int | None,
    token: str | None,
) -> None:
    """Persist one access-log row. Never raises."""
    try:
        async with async_session_maker() as session:
            if user_id is None:
                user_id = await resolve_user_id(session, token)
            session.add(
                RequestLog(
                    method=method,
                    path=path,
                    query_string=query or None,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    client_ip=client_ip,
                    user_id=user_id,
                    error=error,
                )
            )
            await session.commit()
    except Exception:  # logging must never break the request
        logger.warning("failed to write request log", exc_info=True)


async def http_logging_middleware(request: Request, call_next) -> Response:
    start = time.perf_counter()
    error_repr: str | None = None
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:  # unhandled -> 500 (HTTPExceptions never get here)
        logger.exception("unhandled error handling %s %s", request.method, request.url.path)
        error_repr = repr(exc)[:ERROR_REPR_MAX]
        status_code = 500
        # Full detail (type + traceback) goes to the errorlog table.
        await log_request_error(request, exc)
        response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)

    # Time to the response headers. For a streamed body (SSE, a download) that
    # is when the stream opened, not when it ended — and an exception raised
    # mid-stream happens after this point, outside this try.
    duration_ms = int((time.perf_counter() - start) * 1000)
    if not await should_log(request.url.path, request.method, status_code):
        return response

    await write_request_log(
        method=request.method,
        path=request.url.path,
        query=request.url.query,
        status_code=status_code,
        duration_ms=duration_ms,
        client_ip=request.client.host if request.client else None,
        error=error_repr,
        user_id=request_user_id(request),
        token=bearer_token(request),
    )
    return response
```

## 3 + 6. Wiring — middleware order, the sign-in, the auth gate, background tasks

```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import system_log
from app.core.auth_middleware import auth_middleware  # your gate, if you have one
from app.core.error_logging import register_error_logging
from app.core.http_logging import http_logging_middleware

app = FastAPI()

# Every raised HTTPException / 422 lands in `errorlog`; crashes are logged by
# the access-log middleware. No per-endpoint code.
register_error_logging(app)

# Each registration wraps the previous one, so the LAST registered runs first.
# Effective chain: CORS -> access log -> auth -> router.
app.middleware("http")(auth_middleware)          # innermost: its 401s still get logged
app.middleware("http")(http_logging_middleware)  # access log + 500 guard
app.add_middleware(                              # outermost: CORS on every answer,
    CORSMiddleware,                              # the logger's 500 included
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,  # bearer header, not cookies — this is what lets "*" work
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_log.router)

# If Socket.IO wraps the app (socketio.ASGIApp(sio, other_asgi_app=app)), its
# traffic never passes these middlewares: decorate the socket handlers with
# @log_exceptions instead.
```

```python
# app/api/routes/auth.py — the sign-in
@router.post("/login")
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)):
    user = await verify_credentials(session, body.username, body.password)
    if user is None:
        raise HTTPException(401, "Invalid username or password")  # logged, anonymous
    # The request carried no token yet — tell the access log who signed in.
    request.state.log_user_id = user.id
    return await issue_session(session, user)
```

```python
# app/core/auth_middleware.py — after the gate resolved the user
request.state.auth_user_id = user.id  # routes reuse it; so does the logger
return await call_next(request)
```

Code that runs after the response headers — a streamed reply, a task the
request started — is outside the middleware's `try` and outside the handlers.
It logs its own failures, attributed through the token captured when the work
began:

```python
import traceback

from app.core.error_logging import log_error


async def run_reply(conv_id: int, token: str | None) -> None:
    try:
        ...  # the long-running work
    except Exception as exc:
        # Expected upstream conditions (the LLM SDK's rate-limit and connection
        # errors, in the source) are shown to the user — they are not bugs.
        if not isinstance(exc, EXPECTED_UPSTREAM_ERRORS):
            await log_error(
                kind="exception",
                source="assistant.reply",
                message=f"{type(exc).__name__}: {exc}",
                exception_type=type(exc).__name__,
                traceback_text="".join(traceback.format_exception(exc)),
                method="POST",
                path=f"/api/chats/{conv_id}/messages",
                token=token,
            )
        ...  # then tell the user, release locks, etc.
```

If the failing work shares a DB session with later writes (a tool call inside
a chat turn, say), `await session.rollback()` before carrying on. `log_error`
uses its own session either way. Then show the user a plain line such as "The
lookup failed on the server — it has been logged for IT."

## 7. The GET flag — cached read, admin-only write, the switch

Any runtime-config store works. The source used a key/value `setting` table,
and this is the slice the access log needs:

```python
# app/services/settings_service.py
import time
from datetime import datetime

from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import naive_utcnow
from app.db.session import async_session_maker


class Setting(SQLModel, table=True):
    """A runtime-editable value, stored as a string so a new setting needs no
    schema change: the row appears on first write; until then readers fall
    back to the default."""

    key: str = Field(primary_key=True)
    value: str
    description: str | None = Field(default=None)
    updated_at: datetime = Field(default_factory=naive_utcnow)


LOG_GET_REQUESTS = "log_get_requests"
LOG_GET_REQUESTS_DEFAULT = False  # off: polling reads would bury the writes

_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def coerce_bool(value: str) -> bool | None:
    """Strict read; None if the text is neither. For the API boundary, where a
    bad value is rejected rather than silently defaulted."""
    text = value.strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def parse_bool(value: str | None, default: bool) -> bool:
    """Tolerant read of a stored value, falling back on anything unexpected."""
    if value is None:
        return default
    parsed = coerce_bool(value)
    return default if parsed is None else parsed


async def get_bool(session: AsyncSession, key: str, default: bool) -> bool:
    row = await session.get(Setting, key)
    return parse_bool(row.value if row else None, default)


async def set_value(session: AsyncSession, key: str, value: str) -> Setting:
    row = await session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
    else:
        row.value = value
        row.updated_at = naive_utcnow()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    _flag_cache.pop(key, None)  # this worker sees the change at once
    return row


# The middleware consults the flag on every successful GET, so it cannot
# afford a SELECT per request. Cached in-process; dropped the moment
# `set_value` writes the key. Each server worker holds its own cache, so after
# a change made through another worker the TTL is the worst-case lag.
FLAG_CACHE_TTL_SECONDS = 15.0
_flag_cache: dict[str, tuple[bool, float]] = {}


async def flag(key: str, default: bool) -> bool:
    """Cached boolean read in its own session, for callers outside a request's
    dependency scope (the logging middleware). Never raises: a DB problem here
    must not turn into a failed request."""
    now = time.monotonic()
    cached = _flag_cache.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]
    try:
        async with async_session_maker() as session:
            value = await get_bool(session, key, default)
    except Exception:
        return default  # not cached: the next request tries the DB again
    _flag_cache[key] = (value, now + FLAG_CACHE_TTL_SECONDS)
    return value


async def log_get_requests() -> bool:
    """Whether successful GETs get an access-log row."""
    return await flag(LOG_GET_REQUESTS, LOG_GET_REQUESTS_DEFAULT)
```

```python
# app/api/routes/settings.py — inside PUT /api/settings/{key}
value = body.value.strip()
if key == settings_service.LOG_GET_REQUESTS:
    # Admin-only: a diagnostics knob, and switching it off makes the record
    # quieter — not a call for the people running the floor.
    if user.role != Role.admin:
        raise HTTPException(403, f"{key} can only be changed by an admin")
    parsed = settings_service.coerce_bool(value)
    if parsed is None:
        raise HTTPException(400, f"{key} must be true or false")
    # Normalised, so the middleware never has to guess at what was typed.
    value = "true" if parsed else "false"
row = await settings_service.set_value(session, key, value)
```

The switch is `templates/frontend/RequestLoggingSwitch.tsx`: a labelled
`Switch`, a spinner while saving, and a toast that says what is still recorded
("Writes, and anything that failed, are still recorded."). Under it, say that
`/api/health` is never logged and that a change takes up to the TTL to reach
every worker. If it sits among per-browser preferences, badge it as affecting
every terminal: it is the one server-side value there.

## 8. Read API — `app/api/routes/system_log.py`

```python
"""The System Log (admin): the error log and the HTTP access log.

- ``GET /api/system-log/errors``    errors (``errorlog``), newest first
- ``GET /api/system-log/requests``  the access log (``requestlog``), newest
  first, filterable and paged

Both name the user behind each row, resolved from its ``user_id`` at read time
in one batched query (the log tables keep a plain int, no FK, so a log write
can never fail on it — and a renamed user shows their current name).
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_admin  # EXTENSION POINT: your admin gate
from app.db.session import get_session  # your request-scoped session dependency
from app.models.error_log import ErrorLog
from app.models.request_log import RequestLog
from app.models.user import User

router = APIRouter(prefix="/api/system-log", tags=["system-log"])

# EXTENSION POINT: the site's wall clock. Day filters mean local days; the
# columns hold naive UTC.
SITE_TZ = ZoneInfo("Asia/Singapore")


def local_day_start(day: date) -> datetime:
    """Local midnight of `day` as naive UTC, comparable with the columns."""
    local = datetime.combine(day, time.min, tzinfo=SITE_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


class ErrorLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    source: str
    status_code: int | None
    exception_type: str | None
    message: str
    traceback: str | None
    method: str | None
    path: str | None
    client_ip: str | None
    user_id: int | None
    created_at: datetime
    # Resolved now from user_id; null when anonymous (a failed sign-in) or the
    # account no longer exists.
    user_name: str | None = None
    user_code: str | None = None


class RequestLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    method: str
    path: str
    query_string: str | None
    status_code: int
    duration_ms: int
    client_ip: str | None
    user_id: int | None
    error: str | None
    created_at: datetime
    user_name: str | None = None
    user_code: str | None = None


class RequestLogPage(BaseModel):
    items: list[RequestLogOut]
    total: int
    limit: int
    offset: int


async def _users(session: AsyncSession, ids) -> dict[int, User]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    res = await session.exec(select(User).where(col(User.id).in_(wanted)))
    return {u.id: u for u in res.all()}


def _who(users: dict[int, User], user_id: int | None) -> dict:
    """EXTENSION POINT: the two things people recognise a user by (in the
    source: name + employee no.)."""
    u = users.get(user_id) if user_id is not None else None
    return {"user_name": u.name if u else None, "user_code": u.employee_no if u else None}


@router.get("/errors", response_model=list[ErrorLogOut])
async def list_error_logs(
    kind: str | None = Query(default=None, pattern="^(http|exception)$"),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ErrorLogOut]:
    stmt = select(ErrorLog)
    if kind is not None:
        stmt = stmt.where(ErrorLog.kind == kind)
    if user_id is not None:
        stmt = stmt.where(ErrorLog.user_id == user_id)
    rows = list((await session.exec(stmt.order_by(col(ErrorLog.id).desc()).limit(limit))).all())
    users = await _users(session, (r.user_id for r in rows))
    return [
        ErrorLogOut.model_validate(r).model_copy(update=_who(users, r.user_id))
        for r in rows
    ]


@router.get("/requests", response_model=RequestLogPage)
async def list_request_logs(
    user_id: int | None = Query(default=None),
    method: str | None = Query(default=None, pattern="^(GET|POST|PUT|PATCH|DELETE)$"),
    failed: bool = Query(default=False, description="Only status >= 400"),
    q: str | None = Query(default=None, max_length=120, description="Path contains"),
    date_from: date | None = Query(default=None, description="Local day, inclusive"),
    date_to: date | None = Query(default=None, description="Local day, inclusive"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RequestLogPage:
    conds = []
    if user_id is not None:
        conds.append(RequestLog.user_id == user_id)
    if method:
        conds.append(RequestLog.method == method)
    if failed:
        conds.append(RequestLog.status_code >= 400)
    if q and q.strip():
        conds.append(col(RequestLog.path).ilike(f"%{q.strip()}%"))
    if date_from is not None:
        conds.append(RequestLog.created_at >= local_day_start(date_from))
    if date_to is not None:
        # Half-open: before the NEXT local midnight, so the day's last second
        # is in and nothing of the following day is.
        conds.append(RequestLog.created_at < local_day_start(date_to + timedelta(days=1)))
    total = int((await session.exec(
        select(func.count()).select_from(RequestLog).where(*conds)
    )).one())
    rows = list((await session.exec(
        select(RequestLog).where(*conds)
        .order_by(col(RequestLog.id).desc()).offset(offset).limit(limit)
    )).all())
    users = await _users(session, (r.user_id for r in rows))
    items = [
        RequestLogOut.model_validate(r).model_copy(update=_who(users, r.user_id))
        for r in rows
    ]
    return RequestLogPage(items=items, total=total, limit=limit, offset=offset)
```

Ordering is `id desc`: on an append-only table it matches time order and rides
the primary key. The path filter's leading-wildcard `ilike` scans the table,
which is fine for an admin page on a table with retention.

## 9. The System Log page — `templates/frontend/`

| File | Merge into | What it carries |
|------|------------|-----------------|
| `types.ts` | `src/lib/types.ts` | DTO mirror of §8, kept in sync by hand (drop the `User` / `Setting` stand-ins) |
| `api.ts` | `src/lib/api.ts` | `errorLogs`, `requestLogs`, and `query()`, which drops `undefined` and `""` (so pass `failed \|\| undefined`) |
| `format.ts` | `src/lib/format.ts` | `fmtTime`: appends `Z` to the offset-less naive-UTC strings, formats in `SITE_TIME_ZONE` |
| `SystemLogTab.tsx` | a page or tab | the two views below |
| `RequestLoggingSwitch.tsx` | the admin settings | §7 |

- **HTTP requests:** filters are user, method, path, from and to, plus failed-only.
  - The path box is debounced 350 ms, and any filter change resets to page 1.
  - 50 rows a page, newest first, with "1–50 of N requests · newest first" and Newer / Older buttons.
  - The view polls every 15 s on page 1 only (`paused: page > 1`). Skeleton rows show until the first answer (`data === null`).
  - Status tones: ≥ 500 rose, 422 violet, 4xx amber, else emerald. Methods are tinted too, and a 500's repr shows in red under its path.
  - A line on the page says what the log leaves out.
- **Errors:** All / HTTP / Crashes plus a user filter; the newest 200, polled every 15 s.
  - Every row expands (click, Enter or Space, with `aria-expanded`) to the full message, method + path, client IP and the traceback.
  - The expanded text uses `break-all` + `whitespace-pre-wrap`, so long unbroken strings wrap.
- **Who:** shows the name plus a second identifier, or *anonymous* in italics. The user filter loads deactivated accounts too.
- **Needs:**
  - shadcn/ui `badge button card input label select skeleton switch table`, plus `cn` from `@/lib/utils`
  - lucide-react and sonner
  - `usePolling` from `system-status-popover`'s REFERENCE §3: it re-fetches on an interval, `paused` skips ticks, and a sequence ref drops out-of-order answers.
- **Hosting:** an admin-only route, gated twice — the page shows a lock card to
  non-admins, and the API answers 403. In the source the page is the admin-only
  entry of a management-hub registry (`console-app-shell`).

## 10. Smoke tests — `templates/test_request_error_logging.py`

`uv run pytest tests/test_request_error_logging.py`. The file builds a
throwaway app wired like §3 and monkeypatches the writers, so no database is
touched. It asserts:

- health is never logged
- a successful GET is logged only with the flag on, and writes always are
- a raised 404 is logged as `http` under its route template while the response stays unchanged
- `WWW-Authenticate` survives the handler
- the router's own 404 is logged
- a 422 summary omits the submitted value
- a crash becomes a plain 500 that still carries CORS headers, with a traceback row and a request row
- `KeyError()` is logged by its repr
- a sign-in is credited to its user, and the gate's user reaches the logger
- the gate's returned 401 is in the access log only
- the decorator logs and re-raises, passes HTTPExceptions through, wraps only a class's public functions, and holds a reference to the scheduled write
- the writers and the flag stay silent with the DB down
- the local-day boundary is correct

## 11. Other readers — "what went wrong for this user lately"

The source attaches this to every in-app bug report. It is often the real clue:

```python
from datetime import timedelta

from sqlmodel import col, select

RECENT = timedelta(hours=2)


async def recent_trouble(session, user_id: int, own_prefix: str) -> dict:
    """A user's errors and failed requests of the last RECENT. Leave out the
    reporting channel's own calls (`own_prefix`) — they are not the clue.
    Convert times to site time before showing them to people."""
    since = naive_utcnow() - RECENT
    errors = (await session.exec(
        select(ErrorLog)
        .where(ErrorLog.user_id == user_id, ErrorLog.created_at >= since)
        .order_by(col(ErrorLog.created_at).desc())
        .limit(10)
    )).all()
    failed = (await session.exec(
        select(RequestLog)
        .where(
            RequestLog.user_id == user_id,
            RequestLog.created_at >= since,
            RequestLog.status_code >= 400,
            ~col(RequestLog.path).startswith(own_prefix),
        )
        .order_by(col(RequestLog.created_at).desc())
        .limit(15)
    )).all()
    return {
        "recent_errors": [
            {"at": e.created_at.isoformat(), "kind": e.kind, "status": e.status_code,
             "where": e.source, "message": (e.message or "")[:400]}
            for e in errors
        ],
        "recent_failed_requests": [
            {"at": r.created_at.isoformat(), "request": f"{r.method} {r.path}",
             "status": r.status_code, "ms": r.duration_ms}
            for r in failed
        ],
    }
```
