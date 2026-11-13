"""Deterministic selection for each role: which items are eligible, which gates they passed, and their requirement.

`pipeline.py select <role>` prints these as JSON. The role prompts used to state these rules in prose for the model to
carry out; now this module selects and the model only judges. Every function takes `gh` (ghrest.GitHub, or a test
fake with the same methods) and the profile.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, Optional

from ghrest import app_of, by_routine, is_human, login, ts, when
from pcfg import lookup

APPROVAL_LABEL = "groomed"
PROPOSAL_LABEL = "groom-proposed"
BUILD_PREFIX = "groomed/"
GROOM_MARKER = "<!-- BACKLOG-GROOM -->"
MAX_EVALUATIONS = 3
MAX_BUILDS = 2
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# GitHub's closing keywords, any case, an optional colon, then the issue reference
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+#(\d+)\b", re.I)
TASK_LINE = re.compile(r"^\s*- \[[ xX]\] (.*\S)\s*$")
GROOM_KEY = re.compile(r"<!-- groom-key: (.+?) -->")
GATE = re.compile(r"<!-- GATE issue=(\d+) gate=(\S+) base=(\S+) -->")
# people write `#redo` below their feedback, not first
REDO_LINE = re.compile(r"^\s*#redo\b", re.I | re.M)
APPLY_FINDINGS = re.compile(r"^\s*#redo\s+apply the evaluation findings\b", re.I | re.M)
EPOCH = datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- shared helpers


def first_line(body: Optional[str]) -> str:
    return (body or "").lstrip().split("\n", 1)[0].strip()


def marked(item: dict, prefix: str) -> bool:
    """A marker counts only on a routine's own post, so typing one by hand never suppresses work."""
    return by_routine(item) and first_line(item.get("body")).startswith(prefix)


def at(item: dict) -> datetime:
    """`when`, with a floor, so it always sorts."""
    return when(item) or EPOCH


def newest(items: list[dict]) -> Optional[dict]:
    return max(items, key=at, default=None)


def sanitize(text: Optional[str]) -> tuple[str, bool]:
    """Text with its HTML comments removed. Hidden text is a prompt-injection channel, never a requirement."""
    text = text or ""
    return HTML_COMMENT.sub("", text).strip(), bool(HTML_COMMENT.search(text))


def wip(profile: dict, open_prs: list[dict]) -> dict:
    """Open PRs into integration (or into a `wip.prefixes` branch). The integration → production sync PR is free."""
    integration, production = lookup(profile, "branches.integration"), lookup(profile, "branches.production")
    prefixes = lookup(profile, "wip.prefixes") or []
    counted = [
        p["number"]
        for p in open_prs
        if (p["base"]["ref"] == integration or any(p["base"]["ref"].startswith(x) for x in prefixes))
        and not (p["head"]["ref"] == integration and p["base"]["ref"] == production)
    ]
    return {"open": len(counted), "limit": lookup(profile, "wip.limit") or 0, "prs": counted}


def approval(timeline: list[dict], approvers: set, label: str = APPROVAL_LABEL) -> dict:
    """G1: the label's latest `labeled` event was made by a human approver, not through an app."""
    events = [e for e in timeline if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == label]
    last = newest(events)
    if last is None:
        return {"pass": False, "reason": f"no `{label}` label event in the timeline"}
    actor = login(last)
    if app_of(last) is not None:
        return {"pass": False, "actor": actor, "reason": f"`{label}` was added through the app `{app_of(last)}`"}
    if actor not in approvers:
        return {"pass": False, "actor": actor, "reason": f"`{label}` was added by {actor}, who is not an approver"}
    return {"pass": True, "actor": actor, "at": last.get("created_at")}


def normalise_title(text: str) -> str:
    """A groom task line or issue title, compared as `core/hub-contract.md` (Groom items) says."""
    text = (text or "").replace("**", "")
    cut = text.find(" — score")
    return (text[:cut] if cut >= 0 else text).strip()


