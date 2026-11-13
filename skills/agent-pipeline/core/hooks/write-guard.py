#!/usr/bin/env python3
"""PreToolUse(Bash | GitHub MCP) hook for cloud routine sessions: block the GitHub writes no routine may make.

Routines act through the repo owner's GitHub identity, so GitHub cannot tell a routine's merge, approval or close
from the owner's. This hook is the client-side backstop for the hard rules in core/shared.md:
- no merges, reviews, or closing / reopening issues and PRs;
- no approval label (a human approves);
- no ref deletes or moves of protected branches;
- no repository settings changes, and no writes to any other repo.

Rulesets from `check.py --rulesets` are the server-side backstop. Local sessions are left alone. Exit 2 blocks the
call and hands stderr back to Claude. `git push` belongs to push-guard.py.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path

if os.getenv("CLAUDE_CODE_REMOTE") != "true":
    sys.exit(0)

PROFILE = Path(__file__).resolve().parents[2] / "pipeline.yml"  # <repo>/.claude/routines/pipeline.yml
APPROVAL_LABELS = ("groomed",)
SETTINGS = re.compile(
    r"^/(rulesets|branches/[^/]+/protection|collaborators|hooks|keys|invitations|environments|pages|transfer|topics"
    r"|actions/(secrets|variables|permissions)|vulnerability-alerts|automated-security-fixes|properties)(/|$)"
)
OPERATORS = set(";&|()")
GH_CLI = {
    ("pr", "merge"),
    ("pr", "close"),
    ("pr", "reopen"),
    ("pr", "review"),
    ("issue", "close"),
    ("issue", "reopen"),
    ("issue", "delete"),
    ("issue", "transfer"),
    ("repo", "delete"),
    ("repo", "edit"),
    ("repo", "rename"),
    ("repo", "archive"),
}


def profile_facts() -> tuple[set, set]:
    """The repos a routine may write to (this one, and pipeline-rnd's `rnd.upstream`), and the protected branches."""
    text = PROFILE.read_text() if PROFILE.exists() else ""
    repos = set(re.findall(r"\b(?:repo|upstream):\s*[\"']?([\w.-]+/[\w.-]+)", text))
    branches = set(re.findall(r"\b(?:integration|production):\s*[\"']?([\w./-]+)", text))
    return repos, (branches or {"main", "master"})


def segments(command: str):
    """Each simple command, as tokens. A line shlex cannot split is skipped: the API checks below need its args."""
    for line in command.splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            continue
        current: list = []
        for token in tokens:
            if token and set(token) <= OPERATORS:
                if current:
                    yield current
                current = []
            else:
                current.append(token)
        if current:
            yield current


def api_call(args: list) -> tuple:
    """(method, path, fields, JSON input, reads stdin) of a `gh api` argument list. Fields are (key, value) pairs."""
    method, path, fields, input_file = None, None, [], None
    takes_value = {"-H", "--header", "-q", "--jq", "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-X", "--method") and i + 1 < len(args):
            method, i = args[i + 1].upper(), i + 2
        elif arg.startswith("--method="):
            method, i = arg.split("=", 1)[1].upper(), i + 1
        elif arg.startswith("-X") and len(arg) > 2:
            method, i = arg[2:].upper(), i + 1
        elif arg in ("-f", "-F", "--field", "--raw-field") and i + 1 < len(args):
            fields.append(tuple(args[i + 1].split("=", 1) + [""])[:2])
            i += 2
        elif arg.startswith(("--field=", "--raw-field=")):
            fields.append(tuple(arg.split("=", 1)[1].split("=", 1) + [""])[:2])
            i += 1
        elif arg == "--input" and i + 1 < len(args):
            input_file, i = args[i + 1], i + 2
        elif arg in takes_value:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            path = path or arg
            i += 1
    data = None
    if input_file and input_file != "-" and Path(input_file).is_file():
        try:
            data = json.loads(Path(input_file).read_text())
        except ValueError:
            data = None
    method = method or ("POST" if fields or input_file else "GET")
    path = re.sub(r"^https://api\.github\.com/", "", path or "").lstrip("/").split("?", 1)[0]
    return method, path, fields, data, input_file == "-"


def values(fields: list, data, key: str) -> list:
    """Every value given for `key` (or `key[]`), from -f/-F fields and from an --input JSON file."""
    found = [v for k, v in fields if k == key or k.startswith(key + "[")]
    if isinstance(data, dict) and data.get(key) is not None:
        found += data[key] if isinstance(data[key], list) else [data[key]]
    elif isinstance(data, list) and key == "labels":
        found += data
    return [str(v.get("name") if isinstance(v, dict) else v) for v in found]


def api_problems(method: str, path: str, fields: list, data, stdin: str, repo: set, protected: set) -> list:
    """What is forbidden about one `gh api` call. Only structured fields count, never body text, so a comment that
    mentions a label or a state is never mistaken for setting one. `stdin` is the command text when the JSON comes
    from a heredoc."""
    if method == "GET":
        return []
    found = []
    match = re.match(r"^repos/([^/]+)/([^/]+)(/.*)?$", path)
    if not match:
        return [f"a {method} outside this repo ({path or '?'})"]
    target, rest = f"{match.group(1)}/{match.group(2)}", match.group(3) or ""
    if repo and target not in repo | {"{owner}/{repo}", ":owner/:repo"}:
        found.append(f"a write to {target}, which is not this pipeline's repo ({', '.join(sorted(repo))})")
    if re.fullmatch(r"/pulls/\d+/merge|/merges", rest):
        found.append("a merge (a human merges every PR)")
    if re.fullmatch(r"/pulls/\d+/reviews(/\d+(/events)?)?", rest):
        found.append("a PR review (routines comment; they never approve, request changes or review)")
    item = re.fullmatch(r"/(issues|pulls)/\d+", rest)
    states = values(fields, data, "state") + re.findall(r'"state"\s*:\s*"(\w+)"', stdin)
    if item and any(s in ("closed", "open") for s in states):
        found.append("closing or reopening an issue or PR")
    labels = values(fields, data, "labels") + re.findall(r'"labels"\s*:\s*\[([^\]]*)\]', stdin)
    if (item or re.fullmatch(r"/issues(/\d+/labels)?", rest)) and method in ("POST", "PUT", "PATCH"):
        if any(label in value for value in labels for label in APPROVAL_LABELS):
            found.append("adding an approval label (only a human approves)")
    if method == "DELETE" and rest.startswith("/git/refs/"):
        found.append("deleting a branch or tag")
    ref = re.fullmatch(r"/git/refs/heads/(.+)", rest)
    if ref and method == "PATCH" and ref.group(1) in protected:
        found.append(f"moving the protected branch {ref.group(1)}")
    if rest in ("", "/") and method in ("PATCH", "DELETE"):
        found.append("changing or deleting the repository")
    if SETTINGS.match(rest):
        found.append("changing repository settings")
    return found


def bash_problems(command: str, repo: set, protected: set) -> list:
    found = []
    for tokens in segments(command):
        while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):  # env assignments before the command
            tokens = tokens[1:]
        if len(tokens) < 2 or tokens[0] != "gh":
            continue
        if tokens[1] == "api":
            method, path, fields, data, stdin = api_call(tokens[2:])
            found += api_problems(method, path, fields, data, command if stdin else "", repo, protected)
        elif len(tokens) > 2 and (tokens[1], tokens[2]) in GH_CLI:
            found.append(f"`gh {tokens[1]} {tokens[2]}`")
        elif len(tokens) > 2 and tokens[1] in ("issue", "pr") and tokens[2] == "edit":
            adds = [tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t in ("--add-label", "-l")]
            if any(label in value for value in adds for label in APPROVAL_LABELS):
                found.append("adding an approval label (only a human approves)")
    return found


