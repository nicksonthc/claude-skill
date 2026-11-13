"""The run ledger: one record per routine run, whatever the run did.

`pipeline.py begin` opens a record and `pipeline.py finish` closes and stores it. The Stop hook
(`core/hooks/run-ledger.py`) holds a session open until that happens, so no-op and failed runs leave a trace too.

Where a record goes: Turso, when the profile sets `ledger.turso_url`. Otherwise, or when Turso fails, it is one JSON
file per run on the `ledger.branch` branch (default `pipeline-ledger`), written through the Contents API. GitHub
stays the home of work items and approvals; this is only the record of what each run did.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ghrest import GhError
from pcfg import CORE, core_version, lookup, routine

OUTCOMES = ("wrote", "noop", "gated", "failed")
RECORD_FIELDS = (
    "v",
    "repo",
    "routine",
    "role",
    "session",
    "trigger",
    "dry_run",
    "started_at",
    "ended_at",
    "outcome",
    "summary",
    "items",
    "writes",
    "core",
    "model",
    "fallback",
)
DEFAULT_BRANCH = "pipeline-ledger"
README = (
    "# Agent pipeline run ledger\n\n"
    "One JSON file per routine run under `runs/YYYY/MM/DD/`, and one per scorecard week under `metrics/`.\n"
    "Written by `.claude/routines/core/bin/ledger.py`; never edit by hand.\n"
)
TURSO_DDL = [
    "CREATE TABLE IF NOT EXISTS pipeline_runs (session TEXT NOT NULL, routine TEXT NOT NULL, repo TEXT NOT NULL, "
    "started_at TEXT NOT NULL, outcome TEXT, record TEXT NOT NULL, PRIMARY KEY (session, routine))",
    "CREATE INDEX IF NOT EXISTS pipeline_runs_repo_started ON pipeline_runs (repo, started_at)",
]
TURSO_UPSERT = (
    "INSERT INTO pipeline_runs (session, routine, repo, started_at, outcome, record) VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (session, routine) DO UPDATE SET outcome = excluded.outcome, record = excluded.record"
)


class LedgerError(RuntimeError):
    pass


# ---------------------------------------------------------------- run state


def state_path() -> Path:
    return Path(os.environ.get("PIPELINE_RUN_DIR") or "/tmp/agent-pipeline") / "run.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def session_id() -> str:
    return os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID") or f"local-{uuid.uuid4().hex[:12]}"


def load_state() -> Optional[dict]:
    path = state_path()
    return json.loads(path.read_text()) if path.exists() else None


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def begin(profile: dict, key: str, dry_run: bool = False) -> dict:
    """Open this session's run record. Calling it again in the same unfinished run keeps the first one."""
    entry = routine(profile, key)
    if entry is None:
        raise LedgerError(f"no routine {key!r} in pipeline.yml")
    current, remote = load_state(), os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID")
    if current and current.get("routine") == key and not current.get("outcome"):
        same = current.get("session") == remote if remote else str(current.get("session", "")).startswith("local-")
        if same:
            current["dry_run"] = bool(current.get("dry_run") or dry_run)
            save_state(current)
            return current
    session = session_id()
    state = {
        "v": 1,
        "repo": lookup(profile, "project.repo"),
        "routine": key,
        "role": entry.get("role") or "local",
        "session": session,
        "trigger": os.environ.get("PIPELINE_TRIGGER") or "schedule",
        "dry_run": bool(dry_run),
        "started_at": now_iso(),
        "core": core_version(),
        "model": entry.get("model"),
        "items": [],
        "writes": [],
    }
    save_state(state)
    return state


def parse_item(text: str) -> dict:
    """`kind:number:result`, e.g. `pr:12:PASS` or `issue:7:G5`. The result may itself contain colons."""
    kind, _, rest = text.partition(":")
    number, _, result = rest.partition(":")
    return {"kind": kind, "number": int(number) if number.isdigit() else number, "result": result}


def record_of(state: dict) -> dict:
    return {k: state[k] for k in RECORD_FIELDS if k in state}


