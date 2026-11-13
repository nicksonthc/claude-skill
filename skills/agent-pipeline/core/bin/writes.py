"""`pipeline.py post`: the one way a role writes posts to GitHub (the "safe outputs" pattern).

The gateway builds every post the same way: marker line 1, provenance, AI header, body, footer. It keeps each role to
the writes its prompt's front matter declares (`writes:`), skips a post that would repeat one, records every write in
the run ledger, and prints instead of posting in a DRY RUN.

Kinds: comment, issue, pr, pr-body, hub-body, release-pr. A role's other declared writes (`push`, `label`,
`dispatch`, `rerun`) are plain git or `gh api` calls; `push-guard.py` and `write-guard.py` cover those.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import gates
from ghrest import by_routine
from ledger import load_state, now_iso, save_state
from pcfg import front_matter, git, lookup, prompt_file, routine

AI_HEADER = "> 🤖 **AI-generated** · Claude Code"
FOOTER = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
KINDS = ("comment", "issue", "pr", "pr-body", "hub-body", "release-pr")
TARGETS = ("hub", "issue", "pr")
APPROVAL_LABELS = {gates.APPROVAL_LABEL}
# GitHub refuses an issue body over 65,536 codepoints; core/hub-contract.md (Size) budgets the hub at 60,000.
HUB_BUDGET = 60000
# A local routine without a `writes:` front matter is an audit: it owns the hub body and its change-log comment.
LOCAL_DEFAULT = [
    {"kind": "hub-body", "max": 1},
    {"kind": "comment", "to": "hub", "marker": "AUDIT-CHANGELOG", "max": 1},
]
OWN_LINE = re.compile(r"^\s*<!--.*-->\s*$")


class WriteRefused(RuntimeError):
    pass


def marker_pattern(template: str) -> re.Pattern:
    """`PR-EVALUATION sha=<head> verdict=<v>` → a regex where each `<placeholder>` is one non-blank token."""
    parts = re.split(r"(<[^<>]+>)", template)
    return re.compile("".join(r"\S+" if p.startswith("<") and p.endswith(">") else re.escape(p) for p in parts))


def allowed(profile: dict, state: dict) -> list[dict]:
    """The writes this run's routine may make, from its prompt's front matter."""
    entry = routine(profile, state.get("routine", "")) or {}
    specs = front_matter(prompt_file(entry)).get("writes") if entry else None
    if not isinstance(specs, list) or not all(isinstance(s, dict) for s in specs):
        return LOCAL_DEFAULT if entry.get("prompt") else []
    return specs


def describe(specs: list[dict]) -> str:
    out = []
    for spec in specs:
        text = spec.get("kind", "?")
        if spec.get("to"):
            text += f" to {spec['to']}"
        if spec.get("marker"):
            text += f" `{spec['marker']}`"
        out.append(text)
    return "; ".join(out) or "nothing"


def pick(specs: list[dict], kind: str, to: Optional[str], marker: Optional[str]) -> tuple[int, dict]:
    for index, spec in enumerate(specs):
        if spec.get("kind") != kind or (kind == "comment" and to and spec.get("to") != to):
            continue
        template = spec.get("marker")
        if bool(template) != bool(marker) or (template and not marker_pattern(template).fullmatch(marker or "")):
            continue
        return index, spec
    wanted = kind + (f" to {to}" if to else "") + (f" with marker `{marker}`" if marker else "")
    raise WriteRefused(f"this routine may not write a {wanted}. Its front matter allows: {describe(specs)}")


def compose(first: Optional[str], provenance: str, body: str) -> str:
    """Our header and footer around the body. Lines we add ourselves are dropped from the body first, so a body that
    already carries them (the scorecard script prints its own) does not get them twice."""
    lines = body.replace("\r\n", "\n").strip("\n").splitlines()
    while lines and (not lines[0].strip() or OWN_LINE.match(lines[0]) or lines[0].strip() == AI_HEADER):
        lines.pop(0)
    while lines and (not lines[-1].strip() or lines[-1].strip() == FOOTER):
        lines.pop()
    head = ([first] if first else []) + [provenance, AI_HEADER, ""]
    return "\n".join(head + lines + ["", FOOTER]) + "\n"


def duplicate(spec: dict, line1: Optional[str], comments: list[dict]) -> Optional[str]:
    """Why this comment would repeat one already made, or None. `dedupe: marker` makes the marker line a key;
    `dedupe: gate` says a gate skip once, until the gate changes or a human replies."""
    mode = spec.get("dedupe")
    if mode == "marker":
        for comment in comments:
            if by_routine(comment) and gates.first_line(comment.get("body")) == line1:
                return f"already posted: {comment.get('html_url')}"
    if mode == "gate":
        gate = re.search(r"\bgate=(\S+)", line1 or "")
        latest = gates.last_gate(comments)
        if gate and latest and latest["gate"] == gate.group(1) and not latest["human_after"]:
            return f"gate {gate.group(1)} was already said at {latest['url']}, and no human has replied since"
    return None


def release_body(sel: dict, tldr: str) -> str:
    lines = [f"**TL;DR:** {sel['ahead']} commit(s) ahead of {sel['production']} — {tldr.strip().rstrip('.')}."]
    if sel["closes"]:
        lines += ["", "## Closes", *[f"Closes #{n}" for n in sel["closes"]]]
    lines += ["", "## Commits", "```", *sel["commits"]]
    if sel["omitted"]:
        lines.append(f"… and {sel['omitted']} older commit(s), omitted")
    lines += ["```", "", "## Files changed", sel["files_changed"] or "(no changes)"]
    if sel["largest"]:
        lines += ["", "```", *sel["largest"], "```"]
    return "\n".join(lines)


def resolve(profile: dict, value: str) -> str:
    """A front-matter value that names a profile key, like `{ci.autofix.prefix}`, becomes that key's value."""
    found = re.fullmatch(r"\{([a-z_]+(?:\.[a-z_]+)*)\}", value or "")
    return str(lookup(profile, found.group(1)) or "") if found else value


