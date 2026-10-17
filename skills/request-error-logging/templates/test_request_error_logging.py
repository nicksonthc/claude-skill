"""Smoke tests for the request/error logging wiring — no database touched.

A throwaway app is wired exactly like main.py (handlers on the bare app, then
auth gate, access log, CORS), and the writers are monkeypatched to record what
they would have written. Adjust the `app.*` imports to where the modules live,
and keep `build_app` in step with your own main.py wiring order.
"""

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.responses import JSONResponse

from app.api.routes import system_log
from app.core import error_logging, http_logging
from app.core.error_logging import log_exceptions, register_error_logging
from app.core.http_logging import http_logging_middleware
from app.services import settings_service

ORIGIN = "http://terminal.test"


class Order(BaseModel):
    qty: int


@pytest.fixture
def logs(monkeypatch):
    seen = {"errors": [], "requests": [], "flag": False}

    async def fake_log_error(**kw):
        seen["errors"].append(kw)

    async def fake_write(**kw):
        seen["requests"].append(kw)

    async def flag():
        return seen["flag"]

    monkeypatch.setattr(error_logging, "log_error", fake_log_error)
    monkeypatch.setattr(http_logging, "write_request_log", fake_write)
    monkeypatch.setattr(settings_service, "log_get_requests", flag)
    return seen


async def auth_gate(request: Request, call_next):
    """Stands in for the app's gate: answers 401 by RETURNING a response."""
    if request.url.path.startswith("/api/private"):
        if request.headers.get("authorization") != "Bearer good":
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)
        request.state.auth_user_id = 7
    return await call_next(request)


def build_app() -> FastAPI:
    app = FastAPI()
    register_error_logging(app)
    app.middleware("http")(auth_gate)
    app.middleware("http")(http_logging_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/items")
    async def items():
        return []

    @app.post("/api/items", status_code=201)
    async def add_item():
        return {"id": 1}

    @app.get("/api/orders/{code}")
    async def order(code: str):
        raise HTTPException(404, f"No order {code}")

    @app.get("/api/guarded")
    async def guarded():
        raise HTTPException(401, "Invalid session", headers={"WWW-Authenticate": "Bearer"})

    @app.post("/api/orders")
    async def create(body: Order):
        return body

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("kaboom")

    @app.get("/api/empty-boom")
    async def empty_boom():
        raise KeyError()

    @app.post("/api/login")
    async def login(request: Request):
        request.state.log_user_id = 42
        return {"token": "t"}

    @app.get("/api/private/me")
    async def me(request: Request):
        return {"id": request.state.auth_user_id}

    return app


@pytest.fixture
def client(logs):
    return TestClient(build_app())


def test_health_never_logged(client, logs):
    logs["flag"] = True
    assert client.get("/api/health").status_code == 200
    assert logs["requests"] == [] and logs["errors"] == []


def test_successful_get_gated_by_flag(client, logs):
    client.get("/api/items")
    assert logs["requests"] == []
    logs["flag"] = True
    client.get("/api/items")
    assert [r["status_code"] for r in logs["requests"]] == [200]


def test_writes_always_logged(client, logs):
    assert client.post("/api/items").status_code == 201
    assert (logs["requests"][0]["method"], logs["requests"][0]["status_code"]) == ("POST", 201)


def test_http_exception_logged_and_answer_unchanged(client, logs):
    r = client.get("/api/orders/ABC")
    assert r.status_code == 404 and r.json() == {"detail": "No order ABC"}
    (e,) = logs["errors"]
    assert e["kind"] == "http" and e["status_code"] == 404
    assert e["source"] == "GET /api/orders/{code}"  # the template groups rows
    assert e["path"] == "/api/orders/ABC"
    assert logs["requests"][0]["status_code"] == 404  # a failed GET is always kept


def test_default_handler_keeps_headers(client, logs):
    r = client.get("/api/guarded")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_router_404_is_logged(client, logs):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert logs["errors"][0]["source"] == "GET /api/nope"


def test_validation_summary_leaves_values_out(client, logs):
    r = client.post("/api/orders", json={"qty": "hunter2"})
    assert r.status_code == 422
    (e,) = logs["errors"]
    assert e["exception_type"] == "RequestValidationError"
    assert e["message"].startswith("body.qty: ") and "hunter2" not in e["message"]


def test_unhandled_becomes_plain_500_with_cors(client, logs):
    r = client.get("/api/boom", headers={"Origin": ORIGIN})
    assert r.status_code == 500 and r.json() == {"detail": "Internal Server Error"}
    assert r.headers["access-control-allow-origin"] == ORIGIN  # CORS is outermost
    (e,) = logs["errors"]
    assert e["kind"] == "exception" and "kaboom" in e["traceback_text"]
    (q,) = logs["requests"]
    assert q["status_code"] == 500 and q["error"] == "RuntimeError('kaboom')"


def test_empty_message_falls_back_to_repr(client, logs):
    client.get("/api/empty-boom")
    assert logs["errors"][0]["message"] == "KeyError()"


def test_sign_in_names_its_user(client, logs):
    client.post("/api/login")
    assert logs["requests"][0]["user_id"] == 42


def test_gate_401_is_access_log_only(client, logs):
    assert client.get("/api/private/me").status_code == 401
    assert logs["requests"][0]["status_code"] == 401
    assert logs["errors"] == []  # a returned response never reaches the handlers


def test_auth_gate_user_reaches_the_logger(client, logs):
    logs["flag"] = True
    client.get("/api/private/me", headers={"Authorization": "Bearer good"})
    assert logs["requests"][0]["user_id"] == 7


def test_decorator_logs_and_reraises(logs):
    @log_exceptions("job")
    async def job():
        raise ValueError("bad")

    @log_exceptions()
    async def flow():
        raise HTTPException(409, "taken")

    with pytest.raises(ValueError):
        asyncio.run(job())
    with pytest.raises(HTTPException):
        asyncio.run(flow())
    assert [e["source"] for e in logs["errors"]] == ["job"]  # HTTPException passed through


def test_decorated_class_from_sync_code_inside_a_loop(logs):
    @log_exceptions()
    class Worker:
        def tick(self):
            raise RuntimeError("tick")

        def _private(self):
            raise RuntimeError("private")

    async def main():
        with pytest.raises(RuntimeError):
            Worker().tick()
        with pytest.raises(RuntimeError):
            Worker()._private()  # not wrapped: private
        assert len(error_logging._pending) == 1  # the write is referenced…
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not error_logging._pending  # …until it finished

    asyncio.run(main())
    (e,) = logs["errors"]
    assert e["source"].endswith("Worker.tick")


def test_writers_never_raise_when_the_database_is_down(monkeypatch):
    def down():
        raise ConnectionRefusedError("database down")

    for module in (error_logging, http_logging, settings_service):
        monkeypatch.setattr(module, "async_session_maker", down)
    asyncio.run(error_logging.log_error(kind="exception", source="x", message="m"))
    asyncio.run(
        http_logging.write_request_log(
            method="GET", path="/", query="", status_code=200, duration_ms=1,
            client_ip=None, error=None, user_id=None, token="t",
        )
    )
    settings_service._flag_cache.clear()
    assert asyncio.run(settings_service.flag("log_get_requests", True)) is True


def test_local_day_start(monkeypatch):
    monkeypatch.setattr(system_log, "SITE_TZ", ZoneInfo("Asia/Singapore"))  # GMT+8
    assert system_log.local_day_start(date(2026, 10, 17)) == datetime(2026, 10, 16, 16, 0)