def groom_item(hub_comments: list[dict], number: int, title: str) -> Optional[dict]:
    """The groom item an issue was converted from: newest groom comment first, matched by title or by `#<N>`."""
    target = normalise_title(title)
    grooms = sorted((c for c in hub_comments if marked(c, GROOM_MARKER)), key=at, reverse=True)
    for comment in grooms:
        lines = (comment.get("body") or "").splitlines()
        for i, line in enumerate(lines):
            task = TASK_LINE.match(line)
            if not task:
                continue
            text = task.group(1).strip()
            if normalise_title(text) != target and text != f"#{number}":
                continue
            end = i + 1
            while end < len(lines) and not TASK_LINE.match(lines[end]) and not lines[end].startswith("**"):
                end += 1
            item = "\n".join(lines[i:end]).rstrip()
            key = GROOM_KEY.search(item)
            criteria = re.search(r"\*\*Acceptance criteria:\*\*\s*(.+)", item)
            return {
                "source": "groom-item",
                "url": comment.get("html_url"),
                "text": item,
                "acceptance_criteria": criteria.group(1).strip() if criteria else None,
                "groom_key": key.group(1) if key else None,
            }
    return None


NO_REQUIREMENT = (
    "This issue has no requirement: its body is empty and no groom item on the hub matches its title. "
    "Please paste the acceptance criteria into the issue body."
)


def requirement(gh, profile: dict, issue: dict, hub_comments: Optional[list] = None) -> dict:
    """The issue body when it has text; otherwise the groom item it came from; otherwise none, with the question."""
    text, hidden = sanitize(issue.get("body"))
    if text:
        return {
            "source": "issue-body",
            "url": issue.get("html_url"),
            "author": "routine" if by_routine(issue) else "human",
            "text": text,
            "had_hidden_text": hidden,
        }
    hub = lookup(profile, "hub.issue")
    if hub:
        comments = hub_comments if hub_comments is not None else gh.list(f"issues/{hub}/comments?per_page=100")
        item = groom_item(comments, issue["number"], issue.get("title") or "")
        if item:
            return item
    return {"source": "none", "question": NO_REQUIREMENT}


def closing_issue(body: Optional[str]) -> Optional[int]:
    found = CLOSING.search(body or "")
    return int(found.group(1)) if found else None


def in_flight(number: int, open_prs: list[dict], branches: list[str]) -> list[str]:
    """G2: an open PR body names `#<N>` as a whole number, or a `groomed/<N>` branch exists (old names had a slug)."""
    ref = re.compile(rf"#{number}\b")
    hits = [f"PR #{p['number']}" for p in open_prs if ref.search(p.get("body") or "")]
    hits += [
        f"branch {b}" for b in branches if b == f"{BUILD_PREFIX}{number}" or b.startswith(f"{BUILD_PREFIX}{number}-")
    ]
    return hits


def last_gate(comments: list[dict]) -> Optional[dict]:
    """The newest routine GATE comment on an issue, and whether a human commented after it."""
    gates = [c for c in comments if marked(c, "<!-- GATE ")]
    latest = newest(gates)
    if latest is None:
        return None
    found = GATE.match(first_line(latest.get("body")))
    return {
        "gate": found.group(2) if found else None,
        "base": found.group(3) if found else None,
        "url": latest.get("html_url"),
        "human_after": any(is_human(c) and at(c) > at(latest) for c in comments),
    }


def check_state(runs: list[dict], name: str, pushed: Optional[datetime], now: datetime, missing_after: float) -> dict:
    """One required check on a commit: green, failed, pending, or missing once `missing_after` hours have passed."""
    mine = [r for r in runs if r.get("name") == name and (r.get("app") or {}).get("slug") == "github-actions"]
    if not mine:
        hours = (now - pushed).total_seconds() / 3600 if pushed else None
        state = "missing" if hours is not None and hours > missing_after else "pending"
        return {"name": name, "state": state, "hours_since_push": round(hours, 1) if hours is not None else None}
    run = max(mine, key=lambda r: (r.get("started_at") or "", r.get("id") or 0))
    out = {"name": name, "url": run.get("html_url")}
    if run.get("status") != "completed":
        return {**out, "state": "pending"}
    if run.get("conclusion") == "success":
        return {**out, "state": "green"}
    return {
        **out,
        "state": "failed",
        "conclusion": run.get("conclusion"),
        "title": (run.get("output") or {}).get("title"),
    }


