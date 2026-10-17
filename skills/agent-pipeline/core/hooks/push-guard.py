#!/usr/bin/env python3
"""PreToolUse(Bash) hook for cloud routine sessions: block a `git push` that writes the integration or production
branch, force-pushes, pushes every branch, or deletes one.

Routines read their prompts from the integration branch, and GitHub does not limit which branches a routine may push,
so this is the backstop for the shared "never push there" rule. Local sessions are left alone. The two branch names
come from `.claude/routines/pipeline.yml`. Exit 2 blocks the call and hands stderr back to Claude.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

if os.getenv("CLAUDE_CODE_REMOTE") != "true":
    sys.exit(0)

PROFILE = Path(__file__).resolve().parents[2] / "pipeline.yml"  # <repo>/.claude/routines/pipeline.yml
# `git push` in command position only, so a quoted mention or `grep "git push"` doesn't trip it
PUSH = re.compile(r"(?:^|[;&|(\n]|\bthen|\bdo)\s*git\s+((?:(?:-C|-c)\s+\S+\s+|--\S+\s+)*)push\b([^;&|\n]*)")
TAKES_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def protected() -> set[str]:
    text = PROFILE.read_text() if PROFILE.exists() else ""
    # flow or block style: `integration: release` / `{integration: release, production: master}`
    found = set(re.findall(r"\b(?:integration|production):\s*[\"']?([\w./-]+)", text))
    return found or {"main", "master"}


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout.strip()


def problems(args: list[str], repo: str, guarded: set[str]) -> list[str]:
    found, positional, skip = [], [], False
    for tok in args:
        if skip:
            skip = False
        elif tok in TAKES_VALUE:
            skip = True
        elif tok in ("--force", "--force-if-includes") or tok.startswith("--force-with-lease"):
            found.append(f"force-push ({tok})")
        elif tok in ("--delete", "--all", "--mirror", "--branches", "--prune"):
            found.append(f"{tok} rewrites or deletes branches")
        elif tok.startswith("-") and not tok.startswith("--") and len(tok) > 1:
            found += [f"force-push ({tok})"] * ("f" in tok[1:]) + [f"branch delete ({tok})"] * ("d" in tok[1:])
        elif not tok.startswith("-"):
            positional.append(tok)

    current = git(repo, "symbolic-ref", "--short", "-q", "HEAD")  # empty when detached
    targets = []
    if len(positional) <= 1:  # no refspec: the current branch goes to its push target
        targets += [current, git(repo, "rev-parse", "--abbrev-ref", "@{push}").split("/", 1)[-1]]
    for spec in positional[1:]:
        if spec.startswith("+"):
            found.append(f"force-push ({spec})")
            spec = spec[1:]
        src, _, dst = spec.partition(":")
        if spec.startswith(":"):
            found.append(f"branch delete ({spec})")
        dst = dst or (current if src == "HEAD" else src)
        targets.append(dst.removeprefix("refs/heads/"))
    found += [f"push to protected branch {t}" for t in targets if t in guarded]
    return found


payload = json.load(sys.stdin)
command = payload.get("tool_input", {}).get("command", "")
guarded = protected()
blocked = []
for m in PUSH.finditer(command):
    repo = re.search(r"-C\s+(\S+)", m.group(1))
    repo = repo.group(1) if repo else payload.get("cwd") or "."
    try:
        blocked += problems(shlex.split(m.group(2)), repo, guarded)
    except ValueError:
        blocked.append("push arguments could not be parsed")

if blocked:
    print(
        "Blocked by push-guard: " + "; ".join(dict.fromkeys(blocked)) + ".\n"
        f"Routines never push to {', '.join(sorted(guarded))}, never force-push and never delete branches "
        "(.claude/routines/core/shared.md). Push your own branch with a plain `git push origin HEAD:<your-branch>`.",
        file=sys.stderr,
    )
    sys.exit(2)
