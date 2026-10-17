#!/usr/bin/env python3
"""Validate a repo's agent-pipeline profile, or print a routine's launcher.

    python3 check.py <repo-root>                    # validate .claude/routines/pipeline.yml
    python3 check.py <repo-root> --launcher <key>   # print the claude.ai prompt for one routine

Runs locally at install and sync time, never inside a routine (it needs PyYAML). It checks the profile against the
repo's vendored core, or against this skill's core when the repo has none yet. Exit 1 on any error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML missing: pip install pyyaml")

SKILL_CORE = Path(__file__).resolve().parent / "core"
TOP_KEYS = "project|branches|hub|approvers|wip|orient|components|ci|risk|guards|extra_rules"
KEY_REF = re.compile(r"\{((?:" + TOP_KEYS + r")(?:\.[a-z_]+)*)\}")
BASE_REQUIRED = ["project.repo", "project.description", "branches.integration", "branches.production"]
STATUSES = {"active", "planned", "disabled"}


def lookup(profile: dict, dotted: str):
    """The value at a dotted key, or None when it is missing or empty."""
    node = profile
    for part in dotted.split("."):
        if not isinstance(node, dict) or node.get(part) in (None, "", [], {}):
            return None
        node = node[part]
    return node


def front_matter(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}
    return yaml.safe_load(text[4 : text.index("\n---", 4)]) or {}


def prompt_path(routine: dict) -> str:
    if routine.get("prompt"):
        return f".claude/routines/{routine['prompt']}"
    return f".claude/routines/core/roles/{routine['role']}.md"


def launcher(profile: dict, routine: dict) -> str:
    name, branch = profile["project"]["repo"].split("/")[-1], profile["branches"]["integration"]
    return (
        f"You are the routine `{routine['key']}` in .claude/routines/pipeline.yml.\n"
        f"Work in the {name} checkout; cd into it first if this session started in the folder above it.\n"
        f"git fetch origin {branch} --prune && git checkout origin/{branch}\n"
        f"Read .claude/routines/pipeline.yml, .claude/routines/core/shared.md and {prompt_path(routine)}, "
        "and follow them exactly. Where they conflict, the stricter rule wins."
    )


def check(root: Path, profile: dict, core: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    for key in BASE_REQUIRED:
        if lookup(profile, key) is None:
            errors.append(f"{key} is required")
    if not re.fullmatch(r"<!--\s.*\s-->", str(lookup(profile, "hub.marker") or "")):
        errors.append("hub.marker must be an HTML comment like <!-- PIPELINE-HUB -->")
    issue = lookup(profile, "hub.issue")
    if not (isinstance(issue, int) and issue > 0):
        notes.append("hub.issue is unset: install creates the hub issue and records its number")
    if not isinstance(lookup(profile, "wip.limit"), int):
        errors.append("wip.limit must be an integer")

    for i, comp in enumerate(profile.get("components") or []):
        label = f"components[{i}] ({comp.get('name', '?')})"
        for field in ("name", "paths", "tests", "static", "collect"):
            if not comp.get(field):
                errors.append(f"{label}.{field} is required")
        if comp.get("collect") and "{files}" not in comp["collect"]:
            errors.append(f"{label}.collect must contain {{files}}, where the changed test files go")
        for pattern in comp.get("tests") or []:
            if not any(root.glob(pattern)):
                notes.append(f"{label}.tests pattern {pattern!r} matches no file yet")
    integration, production = lookup(profile, "branches.integration"), lookup(profile, "branches.production")

    seen: set[str] = set()
    shared_refs = KEY_REF.findall((core / "shared.md").read_text())
    unset_notes: set[str] = set()
    for routine in profile.get("routines") or []:
        key = routine.get("key", "?")
        if key in seen:
            errors.append(f"routine {key}: duplicate key")
        seen.add(key)
        for field in ("cron", "model"):
            if not routine.get(field):
                errors.append(f"routine {key}: {field} is required")
        status = routine.get("status", "active")
        if status not in STATUSES:
            errors.append(f"routine {key}: status must be one of {sorted(STATUSES)}")
        if bool(routine.get("role")) == bool(routine.get("prompt")):
            errors.append(f"routine {key}: give exactly one of role (a core role) or prompt (local/<file>.md)")
            continue

        if routine.get("role"):
            role_file = core / "roles" / f"{routine['role']}.md"
            if not role_file.exists():
                errors.append(f"routine {key}: no core role {routine['role']!r} ({role_file})")
                continue
            needs = front_matter(role_file).get("needs") or []
            text = role_file.read_text()
        else:
            local = root / ".claude" / "routines" / routine["prompt"]
            if not local.exists():
                errors.append(f"routine {key}: prompt file {local} does not exist")
                continue
            needs, text = [], local.read_text()

        missing = [n for n in needs if lookup(profile, n) is None]
        if missing:
            (errors if status == "active" else notes).append(
                f"routine {key}: needs {', '.join(missing)} before it can be enabled"
            )
        if routine.get("role") == "release-manager" and integration == production and status == "active":
            errors.append(f"routine {key}: the repo is trunk-based ({integration}), so release-manager must stay off")
        if "hub-contract.md" in text:
            text += (core / "hub-contract.md").read_text()
        for ref in set(KEY_REF.findall(text)) | set(shared_refs):
            if lookup(profile, ref) is None and ref not in needs and ref not in BASE_REQUIRED:
                unset_notes.add(ref)

    for ref in sorted(unset_notes):
        notes.append(f"{{{ref}}} is unset: prompts treat it as none")
    for entry in profile.get("removed") or []:
        for field in ("key", "removed", "reason"):
            if not entry.get(field):
                errors.append(f"removed entry {entry.get('key', '?')}: {field} is required")
    return errors, notes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="the repo root")
    ap.add_argument("--launcher", metavar="KEY", help="print the claude.ai prompt for this routine")
    args = ap.parse_args()

    profile_path = args.root / ".claude" / "routines" / "pipeline.yml"
    profile = yaml.safe_load(profile_path.read_text())
    vendored = args.root / ".claude" / "routines" / "core"
    core = vendored if (vendored / "shared.md").exists() else SKILL_CORE

    if args.launcher:
        routine = next((r for r in profile.get("routines") or [] if r.get("key") == args.launcher), None)
        if routine is None:
            sys.exit(f"no routine {args.launcher!r} in {profile_path}")
        print(launcher(profile, routine))
        return

    errors, notes = check(args.root, profile, core)
    for line in errors:
        print(f"error: {line}")
    for line in notes:
        print(f"note:  {line}")
    print(f"{profile_path}: {len(errors)} error(s), {len(notes)} note(s) (core: {core})")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