def overall(states: list[dict]) -> str:
    for state in ("failed", "missing", "pending"):
        if any(s["state"] == state for s in states):
            return state
    return "green"


def commit_time(gh, sha: str) -> Optional[datetime]:
    commit = gh.get(f"commits/{sha}") or {}
    return ts(((commit.get("commit") or {}).get("committer") or {}).get("date"))


def ci_states(gh, profile: dict, sha: str, now: datetime) -> tuple[list[dict], Optional[dict]]:
    """E1 and E4: every `ci.required` check, and the `ci.proof` check, on one commit."""
    runs = gh.list(f"commits/{sha}/check-runs?per_page=100", key="check_runs")
    pushed = commit_time(gh, sha)
    hours = lookup(profile, "ci.missing_after_hours") or 6
    required = [check_state(runs, name, pushed, now, hours) for name in lookup(profile, "ci.required") or []]
    proof = lookup(profile, "ci.proof")
    return required, (check_state(runs, proof, pushed, now, hours) if proof else None)


# ---------------------------------------------------------------- roles


def select_implementer(gh, profile: dict, now: Optional[datetime] = None) -> dict:
    """gated-implementer: the WIP budget (G3), then each `groomed` issue through G1 and G2, with its requirement."""
    approvers = set(lookup(profile, "approvers") or [])
    open_prs = gh.list("pulls?state=open&per_page=100")
    gate = wip(profile, open_prs)
    out: dict = {"role": "gated-implementer", "wip": gate, "budget": 0, "candidates": []}
    if gate["open"] >= gate["limit"]:
        out["stop"] = f"Skipped: {gate['open']} open PRs"
        return out
    out["budget"] = min(MAX_BUILDS, gate["limit"] - gate["open"])
    label_path = f"issues?labels={APPROVAL_LABEL}&state=open&sort=created&direction=asc&per_page=100"
    issues = [i for i in gh.list(label_path) if "pull_request" not in i]
    branches = [r["ref"][len("refs/heads/") :] for r in gh.list(f"git/matching-refs/heads/{BUILD_PREFIX}")]
    hub = lookup(profile, "hub.issue")
    hub_comments = gh.list(f"issues/{hub}/comments?per_page=100") if hub and issues else []
    for issue in issues:
        n = issue["number"]
        entry = {"issue": n, "title": issue.get("title"), "url": issue.get("html_url"), "branch": f"{BUILD_PREFIX}{n}"}
        g1 = approval(gh.list(f"issues/{n}/timeline?per_page=100"), approvers)
        if not g1["pass"]:
            out["candidates"].append({**entry, "eligible": False, "failed": "G1", "reason": g1["reason"]})
            continue
        flight = in_flight(n, open_prs, branches)
        if flight:
            out["candidates"].append(
                {**entry, "eligible": False, "failed": "G2", "reason": "in flight: " + ", ".join(flight)}
            )
            continue
        out["candidates"].append(
            {
                **entry,
                "eligible": True,
                "approved_by": g1["actor"],
                "requirement": requirement(gh, profile, issue, hub_comments),
                "last_gate": last_gate(gh.list(f"issues/{n}/comments?per_page=100")),
            }
        )
    if not any(c["eligible"] for c in out["candidates"]):
        out["stop"] = "no groomed issues ready"
    return out


