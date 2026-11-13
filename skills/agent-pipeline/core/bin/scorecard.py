#!/usr/bin/env python3
"""Weekly outcome scorecard for one repo's agent-pipeline routines.

Reads `.claude/routines/pipeline.yml` and attributes each PR to a routine by its `attribution` branch patterns.
Removed routines are included, so their PRs keep being scored. It adds three things:
- the run ledger: runs per routine, their outcomes, and cron slots with no run;
- the guardrail check: merges, closes, reopens or approval labels made through the Claude app;
- the groom funnel.

It prints the whole hub comment as Markdown. Outcome metrics only, never agent confidence. Read-only and REST only
(`gh api`): `gh pr list` goes through GraphQL, which Claude Code sessions block with a 403.

    python3 .claude/routines/core/bin/scorecard.py [--window 30] [--profile <pipeline.yml>] [--metrics-json <file>]
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # a __pycache__ next to the vendored core would show up as untracked files

import argparse  # noqa: E402
import fnmatch  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402,F401  (tests patch subprocess.run through this module)
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Optional  # noqa: E402

import cronexp  # noqa: E402
import ledger  # noqa: E402
import pcfg  # noqa: E402
from ghrest import ROUTINE_APP, GhError, app_of, gh_items, gh_pages, is_bot, ts  # noqa: E402

# A redo request is a human line starting `#redo`; people often write it below the feedback, not first.
REDO_LINE = re.compile(r"^\s*#redo\b", re.IGNORECASE | re.MULTILINE)
REDO_DONE = re.compile(r"<!-- REDO-DONE\b[^>]*\bstatus=done\b")
# A commit this long after the PR was opened counts as a revision (initial pushes land within minutes).
REVISION_GRACE = timedelta(minutes=10)
# A cron slot counts as run when a ledger record starts within this long after it.
SLOT_TOLERANCE = timedelta(minutes=90)
GUARDED_EVENTS = {"merged", "closed", "reopened"}
APPROVAL_LABEL = "groomed"
AI_HEADER = "> 🤖 **AI-generated** · Claude Code"
FOOTER = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


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
        "by_routine": app_of(hit) == ROUTINE_APP,  # the issue item carries the app; the pulls object does not
        "commits": [c["commit"]["committer"]["date"] for c in gh_items(f"repos/{repo}/pulls/{n}/commits?per_page=100")],
        "comments": gh_items(f"repos/{repo}/issues/{n}/comments?per_page=100"),
        "reviews": gh_items(f"repos/{repo}/pulls/{n}/reviews?per_page=100"),
        "events": gh_items(f"repos/{repo}/issues/{n}/events?per_page=100"),
    }


def pr_items(repo: str, since: Optional[datetime] = None) -> list[dict]:
    """The repo's PRs, as issue items, updated since `since`. Cloud sessions refuse `search/issues` (403: only
    repository-scoped endpoints), so this lists the repo's issues endpoint and keeps the PRs."""
    path = f"repos/{repo}/issues?state=all&per_page=100" + (f"&since={iso(since)}" if since else "")
    return [i for i in gh_items(path) if "pull_request" in i]


def load_prs(repo: str, items: list[dict], since: datetime) -> list[dict]:
    hits = [i for i in items if ts(i["created_at"]) >= since]
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


def reverted_numbers(items: list[dict], prs: list[dict]) -> set[int]:
    """PR numbers named by a revert PR: a 'Revert "<title>"' title or a 'Reverts owner/repo#N' body."""
    hits: set[int] = set()
    titles = {p["title"]: p["number"] for p in prs}
    for revert in (i for i in items if "revert" in i["title"].lower()):
        hits |= {int(n) for n in re.findall(r"#(\d+)", revert.get("body") or "")}
        inner = revert["title"].removeprefix("Revert ").strip('"')
        if inner in titles:
            hits.add(titles[inner])
    return hits


def median(values: list[float]) -> Optional[float]:
    return round(statistics.median(values), 1) if values else None


