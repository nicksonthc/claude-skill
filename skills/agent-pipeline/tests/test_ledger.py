"""ledger.py, cronexp.py and the run-ledger Stop hook: every run leaves one record, wherever it is stored."""

from __future__ import annotations

import base64
import copy
import io
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cronexp
import ledger
import pytest
from conftest import FIXTURES, SKILL, FakeGitHub, load_profile
from ghrest import GhError

PROFILE = load_profile()
HOOK = SKILL / "core" / "hooks" / "run-ledger.py"


def test_begin_opens_one_record_per_run_and_finish_stores_it_on_the_ledger_branch(run_dir):
    state = ledger.begin(PROFILE, "pr-evaluator")
    assert (state["routine"], state["role"], state["outcome"] if "outcome" in state else None) == (
        "pr-evaluator",
        "pr-evaluator",
        None,
    )
    assert ledger.begin(PROFILE, "pr-evaluator")["started_at"] == state["started_at"], "a second begin keeps the run"
    gh = FakeGitHub({"branches/pipeline-ledger": {"name": "pipeline-ledger"}})
    record, sink = ledger.finish(PROFILE, gh, "wrote", " evaluated 1 PR ", ["pr:5:PASS"])
    assert (
        sink == "git"
        and record["summary"] == "evaluated 1 PR"
        and record["items"] == [{"kind": "pr", "number": 5, "result": "PASS"}]
    )
    method, path, payload = gh.writes[-1]
    day = state["started_at"][:10].replace("-", "/")
    assert (method, path) == ("PUT", f"contents/runs/{day}/pr-evaluator--{state['session']}.json")
    assert payload["branch"] == "pipeline-ledger" and "[skip ci]" in payload["message"]
    assert json.loads(base64.b64decode(payload["content"]))["outcome"] == "wrote"
    assert ledger.load_state()["flushed"] == "git"


def test_finish_needs_begin_and_a_dry_run_stores_nothing(run_dir):
    with pytest.raises(ledger.LedgerError, match="begin"):
        ledger.finish(PROFILE, FakeGitHub(), "noop", "x", [])
    ledger.begin(PROFILE, "scorecard", dry_run=True)
    gh = FakeGitHub()
    record, sink = ledger.finish(PROFILE, gh, "noop", "nothing to do", [])
    assert sink == "dry-run" and gh.writes == [] and record["dry_run"] is True
    with pytest.raises(ledger.LedgerError, match="outcome"):
        ledger.begin(PROFILE, "scorecard") and ledger.finish(PROFILE, gh, "great", "x", [])