def in_scope(gh, profile: dict, pr: dict, approvers: set) -> Optional[str]:
    """Why pr-evaluator may judge this PR: its head starts with one of `evaluate.heads`, or an approver added the
    `evaluate.opt_in_label` by hand. None when neither holds."""
    heads = lookup(profile, "evaluate.heads") or [BUILD_PREFIX]
    if any(pr["head"]["ref"].startswith(h) for h in heads):
        return "head"
    label = lookup(profile, "evaluate.opt_in_label")
    if label and label in {x.get("name") for x in pr.get("labels") or []}:
        if approval(gh.list(f"issues/{pr['number']}/timeline?per_page=100"), approvers, label)["pass"]:
            return "opt-in"
    return None


def select_evaluator(gh, profile: dict, now: Optional[datetime] = None) -> dict:
    """pr-evaluator: in-scope PRs into integration not yet evaluated at their head SHA, at most 3, lowest first.

    A PR whose checks are still running waits for the next run and does not use up one of the 3 slots. A ci-doctor
    fix PR (`ci.autofix.prefix`) has no proof job: its proof is its issue's CI-DOCTOR evidence, which the model reads.
    """
    now = now or datetime.now(timezone.utc)
    integration = lookup(profile, "branches.integration")
    approvers = set(lookup(profile, "approvers") or [])
    autofix = lookup(profile, "ci.autofix.prefix")
    hub = lookup(profile, "hub.issue")
    hub_comments: Optional[list] = None
    out: dict = {"role": "pr-evaluator", "evaluate": [], "waiting": [], "deferred": []}
    for pr in sorted(gh.list("pulls?state=open&per_page=100"), key=lambda p: p["number"]):
        n, sha = pr["number"], pr["head"]["sha"]
        if pr["base"]["ref"] != integration or pr.get("draft"):
            continue
        scope = in_scope(gh, profile, pr, approvers)
        if scope is None:
            continue
        done = [c for c in gh.list(f"issues/{n}/comments?per_page=100") if marked(c, f"<!-- PR-EVALUATION sha={sha}")]
        if done and "verdict=CI-MISSING" not in first_line(newest(done).get("body")):
            continue  # evaluated at this head SHA; a new push makes it eligible again
        required, proof = ci_states(gh, profile, sha, now)
        ci_fix = bool(autofix) and pr["head"]["ref"].startswith(autofix)
        if ci_fix:
            proof = {
                "name": lookup(profile, "ci.proof"),
                "state": "n/a",
                "why": "a ci-fix PR: its proof is the CI-DOCTOR evidence on its issue",
            }
        states = required + ([proof] if proof and proof["state"] != "n/a" else [])
        if done and any(s["state"] == "missing" for s in states):
            continue  # CI-MISSING already said at this SHA, and the checks still do not exist
        reentry = bool(done)
        state = overall(states)
        if state == "pending":
            out["waiting"].append({"pr": n, "pending": [s["name"] for s in states if s["state"] == "pending"]})
            continue
        if len(out["evaluate"]) >= MAX_EVALUATIONS:
            out["deferred"].append(n)
            continue
        number = closing_issue(pr.get("body"))
        issue = gh.get(f"issues/{number}") if number else None
        if issue:
            # the hub is read only for an empty-bodied issue, and then once per run
            if hub_comments is None and hub and not sanitize(issue.get("body"))[0]:
                hub_comments = gh.list(f"issues/{hub}/comments?per_page=100")
            req = requirement(gh, profile, issue, hub_comments or [])
        elif scope == "opt-in" and app_of(gh.get(f"issues/{n}") or {}) is None:
            # an opted-in PR a human wrote, with no issue: its own body is the requirement
            text, hidden = sanitize(pr.get("body"))
            req = {"source": "pr-body", "url": pr.get("html_url"), "text": text, "had_hidden_text": hidden}
            if not text:
                req = {"source": "none", "question": "This opted-in PR names no issue and its body is empty."}
        else:
            req = {
                "source": "none",
                "question": "The PR body names no issue with `Closes #<N>`, so it has no requirement.",
            }
        verdict = {"failed": "REWORK", "missing": "CI-MISSING"}.get(state)
        out["evaluate"].append(
            {
                "pr": n,
                "title": pr.get("title"),
                "url": pr.get("html_url"),
                "head_ref": pr["head"]["ref"],
                "head_sha": sha,
                "scope": scope,
                "ci_fix": ci_fix,
                "issue": number,
                "requirement": req,
                "ci": required,
                "proof": proof,
                "objective_verdict": verdict,
                "reentry_after_ci_missing": reentry,
                "worktree": f"git fetch origin pull/{n}/head && git worktree add --detach /tmp/wt/pr-{n} FETCH_HEAD",
            }
        )
    if not out["evaluate"]:
        out["stop"] = "no PRs to evaluate"
    return out