def finish(profile: dict, gh, outcome: str, summary: str, items: list[str]) -> tuple[dict, str]:
    """Close the run record and store it. In a DRY RUN, nothing is stored and the caller prints the record."""
    state = load_state()
    if state is None:
        raise LedgerError("no run to finish: run `pipeline.py begin <routine key>` first")
    if outcome not in OUTCOMES:
        raise LedgerError(f"outcome must be one of {', '.join(OUTCOMES)}")
    state.update(outcome=outcome, summary=summary.strip(), ended_at=now_iso())
    state["items"] = (state.get("items") or []) + [parse_item(i) for i in items]
    save_state(state)
    return flush_state(profile, gh, state)


def flush_state(profile: dict, gh, state: dict) -> tuple[dict, str]:
    record = record_of(state)
    sink = "dry-run" if state.get("dry_run") else store(profile, gh, record)
    state["flushed"] = sink
    if record.get("fallback"):
        state["fallback"] = record["fallback"]
    save_state(state)
    return record, sink


# ---------------------------------------------------------------- sinks


def ledger_branch(profile: dict) -> str:
    return lookup(profile, "ledger.branch") or DEFAULT_BRANCH


def record_path(record: dict) -> str:
    day = (record.get("started_at") or now_iso())[:10].replace("-", "/")
    return f"runs/{day}/{record['routine']}--{record['session']}.json"


def store(profile: dict, gh, record: dict) -> str:
    """Turso when it is set up; git otherwise, and whenever Turso fails, so a record is never lost to an outage."""
    url = lookup(profile, "ledger.turso_url")
    if url:
        try:
            turso_execute(url, [(TURSO_UPSERT, turso_row(record))])
            return "turso"
        except Exception as err:  # any failure: keep the record, on git, and say why
            record["fallback"] = f"git: turso failed ({err})"[:300]
    message = f"chore(ledger): {record['routine']} {record.get('outcome')} [skip ci]"
    git_put(gh, ledger_branch(profile), record_path(record), record, message)
    return "git"


def ensure_branch(gh, name: str) -> None:
    """Create the ledger branch as an orphan (one README, no parent) the first time a run writes to it."""
    if gh.get(f"branches/{name}") is not None:
        return
    tree = gh.write(
        "POST", "git/trees", {"tree": [{"path": "README.md", "mode": "100644", "type": "blob", "content": README}]}
    )
    commit = gh.write(
        "POST",
        "git/commits",
        {"message": "chore(ledger): start the run ledger [skip ci]", "tree": tree["sha"], "parents": []},
    )
    try:
        gh.write("POST", "git/refs", {"ref": f"refs/heads/{name}", "sha": commit["sha"]})
    except GhError as err:
        if err.status != 422:  # 422: another run created it a moment ago
            raise


def git_put(gh, branch: str, path: str, data: dict, message: str, attempts: int = 4) -> None:
    """Create or replace one JSON file on the ledger branch. Concurrent writers get 409; retry them."""
    ensure_branch(gh, branch)
    content = base64.b64encode((json.dumps(data, indent=2, sort_keys=True) + "\n").encode()).decode()
    for attempt in range(attempts):
        payload = {"message": message, "content": content, "branch": branch}
        existing = gh.get(f"contents/{path}?ref={branch}")
        if existing and existing.get("sha"):
            payload["sha"] = existing["sha"]
        try:
            gh.write("PUT", f"contents/{path}", payload)
            return
        except GhError as err:
            if err.status in (409, 422) and attempt < attempts - 1:
                time.sleep(1 + attempt)
                continue
            raise


def turso_row(record: dict) -> list:
    blob = json.dumps(record, sort_keys=True)
    return [
        record["session"],
        record["routine"],
        record.get("repo"),
        record.get("started_at"),
        record.get("outcome"),
        blob,
    ]


def turso_value(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool) or not isinstance(value, int):
        return {"type": "text", "value": str(value)}
    return {"type": "integer", "value": str(value)}


