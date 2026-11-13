"""GitHub REST through `gh api`, for the pipeline scripts.

Claude Code cloud sessions reach GitHub through a proxy that refuses GraphQL (`gh pr …`, `gh issue …`) and search
(`search/issues`), so every call here is a repository-scoped REST call. Callers honour DRY RUN before they write.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from typing import Any, Optional

ROUTINE_APP = "claude"  # performed_via_github_app.slug on everything a routine posts
BOTS = {"coderabbitai", "github-actions", "dependabot"}
MAX_PAGES = 100


class GhError(RuntimeError):
    """A failed `gh api` call. `status` is the HTTP status when gh reported one."""

    def __init__(self, path: str, stderr: str):
        found = re.search(r"HTTP (\d{3})", stderr or "")
        self.status = int(found.group(1)) if found else None
        super().__init__(f"gh api {path} failed: {(stderr or '').strip()}")


def gh_pages(path: str, key: Optional[str] = None) -> list[Any]:
    """Every page of a REST GET, one request per page.

    Not `gh api --paginate`: it follows the response's `Link: rel="next"`, and GitHub writes that URL in the
    numeric-ID form `repositories/{id}/...`, which the Claude Code GitHub proxy refuses (403, "Numeric-ID repository
    paths ... are not supported through this proxy"). Walking `page=N` on the `repos/{owner}/{repo}/...` path the
    caller gave keeps every request in the form the proxy serves. An object page wraps its list in `key` (check runs:
    `check_runs`) or `items` (search); a single object, such as one PR, is fetched once.
    """
    found = re.search(r"[?&]per_page=(\d+)", path)
    per_page = int(found.group(1)) if found else 0
    pages: list[Any] = []
    for number in range(1, MAX_PAGES + 1):
        sep = "&" if "?" in path else "?"
        proc = subprocess.run(["gh", "api", f"{path}{sep}page={number}"], capture_output=True, text=True)
        if proc.returncode:
            raise GhError(path, proc.stderr)
        page = json.loads(proc.stdout)
        if isinstance(page, dict):
            items = page.get(key) if key else page.get("items")
        else:
            items = page
        if not isinstance(items, list):
            return [page]  # a single object: there is nothing to page through
        pages.append(page)
        if not per_page or len(items) < per_page:
            break
    return pages


def gh_items(path: str, key: Optional[str] = None) -> list[dict]:
    """A paged REST list, flattened. Object pages wrap their list: search in `items`, check runs in `check_runs`."""
    items: list[dict] = []
    for page in gh_pages(path, key):
        items.extend(page.get(key or "items", []) if isinstance(page, dict) else page)
    return items


def gh_json(path: str) -> Any:
    """One REST GET without paging: an object, or the first page of a list."""
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if proc.returncode:
        raise GhError(path, proc.stderr)
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def gh_write(method: str, path: str, payload: dict) -> Any:
    """A REST write. The JSON body goes in on stdin, so no post text ever passes through a shell."""
    proc = subprocess.run(
        ["gh", "api", "-X", method, path, "--input", "-"], input=json.dumps(payload), capture_output=True, text=True
    )
    if proc.returncode:
        raise GhError(path, proc.stderr)
    return json.loads(proc.stdout) if proc.stdout.strip() else None


class GitHub:
    """Repository-scoped REST for one repo. Tests swap in a fake with the same four methods."""

    def __init__(self, repo: str):
        self.repo = repo

    def list(self, path: str, key: Optional[str] = None) -> list[dict]:
        return gh_items(f"repos/{self.repo}/{path}", key)

    def page(self, path: str) -> Any:
        return gh_json(f"repos/{self.repo}/{path}") or []

    def get(self, path: str) -> Optional[dict]:
        """One object, or None when GitHub answers 404."""
        try:
            return gh_json(f"repos/{self.repo}/{path}")
        except GhError as err:
            if err.status == 404:
                return None
            raise

    def write(self, method: str, path: str, payload: dict) -> Any:
        return gh_write(method, f"repos/{self.repo}/{path}", payload)


def ts(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def when(item: dict) -> Optional[datetime]:
    """When a comment, review or event happened. Reviews carry `submitted_at`, everything else `created_at`."""
    return ts(item.get("submitted_at") or item.get("created_at"))


def app_of(item: dict) -> Optional[str]:
    return (item.get("performed_via_github_app") or {}).get("slug")


def login(item: dict) -> str:
    return ((item.get("user") or item.get("actor") or {}).get("login")) or ""


def is_bot(name: str) -> bool:
    return name in BOTS or name.endswith("[bot]")


def by_routine(item: dict) -> bool:
    """A routine of this pipeline made it. Routines post as the repo owner, so only the app field tells."""
    return app_of(item) == ROUTINE_APP


def is_human(item: dict) -> bool:
    return app_of(item) is None and not is_bot(login(item))
