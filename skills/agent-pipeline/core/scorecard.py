#!/usr/bin/env python3
"""Weekly outcome scorecard for one repo's agent-pipeline routines.

Reads `.claude/routines/pipeline.yml`, attributes each PR to a routine by its `attribution` branch patterns (removed
routines included, so their PRs keep being scored) and prints the whole hub comment as Markdown. Outcome metrics only,
never agent confidence. Read-only, and REST only (`gh api`): `gh pr list` goes through GraphQL, which Claude Code
sessions block with a 403.

    python3 .claude/routines/core/scorecard.py [--window 30] [--profile .claude/routines/pipeline.yml]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("PyYAML missing: pip install pyyaml")

CORE = Path(__file__).resolve().parent
DEFAULT_PROFILE = CORE.parent / "pipeline.yml"
ROUTINE_APP = "claude"  # performed_via_github_app.slug on everything a routine posts
BOTS = {"coderabbitai", "github-actions", "dependabot"}
# A redo request is a human line starting `#redo`; people often write it below the feedback, not first.
REDO_LINE = re.compile(r"^\s*#redo\b", re.IGNORECASE | re.MULTILINE)
REDO_DONE = re.compile(r"<!-- REDO-DONE\b[^>]*\bstatus=done\b")
# A commit this long after the PR was opened counts as a revision (initial pushes land within minutes).
REVISION_GRACE = timedelta(minutes=10)
AI_HEADER = "> 🤖 **AI-generated** · Claude Code"
FOOTER = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"


def gh_pages(path: str) -> list[Any]:
    """Every page of a REST GET. `gh api --paginate` prints one JSON document per page, back to back."""
    proc = subprocess.run(["gh", "api", "--paginate", path], capture_output=True, text=True)
    if proc.returncode:
        sys.exit(f"gh api {path} failed: {proc.stderr.strip()}")
    decoder, text, pos, pages = json.JSONDecoder(), proc.stdout, 0, []
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos == len(text):
            return pages
        page, pos = decoder.raw_decode(text, pos)
        pages.append(page)


def gh_items(path: str) -> list[dict]:
    """A paginated REST list, flattened. Search pages wrap their results in `items`."""
    items: list[dict] = []
    for page in gh_pages(path):
        items.extend(page["items"] if isinstance(page, dict) else page)
    return items


def ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def app_of(x: dict) -> str | None:
    return (x.get("performed_via_github_app") or {}).get("slug")


def is_bot(login: str) -> bool:
    return login in BOTS or login.endswith("[bot]")


def load_pr(repo: str, hit: dict) -> dict:
    n = hit["number"]
    pr = gh_pages(f"repos/{repo}/pulls/{n}")[0]
    return {
        "number": n,
        "title": pr["title"],
        "head": pr["head"]["ref"],
        "base": pr["base"]["ref"],
        "state": pr["state"],  # REST "closed" includes merged PRs; `merged_at` tells them apart
        "created_at": pr["created_at"],
        "merged_at": pr["merged_at"],
        "author": pr["user"]["login"],
        "by_routine": app_of(hit) == ROUTINE_APP,  # the search hit carries the app; the pulls object does not
        "commits": [c["commit"]["committer"]["date"] for c in gh_items(f"repos/{repo}/pulls/{n}/commits?per_page=100")],
        "comments": gh_items(f"repos/{repo}/issues/{n}/comments?per_page=100"),
        "reviews": gh_items(f"repos/{repo}/pulls/{n}/reviews?per_page=100"),
    }


def load_prs(repo: str, since: datetime) -> list[dict]:
    hits = gh_items(f"search/issues?q=repo:{repo}+is:pr+created:>={since:%Y-%m-%d}&per_page=100")
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda hit: load_pr(repo, hit), hits))


def matches(pr: dict, rule: dict) -> bool:
    return fnmatch.fnmatch(pr["head"], rule.get("head", "*")) and fnmatch.fnmatch(pr["base"], rule.get("base", "*"))


def redo_requests(pr: dict, approvers: set[str]) -> list[dict]:
    """Comments and reviews by a human approver that carry a `#redo` line."""
    return [
        x
        for x in pr["comments"] + pr["reviews"]
        if app_of(x) is None and x["user"]["login"] in approvers and REDO_LINE.search(x.get("body") or "")
    ]


def redo_replies(pr: dict) -> int:
    """Routine replies that carried out a redo, plus the legacy `done redo` replies."""
    count = 0
    for x in pr["comments"]:
        body = (x.get("body") or "").strip()
        if (app_of(x) == ROUTINE_APP and REDO_DONE.search(body)) or body.lower().startswith("done redo"):
            count += 1
    return count


def pr_facts(pr: dict, approvers: set[str]) -> dict:
    opened = ts(pr["created_at"])
    merged = pr["merged_at"] is not None
    revisions = sum(1 for c in pr["commits"] if ts(c) > opened + REVISION_GRACE)
    asks = len(redo_requests(pr, approvers))
    # A human touch is a post no routine or bot made. On a human-authored PR the author's own posts don't count; on a
    # routine PR the author login is the owner's account, so the owner's posts are the review.
    touch = [
        ts(x.get("submitted_at") or x.get("created_at"))
        for x in pr["comments"] + pr["reviews"]
        if app_of(x) is None
        and not is_bot(x["user"]["login"])
        and (pr["by_routine"] or x["user"]["login"] != pr["author"])
    ]
    first_touch = min((t for t in touch if t), default=None)
    return {
        "merged": merged,
        "closed_unmerged": pr["state"] == "closed" and not merged,
        "open": pr["state"] == "open",
        "revisions": revisions,
        "redo_asks": asks,
        "first_pass": merged and revisions == 0 and asks == 0,
        "review_hours": (first_touch - opened).total_seconds() / 3600 if first_touch else None,
        "merge_hours": (ts(pr["merged_at"]) - opened).total_seconds() / 3600 if merged else None,
    }


def reverted_numbers(repo: str, prs: list[dict]) -> set[int]:
    """PR numbers named by a revert PR: a 'Revert "<title>"' title or a 'Reverts owner/repo#N' body."""
    hits: set[int] = set()
    titles = {p["title"]: p["number"] for p in prs}
    for revert in gh_items(f"search/issues?q=repo:{repo}+is:pr+revert+in:title&per_page=100"):
        hits |= {int(n) for n in re.findall(r"#(\d+)", revert.get("body") or "")}
        inner = revert["title"].removeprefix("Revert ").strip('"')
        if inner in titles:
            hits.add(titles[inner])
    return hits


def median(values: list[float]) -> str:
    return f"{statistics.median(values):.1f}h" if values else "—"


def row(key: str, prs: list[dict], reverted: set[int], approvers: set[str], revisions: bool = True) -> str:
    facts = [pr_facts(p, approvers) for p in prs]
    merged = [f for f in facts if f["merged"]]
    first_pass = sum(f["first_pass"] for f in facts)
    rate = f"{first_pass}/{len(merged)}" if merged and revisions else "—"
    pushes = sum(f["revisions"] for f in facts) if revisions else "n/a"
    return (
        f"| {key} | {len(prs)} | {len(merged)} | {rate} | {sum(f['redo_asks'] > 0 for f in facts)} "
        f"| {pushes} | {sum(f['closed_unmerged'] for f in facts)} | {sum(f['open'] for f in facts)} "
        f"| {sum(1 for p in prs if p['number'] in reverted)} "
        f"| {median([f['review_hours'] for f in facts if f['review_hours'] is not None])} "
        f"| {median([f['merge_hours'] for f in facts if f['merge_hours'] is not None])} |"
    )


def redo_stats(prs: list[dict], approvers: set[str]) -> str:
    asks = sum(len(redo_requests(p, approvers)) for p in prs)
    return f"`#redo` requests: {asks} · done replies: {sum(redo_replies(p) for p in prs)}"


def groom_stats(repo: str, hub: int) -> str:
    comments = gh_items(f"repos/{repo}/issues/{hub}/comments?per_page=100")
    proposed = sum((c.get("body") or "").count("<!-- groom-key:") for c in comments if app_of(c) == ROUTINE_APP)
    issues = gh_items(f"repos/{repo}/issues?labels=groomed&state=all&per_page=100")
    return f"proposals: {proposed} · approved (`groomed` issues): {sum('pull_request' not in i for i in issues)}"


def provenance() -> str:
    core = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD:.claude/routines/core"], capture_output=True, text=True, cwd=CORE
    ).stdout.strip()
    run = os.getenv("CLAUDE_CODE_REMOTE_SESSION_ID") or "local"
    return f"<!-- agent-pipeline core={core or 'uncommitted'} run={run} -->"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=30, help="days of PR history to score")
    ap.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="the repo's pipeline.yml")
    args = ap.parse_args()

    profile = yaml.safe_load(args.profile.read_text())
    repo, hub = profile["project"]["repo"], profile["hub"]["issue"]
    approvers = set(profile.get("approvers") or [])
    now = datetime.now(timezone.utc)
    prs = load_prs(repo, now - timedelta(days=args.window))
    reverted = reverted_numbers(repo, prs)

    lines = [
        f"<!-- ROUTINE-SCORECARD week={now:%G-W%V} -->",
        provenance(),
        AI_HEADER,
        "",
        f"## Routine scorecard — {now:%Y-%m-%d} (ISO week {now:%G-W%V}, last {args.window} days)",
        "",
        "| routine | PRs | merged | first-pass merged | needed #redo | revision pushes | closed unmerged "
        "| open | reverted | median to 1st human review | median to merge |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    claimed: set[int] = set()
    entries = [(r, r["key"]) for r in profile.get("routines") or []]
    entries += [(r, r["key"] if r["key"].endswith("(removed)") else f"{r['key']} (removed)") for r in profile.get("removed") or []]
    for routine, label in entries:
        rules = routine.get("attribution") or []
        if not rules:
            continue
        mine = [p for p in prs if any(matches(p, rule) for rule in rules)]
        claimed |= {p["number"] for p in mine}
        lines.append(row(label, mine, reverted, approvers, routine.get("score_revisions", True)))
    lines.append(row("_unattributed (human)_", [p for p in prs if p["number"] not in claimed], reverted, approvers))
    lines += [
        "",
        f"- redo-executor — {redo_stats(prs, approvers)}",
        f"- backlog-groom — {groom_stats(repo, hub)}",
        "",
        "_Method: PRs attributed by the `attribution` branch patterns in `.claude/routines/pipeline.yml`. "
        "First-pass = merged with no push >10 min after opening and no `#redo`. A human touch is a comment or review "
        "that no routine (`performed_via_github_app`) or bot posted. Revision metrics are n/a where the head branch "
        "moves by design (the release PR). Reverted = named by a later revert PR. Agent confidence is deliberately "
        "not scored._",
        "",
        FOOTER,
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