def stats(prs: list[dict], reverted: set[int], approvers: set[str], revisions: bool = True) -> dict:
    facts = [pr_facts(p, approvers) for p in prs]
    merged = [f for f in facts if f["merged"]]
    return {
        "prs": len(prs),
        "merged": len(merged),
        "first_pass": sum(f["first_pass"] for f in facts) if merged and revisions else None,
        "needed_redo": sum(f["redo_asks"] > 0 for f in facts),
        "revision_pushes": sum(f["revisions"] for f in facts) if revisions else None,
        "closed_unmerged": sum(f["closed_unmerged"] for f in facts),
        "open": sum(f["open"] for f in facts),
        "reverted": sum(1 for p in prs if p["number"] in reverted),
        "median_review_hours": median([f["review_hours"] for f in facts if f["review_hours"] is not None]),
        "median_merge_hours": median([f["merge_hours"] for f in facts if f["merge_hours"] is not None]),
    }


def hours(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f}h"


def row(key: str, s: dict) -> str:
    rate = f"{s['first_pass']}/{s['merged']}" if s["first_pass"] is not None else "—"
    pushes = "n/a" if s["revision_pushes"] is None else s["revision_pushes"]
    return (
        f"| {key} | {s['prs']} | {s['merged']} | {rate} | {s['needed_redo']} | {pushes} | {s['closed_unmerged']} "
        f"| {s['open']} | {s['reverted']} | {hours(s['median_review_hours'])} | {hours(s['median_merge_hours'])} |"
    )


def redo_stats(prs: list[dict], approvers: set[str]) -> str:
    asks = sum(len(redo_requests(p, approvers)) for p in prs)
    return f"`#redo` requests: {asks} · done replies: {sum(redo_replies(p) for p in prs)}"


def groom_stats(repo: str, hub: int, since: datetime) -> tuple[str, list[str]]:
    """The groom funnel in the window, and any approval label added through the Claude app (a guardrail breach)."""
    comments = gh_items(f"repos/{repo}/issues/{hub}/comments?per_page=100&since={iso(since)}")
    proposed = sum(
        (c.get("body") or "").count("<!-- groom-key:")
        for c in comments
        if app_of(c) == ROUTINE_APP and ts(c["created_at"]) >= since
    )
    labelled = gh_items(f"repos/{repo}/issues?labels={APPROVAL_LABEL}&state=all&per_page=100&since={iso(since)}")
    issues = [i for i in labelled if "pull_request" not in i]
    breaches = []
    for issue in issues:
        for event in gh_items(f"repos/{repo}/issues/{issue['number']}/events?per_page=100"):
            label = (event.get("label") or {}).get("name")
            if event.get("event") == "labeled" and label == APPROVAL_LABEL and app_of(event) == ROUTINE_APP:
                breaches.append(f"#{issue['number']} labelled `{APPROVAL_LABEL}`")
    approved = sum(1 for i in issues if ts(i["created_at"]) >= since)
    return f"proposals: {proposed} · approved (`{APPROVAL_LABEL}` issues): {approved}", breaches


def pr_breaches(prs: list[dict]) -> list[str]:
    """Merges, closes and reopens made through the Claude app: a routine broke a hard rule."""
    return [
        f"#{p['number']} {e['event']}"
        for p in prs
        for e in p.get("events") or []
        if e.get("event") in GUARDED_EVENTS and app_of(e) == ROUTINE_APP
    ]


def missed_slots(cron: Optional[str], starts: list[datetime], start: datetime, now: datetime) -> Optional[int]:
    """Cron slots in [start, now − tolerance) with no run record starting within the tolerance after them."""
    if not cron:
        return None
    try:
        expected = cronexp.slots(cron, start, now - SLOT_TOLERANCE)
    except ValueError:
        return None
    return sum(1 for slot in expected if not any(slot <= t < slot + SLOT_TOLERANCE for t in starts))