def findings_of(evaluation: Optional[dict]) -> Optional[str]:
    """The "Findings to fix" list of an evaluation comment, up to its closing `#redo` hint."""
    if not evaluation:
        return None
    lines = (evaluation.get("body") or "").splitlines()
    start = next((i for i, line in enumerate(lines) if "Findings to fix" in line), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("Reply `#redo")), len(lines))
    return "\n".join(lines[start:end]).strip()


def redo_brief(gh, profile, pr: dict, request: dict, comments, review_comments, reviews, now) -> dict:
    """What a `#redo` asks for: its own words, the current evaluation's findings, or all open feedback."""
    sha = pr["head"]["sha"]
    evaluation = newest([c for c in comments if marked(c, f"<!-- PR-EVALUATION sha={sha}")])
    body = request.get("body") or ""
    if APPLY_FINDINGS.search(body):
        findings = findings_of(evaluation)
        if not findings:
            return {
                "kind": "ask",
                "question": "There is no evaluation of the current head commit to apply. What needs redoing?",
            }
        return {"kind": "evaluation-findings", "findings": findings, "evaluation_url": evaluation.get("html_url")}
    text, hidden = sanitize(body)
    if REDO_LINE.sub("", text).strip():
        return {"kind": "explicit", "brief": text, "had_hidden_text": hidden}
    done = [c for c in comments if marked(c, "<!-- REDO-DONE ")]
    since = at(newest(done)) if done else None
    feedback = []
    for c in review_comments:
        if is_human(c) and (since is None or at(c) > since):
            feedback.append(
                {
                    "type": "review comment",
                    "path": c.get("path"),
                    "line": c.get("line"),
                    "url": c.get("html_url"),
                    "body": sanitize(c.get("body"))[0],
                }
            )
    for r in reviews:
        if r.get("state") == "CHANGES_REQUESTED" and (since is None or at(r) > since):
            feedback.append({"type": "changes requested", "url": r.get("html_url"), "body": sanitize(r.get("body"))[0]})
    if findings_of(evaluation):
        feedback.append(
            {"type": "evaluation findings", "url": evaluation.get("html_url"), "body": findings_of(evaluation)}
        )
    required, _ = ci_states(gh, profile, sha, now)
    feedback += [{"type": "failing check", **s} for s in required if s["state"] == "failed"]
    if not feedback:
        return {"kind": "ask", "question": "What needs redoing? This PR has no open feedback."}
    return {
        "kind": "open-feedback",
        "feedback": feedback,
        "note": "REST does not say whether a review thread is resolved: skip a thread a later commit already addressed.",
    }