def mcp_problems(tool: str, tool_input: dict, repo: set) -> list:
    """The same rules for GitHub MCP tools, judged by tool name and structured input."""
    name, found = tool.lower(), []
    owner, target = tool_input.get("owner"), tool_input.get("repo")
    writes = re.search(r"create|update|add|delete|merge|push|write|edit|assign|fork|close|label|review", name)
    if writes and owner and target and repo and f"{owner}/{target}" not in repo:
        found.append(f"a write to {owner}/{target}, which is not this pipeline's repo ({', '.join(sorted(repo))})")
    if "merge" in name:
        found.append("a merge (a human merges every PR)")
    if "review" in name and re.search(r"create|submit|write|approve", name):
        found.append("a PR review")
    if "delete" in name:
        found.append("a delete")
    if tool_input.get("state") in ("closed", "open") and re.search(r"update|write|edit", name):
        found.append("closing or reopening an issue or PR")
    labels = tool_input.get("labels") or []
    labels = [labels] if isinstance(labels, str) else labels
    if writes and any(str(label) in APPROVAL_LABELS for label in labels):
        found.append("adding an approval label (only a human approves)")
    return found


payload = json.load(sys.stdin)
repo, protected = profile_facts()
tool = payload.get("tool_name", "")
tool_input = payload.get("tool_input") or {}
if tool == "Bash":
    blocked = bash_problems(tool_input.get("command", ""), repo, protected)
elif tool.startswith("mcp__"):
    blocked = mcp_problems(tool, tool_input, repo)
else:
    blocked = []

if blocked:
    print(
        "Blocked by write-guard: " + "; ".join(dict.fromkeys(blocked)) + ".\n"
        "Routines never merge, review, close or reopen, approve, delete refs, change settings, or write outside "
        "their repo (.claude/routines/core/shared.md). Post comments and PRs through "
        "`python3 .claude/routines/core/bin/pipeline.py post`.",
        file=sys.stderr,
    )
    sys.exit(2)