def ledger_section(profile: dict, records: list[dict], since: datetime, now: datetime) -> tuple[list[str], dict]:
    """Runs per active routine from the ledger. Slots before the first record are not counted as missed."""
    real = [r for r in records if not r.get("dry_run") and r.get("started_at")]
    if not real:
        return ["_No run records yet: the run ledger starts with core 2.0._"], {}
    first = min(ts(r["started_at"]) for r in real)
    lines = [
        "| routine | runs | wrote | noop | gated | failed | missed slots | median minutes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    data = {}
    for routine in profile.get("routines") or []:
        if routine.get("status", "active") != "active":
            continue
        mine = [r for r in real if r.get("routine") == routine["key"]]
        counts = {outcome: sum(1 for r in mine if r.get("outcome") == outcome) for outcome in ledger.OUTCOMES}
        minutes = [(ts(r["ended_at"]) - ts(r["started_at"])).total_seconds() / 60 for r in mine if r.get("ended_at")]
        missed = missed_slots(routine.get("cron"), [ts(r["started_at"]) for r in mine], max(since, first), now)
        data[routine["key"]] = {"runs": len(mine), **counts, "missed_slots": missed, "median_minutes": median(minutes)}
        lines.append(
            f"| {routine['key']} | {len(mine)} | {counts['wrote']} | {counts['noop']} | {counts['gated']} "
            f"| {counts['failed']} | {'—' if missed is None else missed} "
            f"| {'—' if median(minutes) is None else median(minutes)} |"
        )
    return lines, data


def provenance() -> str:
    run = os.getenv("CLAUDE_CODE_REMOTE_SESSION_ID") or "local"
    return f"<!-- agent-pipeline core={pcfg.core_version()} run={run} -->"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=30, help="days of PR and run history to score")
    ap.add_argument("--profile", help="the repo's pipeline.yml")
    ap.add_argument("--metrics-json", help="also write the numbers as JSON to this file, for the ledger")
    args = ap.parse_args()

    profile = pcfg.load(args.profile)
    repo, hub = profile["project"]["repo"], profile["hub"]["issue"]
    approvers = set(profile.get("approvers") or [])
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.window)
    try:
        items = pr_items(repo, since)
        prs = load_prs(repo, items, since)
        groom_line, label_breaches = groom_stats(repo, hub, since)
    except GhError as err:
        sys.exit(str(err))
    reverted = reverted_numbers(items, prs)
    records = ledger.read_records(profile, since)
    week = f"{now:%G-W%V}"

    lines = [
        f"<!-- ROUTINE-SCORECARD week={week} -->",
        provenance(),
        AI_HEADER,
        "",
        f"## Routine scorecard — {now:%Y-%m-%d} (ISO week {week}, last {args.window} days)",
        "",
        "| routine | PRs | merged | first-pass merged | needed #redo | revision pushes | closed unmerged "
        "| open | reverted | median to 1st human review | median to merge |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    metrics: dict = {"week": week, "generated_at": iso(now), "window_days": args.window, "routines": {}}
    claimed: set[int] = set()
    entries = [(r, r["key"]) for r in profile.get("routines") or []]
    entries += [
        (r, r["key"] if r["key"].endswith("(removed)") else f"{r['key']} (removed)")
        for r in profile.get("removed") or []
    ]
    for routine, label in entries:
        rules = routine.get("attribution") or []
        if not rules:
            continue
        mine = [p for p in prs if any(matches(p, rule) for rule in rules)]
        claimed |= {p["number"] for p in mine}
        metrics["routines"][label] = stats(mine, reverted, approvers, routine.get("score_revisions", True))
        lines.append(row(label, metrics["routines"][label]))
    human = stats([p for p in prs if p["number"] not in claimed], reverted, approvers)
    metrics["routines"]["_unattributed (human)_"] = human
    lines.append(row("_unattributed (human)_", human))

    run_lines, metrics["ledger"] = ledger_section(profile, records, since, now)
    breaches = pr_breaches(prs) + label_breaches
    metrics["guardrail_breaches"] = breaches
    lines += [
        "",
        f"- redo-executor — {redo_stats(prs, approvers)}",
        f"- backlog-groom — {groom_line}",
        f"- guardrails — {len(breaches)} breach(es)" + (f": {', '.join(breaches)}" if breaches else ""),
        "",
        f"### Runs (ledger, last {args.window} days)",
        "",
        *run_lines,
        "",
        "_Method: PRs attributed by the `attribution` branch patterns in `.claude/routines/pipeline.yml`. "
        "First-pass = merged with no push >10 min after opening and no `#redo`. A human touch is a comment or review "
        "that no routine (`performed_via_github_app`) or bot posted. Revision metrics are n/a where the head branch "
        "moves by design (the release PR). Reverted = named by a later revert PR. A guardrail breach is a merge, "
        "close, reopen or approval label made through the Claude app. A missed slot is a cron time of an active "
        "routine with no run record within 90 minutes after it. Agent confidence is deliberately not scored._",
        "",
        FOOTER,
    ]
    print("\n".join(lines))
    if args.metrics_json:
        with open(args.metrics_json, "w") as out:
            json.dump(metrics, out, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