def select_redo(gh, profile: dict, now: Optional[datetime] = None) -> dict:
    """redo-executor: open PRs whose newest `#redo` request from an approver has no answer yet."""
    now = now or datetime.now(timezone.utc)
    approvers = set(lookup(profile, "approvers") or [])
    out: dict = {"role": "redo-executor", "redo": [], "skipped": []}
    for pr in sorted(gh.list("pulls?state=open&per_page=100"), key=lambda p: p["number"]):
        n = pr["number"]
        comments = gh.list(f"issues/{n}/comments?per_page=100")
        review_comments = gh.list(f"pulls/{n}/comments?per_page=100")
        reviews = gh.list(f"pulls/{n}/reviews?per_page=100")
        requests = [
            x
            for x in comments + review_comments + reviews
            if app_of(x) is None and login(x) in approvers and REDO_LINE.search(x.get("body") or "")
        ]
        request = newest(requests)
        if request is None:
            continue
        answered = any(marked(c, f"<!-- REDO-DONE for={request['id']} ") for c in comments) or any(
            (c.get("body") or "").strip().lower().startswith("done redo") and at(c) > at(request) for c in comments
        )
        if answered:
            continue
        head_repo = ((pr["head"].get("repo") or {}).get("full_name")) or ""
        base_repo = ((pr["base"].get("repo") or {}).get("full_name")) or ""
        if head_repo != base_repo:
            out["skipped"].append({"pr": n, "reason": "the head branch is on a fork, which a routine cannot push to"})
            continue
        head = pr["head"]["ref"]
        out["redo"].append(
            {
                "pr": n,
                "url": pr.get("html_url"),
                "head_ref": head,
                "head_sha": pr["head"]["sha"],
                "request": {"id": request["id"], "url": request.get("html_url"), "author": login(request)},
                "brief": redo_brief(gh, profile, pr, request, comments, review_comments, reviews, now),
                # an explicit refspec, so origin/<head> exists even in a single-branch clone
                "worktree": f"git fetch origin +refs/heads/{head}:refs/remotes/origin/{head}"
                f" && git worktree add -B {head} /tmp/wt/pr-{n} origin/{head}",
            }
        )
    if not out["redo"]:
        out["stop"] = "no #redo requests found"
    return out


def section(markdown: str, prefix: str) -> Optional[str]:
    """The section whose heading text starts with `prefix`, up to the next heading of the same or a higher level."""
    lines = (markdown or "").splitlines()
    for i, line in enumerate(lines):
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading and heading.group(2).strip().startswith(prefix):
            level, end = len(heading.group(1)), i + 1
            while end < len(lines):
                nxt = re.match(r"^(#{1,6})\s", lines[end])
                if nxt and len(nxt.group(1)) <= level:
                    break
                end += 1
            return "\n".join(lines[i:end]).strip()
    return None


def select_groom(gh, profile: dict, now: Optional[datetime] = None) -> dict:
    """backlog-groom: the WIP gate, then everything the groomer screens candidates against."""
    open_prs = gh.list("pulls?state=open&per_page=100")
    gate = wip(profile, open_prs)
    out: dict = {"role": "backlog-groom", "wip": gate}
    if gate["open"] > gate["limit"]:
        out["stop"] = f"Skipped: {gate['open']} open PRs (> {gate['limit']})"
        return out
    hub = lookup(profile, "hub.issue")
    issue = gh.get(f"issues/{hub}") if hub else None
    if not issue or issue.get("state") != "open":
        out["stop"] = f"the hub issue #{hub} is closed or missing"
        return out
    comments = gh.list(f"issues/{hub}/comments?per_page=100")
    grooms = [c for c in comments if marked(c, GROOM_MARKER)]
    runs = [
        c
        for c in comments
        if by_routine(c) and first_line(c.get("body")).startswith(("<!-- IMPLEMENTATION-RUN", "**Implementation run"))
    ]
    prs = gh.page("pulls?state=all&sort=created&direction=desc&per_page=60")
    issues = [i for i in gh.page("issues?state=all&sort=created&direction=desc&per_page=60") if "pull_request" not in i]
    # its own open proposals are issues too: a pick still sitting in one is never proposed again
    proposals = [
        i
        for i in gh.list(f"issues?labels={PROPOSAL_LABEL}&state=open&per_page=100")
        if "pull_request" not in i and by_routine(i)
    ]
    keys = {k for c in grooms for k in GROOM_KEY.findall(c.get("body") or "")}
    keys |= {k for i in proposals for k in GROOM_KEY.findall(i.get("body") or "")}
    out.update(
        {
            "hub": {"issue": hub, "url": issue.get("html_url"), "updated_at": issue.get("updated_at")},
            "proposal_label": {"name": PROPOSAL_LABEL, "exists": gh.get(f"labels/{PROPOSAL_LABEL}") is not None},
            "open_proposals": [
                {
                    "number": i["number"],
                    "title": i.get("title"),
                    "groom_key": (GROOM_KEY.findall(i.get("body") or "") or [None])[0],
                }
                for i in proposals
            ],
            "enhancements": section(issue.get("body") or "", "Enhancement suggestions"),
            "hub_body": issue.get("body") or "",
            "prior_groom_keys": sorted(keys),
            "implementation_runs": [
                {"url": c.get("html_url"), "body": c.get("body")} for c in sorted(runs, key=at)[-5:]
            ],
            "recent_prs": [
                {
                    "number": p["number"],
                    "title": p.get("title"),
                    "state": p.get("state"),
                    "head": p["head"]["ref"],
                    "merged": bool(p.get("merged_at")),
                }
                for p in prs
            ],
            "recent_issues": [
                {
                    "number": i["number"],
                    "title": i.get("title"),
                    "state": i.get("state"),
                    "labels": [x.get("name") for x in i.get("labels") or []],
                }
                for i in issues
            ],
        }
    )
    return out