def send(
    gh, state: dict, index: int, method: str, path: str, payload: dict, target: str, marker: Optional[str]
) -> dict:
    record = {"spec": index, "target": target, "marker": marker, "at": now_iso()}
    if state.get("dry_run"):
        extra = "".join(f"\n{k}: {payload[k]}" for k in ("title", "labels") if payload.get(k))
        print(f"DRY RUN: would {method} repos/{gh.repo}/{path} ({target}){extra}")
        print(f"-----\n{payload.get('body', '')}-----")
        record.update(dry_run=True, url=None)
    else:
        result = gh.write(method, path, payload) or {}
        record["url"] = result.get("html_url")
        if result.get("number"):
            record["number"] = result["number"]
    state.setdefault("writes", []).append(record)
    save_state(state)
    return record


def post(
    profile: dict,
    gh,
    kind: str,
    body: str = "",
    to: Optional[str] = None,
    number: Optional[int] = None,
    marker: Optional[str] = None,
    title: Optional[str] = None,
    head: Optional[str] = None,
    base: Optional[str] = None,
    tldr: Optional[str] = None,
) -> dict:
    """Make one write for this run's routine, or refuse it with the reason."""
    state = load_state()
    if state is None:
        raise WriteRefused("no run is open: run `pipeline.py begin <routine key>` first")
    specs = allowed(profile, state)
    index, spec = pick(specs, kind, to, marker)
    used = sum(1 for w in state.get("writes") or [] if w.get("spec") == index)
    if spec.get("max") and used >= spec["max"]:
        raise WriteRefused(f"this routine already made {used} of its at most {spec['max']} `{kind}` write(s) this run")
    provenance = f"<!-- agent-pipeline core={state.get('core')} run={state.get('session')} -->"
    if kind in ("comment", "issue", "pr", "pr-body", "hub-body") and not body.strip():
        raise WriteRefused("the body is empty. A run with nothing to say posts nothing")
    hub, integration = lookup(profile, "hub.issue"), lookup(profile, "branches.integration")
    line1 = f"<!-- {marker} -->" if marker else None

    if kind == "issue":
        labels = [resolve(profile, x) for x in spec.get("labels") or []]
        if APPROVAL_LABELS & set(labels):
            raise WriteRefused("a routine never opens an issue with an approval label: only a human approves")
        if not title:
            raise WriteRefused("an issue needs --title")
        if spec.get("dedupe") == "marker":
            query = f"issues?labels={labels[0]}&state=open&per_page=100" if labels else "issues?state=open&per_page=100"
            for open_issue in gh.list(query):
                if by_routine(open_issue) and gates.first_line(open_issue.get("body")) == line1:
                    return {"skipped": f"already open: #{open_issue['number']} {open_issue.get('html_url')}"}
        payload = {"title": title, "body": compose(line1, provenance, body), "labels": labels}
        record = send(gh, state, index, "POST", "issues", payload, f"issue '{title}'", marker)
        if record.get("number"):
            # a token without push access has its labels silently dropped, so read them back
            names = {x.get("name") for x in (gh.get(f"issues/{record['number']}") or {}).get("labels") or []}
            record.update(labels=sorted(names), labelled=set(labels) <= names)
            save_state(state)
        return record

    if kind == "comment":
        to = to or spec.get("to")
        if to == "hub":
            if number not in (None, hub):
                raise WriteRefused(f"this comment belongs on the hub issue #{hub}, not #{number}")
            number = hub
        if not number:
            raise WriteRefused("say which issue or PR with --issue <N>")
        issue = gh.get(f"issues/{number}")
        if issue is None:
            raise WriteRefused(f"#{number} does not exist in {gh.repo}")
        is_pr = "pull_request" in issue
        if to == "pr" and not is_pr:
            raise WriteRefused(f"#{number} is an issue, and this comment belongs on a PR")
        if to == "issue" and is_pr:
            raise WriteRefused(f"#{number} is a PR, and this comment belongs on an issue")
        if spec.get("dedupe"):
            reason = duplicate(spec, line1, gh.list(f"issues/{number}/comments?per_page=100"))
            if reason:
                return {"skipped": reason}
        payload = {"body": compose(line1, provenance, body)}
        return send(gh, state, index, "POST", f"issues/{number}/comments", payload, f"comment on #{number}", marker)

    if kind == "pr":
        prefix = resolve(profile, spec.get("head") or gates.BUILD_PREFIX)
        base = base or integration
        if not (head or "").startswith(prefix):
            raise WriteRefused(f"a PR head must start with `{prefix}`, not `{head}`")
        if base != integration:
            raise WriteRefused(f"PRs go into `{integration}`, not `{base}`")
        if not title:
            raise WriteRefused("a PR needs --title")
        payload = {"title": title, "head": head, "base": base, "body": compose(line1, provenance, body)}
        return send(gh, state, index, "POST", "pulls", payload, f"PR {head} → {base}", marker)

    if kind == "pr-body":
        prefix = resolve(profile, spec.get("head") or gates.BUILD_PREFIX)
        pr = gh.get(f"pulls/{number}") if number else None
        if not pr:
            raise WriteRefused("say which of your own PRs with --issue <N>")
        if not pr["head"]["ref"].startswith(prefix) or pr.get("state") != "open":
            raise WriteRefused(
                f"#{number} is not an open PR from `{prefix}`: a routine rewrites only its own PR's body"
            )
        payload = {"body": compose(line1, provenance, body)}
        return send(gh, state, index, "PATCH", f"pulls/{number}", payload, f"body of PR #{number}", marker)

    if kind == "hub-body":
        text = compose(lookup(profile, "hub.marker"), provenance, body)
        if len(text) > HUB_BUDGET:
            raise WriteRefused(
                f"the hub body is {len(text):,} codepoints, over its {HUB_BUDGET:,} budget (GitHub refuses 65,536). "
                "Relocate per core/hub-contract.md (Size): move Verified closed, then the oldest lowest-grade "
                "findings, verbatim into this run's AUDIT-CHANGELOG comment, and leave a one-line pointer"
            )
        return send(gh, state, index, "PATCH", f"issues/{hub}", {"body": text}, f"body of the hub #{hub}", None)

    if kind == "release-pr":
        sel = gates.select_release(gh, profile, git, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        if sel.get("stop"):
            return {"skipped": sel["stop"]}
        if not (tldr or "").strip():
            raise WriteRefused(
                "a release PR needs --tldr: its main themes, from the commit subjects, in 15 words or fewer"
            )
        text = compose(None, provenance, release_body(sel, tldr or ""))
        if sel["release_pr"]:
            n = sel["release_pr"]
            return send(gh, state, index, "PATCH", f"pulls/{n}", {"body": text}, f"release PR #{n}", None)
        payload = {"title": sel["title"], "head": sel["integration"], "base": sel["production"], "body": text}
        return send(gh, state, index, "POST", "pulls", payload, "the release PR", None)

    raise WriteRefused(f"unknown kind {kind!r}: use one of {', '.join(KINDS)}")


def read_body(path: Optional[str]) -> str:
    return Path(path).read_text() if path else ""