def turso_execute(url: str, statements: list) -> list[dict]:
    """Run statements over Turso's HTTP pipeline API. The token comes from a cloud-environment network secret on the
    database host; locally, `PIPELINE_LEDGER_TOKEN` supplies it."""
    endpoint = ("https://" + url[len("libsql://") :] if url.startswith("libsql://") else url).rstrip(
        "/"
    ) + "/v2/pipeline"
    requests = [
        {"type": "execute", "stmt": {"sql": sql, "args": [turso_value(v) for v in args]}} for sql, args in statements
    ]
    headers = {"Content-Type": "application/json"}
    if os.environ.get("PIPELINE_LEDGER_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['PIPELINE_LEDGER_TOKEN']}"
    body = json.dumps({"requests": requests + [{"type": "close"}]}).encode()
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
    except urllib.error.HTTPError as err:
        raise LedgerError(f"turso HTTP {err.code}: {err.read()[:200].decode(errors='replace')}") from err
    results = data.get("results") or []
    for result in results:
        if result.get("type") == "error":
            raise LedgerError(f"turso: {(result.get('error') or {}).get('message')}")
    return [((r.get("response") or {}).get("result") or {}) for r in results[: len(statements)]]


def init_db(profile: dict) -> None:
    url = lookup(profile, "ledger.turso_url")
    if not url:
        raise LedgerError("ledger.turso_url is not set in pipeline.yml")
    turso_execute(url, [(sql, []) for sql in TURSO_DDL])


def put_metrics(profile: dict, gh, week: str, data: dict) -> str:
    """The scorecard's numbers for one ISO week, as JSON on the ledger branch (derived data: git is enough)."""
    path = f"metrics/{week}.json"
    git_put(gh, ledger_branch(profile), path, data, f"chore(ledger): scorecard {week} [skip ci]")
    return path


# ---------------------------------------------------------------- reading


def git_records(branch: str, since: datetime, cwd: Optional[Path] = None) -> list[dict]:
    """Every run record on the ledger branch from `since` on, read through one shallow fetch."""
    cwd = cwd or CORE
    ref = f"refs/remotes/origin/{branch}"
    fetch = ["git", "fetch", "--quiet", "--depth=1", "origin", f"+refs/heads/{branch}:{ref}"]
    if subprocess.run(fetch, capture_output=True, cwd=cwd).returncode:
        return []  # no ledger branch yet
    listing = subprocess.run(
        ["git", "ls-tree", "-r", ref, "--", "runs"], capture_output=True, text=True, cwd=cwd
    ).stdout
    shas = []
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        parts = path.split("/")
        if len(parts) != 5 or not parts[4].endswith(".json"):
            continue
        try:
            day = datetime(int(parts[1]), int(parts[2]), int(parts[3]), tzinfo=timezone.utc)
        except ValueError:
            continue
        if day + timedelta(days=1) > since:
            shas.append(meta.split()[2])
    if not shas:
        return []
    batch = subprocess.run(
        ["git", "cat-file", "--batch"], input=("\n".join(shas) + "\n").encode(), capture_output=True, cwd=cwd
    )
    data, pos, records = batch.stdout, 0, []
    while pos < len(data):
        newline = data.index(b"\n", pos)
        header = data[pos:newline].split()
        if len(header) < 3:  # "<sha> missing"
            pos = newline + 1
            continue
        size, start = int(header[2]), newline + 1
        try:
            records.append(json.loads(data[start : start + size]))
        except ValueError:
            pass
        pos = start + size + 1
    return records


def read_records(profile: dict, since: datetime, cwd: Optional[Path] = None) -> list[dict]:
    """Run records from Turso (when set up) and the ledger branch, merged by run, oldest first."""
    found: dict = {}
    url = lookup(profile, "ledger.turso_url")
    if url:
        query = "SELECT record FROM pipeline_runs WHERE repo = ? AND started_at >= ? ORDER BY started_at"
        try:
            result = turso_execute(
                url, [(query, [lookup(profile, "project.repo"), since.strftime("%Y-%m-%dT%H:%M:%SZ")])]
            )[0]
            for row in result.get("rows") or []:
                record = json.loads(row[0]["value"])
                found[(record.get("session"), record.get("routine"))] = record
        except Exception as err:
            print(f"warning: could not read the Turso ledger ({err}); using the git ledger only", file=sys.stderr)
    for record in git_records(ledger_branch(profile), since, cwd):
        found.setdefault((record.get("session"), record.get("routine")), record)
    return sorted(
        (r for r in found.values() if (r.get("started_at") or "") >= since.strftime("%Y-%m-%dT%H:%M:%SZ")),
        key=lambda r: r.get("started_at") or "",
    )