def select_release(gh, profile: dict, git: Callable[..., str], today: str) -> dict:
    """release-manager: everything the one integration → production PR needs, computed; the model adds only themes."""
    integration, production = lookup(profile, "branches.integration"), lookup(profile, "branches.production")
    out: dict = {"role": "release-manager"}
    if integration == production:
        out["stop"] = "Trunk-based: nothing to ship."
        return out
    git("fetch", "origin", production, integration, "--prune")
    span = f"origin/{production}..origin/{integration}"
    shas = set(git("rev-list", span).split())
    if not shas:
        out["stop"] = "No commits ahead — nothing to do."
        return out
    open_release = [
        p for p in gh.list(f"pulls?state=open&base={production}&per_page=100") if p["head"]["ref"] == integration
    ]
    merged = [
        p
        for p in gh.page(f"pulls?state=closed&base={integration}&sort=updated&direction=desc&per_page=100")
        if p.get("merged_at") and p.get("merge_commit_sha") in shas
    ]
    closes = []
    for n in sorted({int(x) for p in merged for x in CLOSING.findall(p.get("body") or "")}):
        issue = gh.get(f"issues/{n}") or {}
        if issue.get("state") == "open" and "pull_request" not in issue:
            closes.append(n)
    log = [line for line in git("log", "--oneline", "--no-merges", span).splitlines() if line.strip()]
    stat = [
        line
        for line in git("diff", "--stat", f"origin/{production}...origin/{integration}").splitlines()
        if line.strip()
    ]
    entries = sorted(stat[:-1], key=lambda line: -int((re.search(r"\|\s*(\d+)", line) or [0, 0])[1]))
    out.update(
        {
            "integration": integration,
            "production": production,
            "ahead": len(shas),
            "release_pr": open_release[0]["number"] if open_release else None,
            "title": f"Release: merge {integration} into {production} ({today})",
            "closes": closes,
            "commits": log[:40],
            "omitted": max(0, len(log) - 40),
            "files_changed": stat[-1].strip() if stat else "",
            "largest": [line.strip() for line in entries[:10]],
        }
    )
    return out


def overlap(gh, files: list[str]) -> list[dict]:
    """G4: the open PRs that touch any of these files."""
    wanted, hits = set(files), []
    for pr in gh.list("pulls?state=open&per_page=100"):
        touched = {f.get("filename") for f in gh.list(f"pulls/{pr['number']}/files?per_page=100")}
        common = sorted(wanted & touched)
        if common:
            hits.append({"pr": pr["number"], "url": pr.get("html_url"), "files": common})
    return hits


SELECTORS = {
    "gated-implementer": select_implementer,
    "pr-evaluator": select_evaluator,
    "redo-executor": select_redo,
    "backlog-groom": select_groom,
}