def test_the_first_write_creates_the_ledger_branch_as_an_orphan_and_conflicts_are_retried(monkeypatch):
    monkeypatch.setattr(ledger.time, "sleep", lambda s: None)
    attempts = []

    def put(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise GhError("contents/x", "gh: conflict (HTTP 409)")
        return {"content": {}}

    gh = FakeGitHub(
        {
            ("POST", "git/trees"): {"sha": "t1"},
            ("POST", "git/commits"): {"sha": "c1"},
            ("PUT", "contents/runs/x.json"): put,
        }
    )
    ledger.git_put(gh, "pipeline-ledger", "runs/x.json", {"a": 1}, "msg [skip ci]")
    kinds = [(m, p) for m, p, _ in gh.writes]
    assert kinds[:3] == [("POST", "git/trees"), ("POST", "git/commits"), ("POST", "git/refs")]
    assert gh.writes[1][2]["parents"] == [] and gh.writes[2][2] == {"ref": "refs/heads/pipeline-ledger", "sha": "c1"}
    assert len(attempts) == 2


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_turso_takes_the_record_when_it_is_set_up_and_git_takes_it_when_turso_fails(run_dir, monkeypatch):
    profile = copy.deepcopy(PROFILE)
    profile["ledger"] = {"turso_url": "libsql://runs-acme.turso.io"}
    sent = []

    def ok(request, timeout):
        sent.append((request.full_url, json.loads(request.data), dict(request.headers)))
        return Response(
            json.dumps(
                {"results": [{"type": "ok", "response": {"type": "execute", "result": {}}}, {"type": "ok"}]}
            ).encode()
        )

    monkeypatch.setenv("PIPELINE_LEDGER_TOKEN", "t0k")
    monkeypatch.setattr(ledger.urllib.request, "urlopen", ok)
    ledger.begin(profile, "pr-evaluator")
    gh = FakeGitHub({"branches/pipeline-ledger": {"name": "pipeline-ledger"}})
    _, sink = ledger.finish(profile, gh, "noop", "nothing", [])
    url, body, headers = sent[0]
    assert sink == "turso" and url == "https://runs-acme.turso.io/v2/pipeline" and gh.writes == []
    assert body["requests"][0]["stmt"]["sql"].startswith("INSERT INTO pipeline_runs") and body["requests"][-1] == {
        "type": "close"
    }
    assert headers["Authorization"] == "Bearer t0k"

    def down(request, timeout):
        return Response(
            json.dumps({"results": [{"type": "error", "error": {"message": "no such table: pipeline_runs"}}]}).encode()
        )

    monkeypatch.setattr(ledger.urllib.request, "urlopen", down)
    ledger.save_state({**ledger.load_state(), "outcome": None, "flushed": None, "session": "s2"})
    record, sink = ledger.finish(profile, gh, "noop", "nothing", [])
    assert sink == "git" and "no such table" in record["fallback"]
    assert json.loads(base64.b64decode(gh.writes[-1][2]["content"]))["fallback"].startswith("git: turso failed")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_records_are_read_back_from_the_ledger_branch_with_one_fetch(tmp_path):
    origin, seed, work = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "init", "-q", "-b", "pipeline-ledger", str(seed))
    for day, name, summary in [("2026/10/01", "old", "too old"), ("2026/11/12", "r1", "kept — with an em dash")]:
        target = seed / "runs" / day / f"pr-evaluator--{name}.json"
        target.parent.mkdir(parents=True)
        target.write_text(
            json.dumps(
                {
                    "session": name,
                    "routine": "pr-evaluator",
                    "started_at": day.replace("/", "-") + "T01:00:00Z",
                    "summary": summary,
                }
            )
        )
    git(seed, "add", ".")
    git(seed, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "ledger")
    git(seed, "push", "-q", str(origin), "pipeline-ledger")
    git(tmp_path, "clone", "-q", str(origin), str(work))
    since = datetime(2026, 11, 1, tzinfo=timezone.utc)
    records = ledger.git_records("pipeline-ledger", since, cwd=work)
    assert [r["session"] for r in records] == ["r1"] and records[0]["summary"].endswith("em dash")
    assert ledger.git_records("no-such-branch", since, cwd=work) == []


def test_cron_slots_follow_cron_semantics():
    week = datetime(2026, 11, 9, tzinfo=timezone.utc), datetime(2026, 11, 16, tzinfo=timezone.utc)  # Mon..Mon
    build = cronexp.slots("0 1,4,7 * * 1-5", *week)
    assert len(build) == 15 and build[0] == datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)
    groom = cronexp.slots("30 23 * * 0-4", *week)
    assert [s.weekday() for s in groom] == [0, 1, 2, 3, 6]  # Mon–Thu and Sun
    either = cronexp.slots(
        "0 0 15 * MON", datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc)
    )
    assert sorted({s.day for s in either}) == [2, 9, 15, 16, 23, 30]
    assert len(cronexp.slots("*/15 * * * *", *week)) == 7 * 24 * 4
    with pytest.raises(ValueError):
        cronexp.slots("0 1 * *", *week)


def stop_hook(payload: dict, run_dir: Path, remote: str = "true") -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "CLAUDE_CODE_REMOTE": remote,
        "PIPELINE_RUN_DIR": str(run_dir),
        "PIPELINE_PROFILE": str(FIXTURES / "release-repo/.claude/routines/pipeline.yml"),
    }
    return subprocess.run(["python3", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env)


def test_the_stop_hook_ignores_other_sessions_and_blocks_an_unfinished_run_once(run_dir):
    assert stop_hook({}, run_dir).stdout == "", "no run state: not a pipeline session"
    ledger.begin(PROFILE, "scorecard", dry_run=True)
    assert stop_hook({}, run_dir, remote="").stdout == "", "local sessions are left alone"
    first = stop_hook({"stop_hook_active": False}, run_dir)
    assert (
        json.loads(first.stdout)["decision"] == "block" and "pipeline.py finish" in json.loads(first.stdout)["reason"]
    )
    second = stop_hook({"stop_hook_active": True}, run_dir)
    state = ledger.load_state()
    assert second.stdout == "" and state["outcome"] == "failed" and state["flushed"] == "dry-run"
    assert stop_hook({"stop_hook_active": True}, run_dir).stdout == "", "a stored run never blocks again"
