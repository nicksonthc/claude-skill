from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# The tests import the core's scripts by path; a __pycache__ there would be vendored into every repo.
sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SKILL / "core" / "bin"))

ROUTINE = {"slug": "claude"}
REPO = "acme/orders-api"


class FakeGitHub:
    """ghrest.GitHub's four methods over canned REST data, keyed by the same paths the code requests.
    Writes are recorded; a route keyed by (method, path) answers a write, and a callable route may raise."""

    def __init__(self, routes: dict | None = None, repo: str = REPO):
        self.repo, self.routes, self.calls, self.writes = repo, dict(routes or {}), [], []

    def list(self, path, key=None):
        self.calls.append(path)
        return list(self.routes.get(path, []))

    def page(self, path):
        self.calls.append(path)
        return self.routes.get(path, [])

    def get(self, path):
        self.calls.append(path)
        return self.routes.get(path)

    def write(self, method, path, payload):
        self.writes.append((method, path, payload))
        answer = self.routes.get((method, path))
        if callable(answer):
            return answer(payload)
        return answer if answer is not None else {"html_url": f"https://github.com/{self.repo}/{path}"}


def load_profile(name: str = "release-repo") -> dict:
    return yaml.safe_load((FIXTURES / name / ".claude/routines/pipeline.yml").read_text())


def comment(body, login="alice", app=None, at="2026-11-01T00:00:00Z", id=1, url=None):
    return {
        "id": id,
        "user": {"login": login},
        "body": body,
        "created_at": at,
        "performed_via_github_app": app,
        "html_url": url or f"https://github.com/{REPO}/issues/1#issuecomment-{id}",
    }


def pull(n, head="groomed/7", base="release", sha="a" * 40, body="Closes #7", draft=False, fork=False):
    head_repo = "someone/fork" if fork else REPO
    return {
        "number": n,
        "title": f"PR {n}",
        "body": body,
        "draft": draft,
        "html_url": f"https://github.com/{REPO}/pull/{n}",
        "head": {"ref": head, "sha": sha, "repo": {"full_name": head_repo}},
        "base": {"ref": base, "repo": {"full_name": REPO}},
    }


def issue(n, title="Fix the thing", body="", app=None, state="open"):
    return {
        "number": n,
        "title": title,
        "body": body,
        "state": state,
        "performed_via_github_app": app,
        "html_url": f"https://github.com/{REPO}/issues/{n}",
    }


def labeled(actor="alice", app=None, label="groomed", at="2026-11-01T00:00:00Z"):
    return {
        "event": "labeled",
        "label": {"name": label},
        "actor": {"login": actor},
        "performed_via_github_app": app,
        "created_at": at,
    }


def check(name, conclusion="success", status="completed", app="github-actions", started="2026-11-01T01:00:00Z"):
    return {
        "id": 1,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "app": {"slug": app},
        "html_url": f"https://github.com/{REPO}/runs/1",
        "started_at": started,
        "output": {"title": "1 failed"},
    }


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """An isolated run-state dir and profile path, so ledger state never leaks between tests or into /tmp."""
    monkeypatch.setenv("PIPELINE_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("PIPELINE_PROFILE", str(FIXTURES / "release-repo/.claude/routines/pipeline.yml"))
    monkeypatch.delenv("CLAUDE_CODE_REMOTE_SESSION_ID", raising=False)
    return tmp_path / "run"
