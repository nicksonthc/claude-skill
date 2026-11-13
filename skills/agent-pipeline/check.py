#!/usr/bin/env python3
"""Validate a repo's agent-pipeline profile, print a routine's launcher or the repo's rulesets, or check the live repo.

    python3 check.py <repo-root>                    # validate .claude/routines/pipeline.yml
    python3 check.py <repo-root> --launcher <key>   # print the claude.ai prompt for one routine
    python3 check.py <repo-root> --rulesets         # print the branch rulesets to apply, as a JSON array
    python3 check.py <repo-root> --doctor           # validate, then check the live repo through `gh api`

Runs locally at install and sync time, never inside a routine. It checks the profile against the repo's vendored core,
or against this skill's core when the repo has none yet. Exit 1 on any error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML missing: pip install pyyaml")

SKILL_CORE = Path(__file__).resolve().parent / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL_CORE / "bin"))
from pcfg import front_matter, lookup  # noqa: E402

TOP_KEYS = "project|branches|hub|approvers|wip|orient|components|ci|evaluate|rnd|risk|guards|extra_rules|ledger"
KEY_REF = re.compile(r"\{((?:" + TOP_KEYS + r")(?:\.[a-z_]+)*)\}")
BASE_REQUIRED = ["project.repo", "project.description", "branches.integration", "branches.production"]
STATUSES = {"active", "planned", "disabled"}
HOOKS = ("push-guard.py", "write-guard.py", "require-ai-marker.sh", "run-ledger.py")
# the gateway posts the first six; the rest are plain git or `gh api` calls the hooks cover
WRITE_KINDS = {"comment", "issue", "pr", "pr-body", "hub-body", "release-pr", "push", "label", "dispatch", "rerun"}
APPROVAL_LABELS = {"groomed"}
COMMENT_TARGETS = {"hub", "issue", "pr"}
DEDUPE = {"marker", "gate"}
DEFAULT_LEDGER = "pipeline-ledger"


def prompt_path(routine: dict) -> str:
    if routine.get("prompt"):
        return f".claude/routines/{routine['prompt']}"
    return f".claude/routines/core/roles/{routine['role']}.md"


def launcher(profile: dict, routine: dict, control_plane: bool = True) -> str:
    """The claude.ai prompt. `control_plane` is False for a repo still on a 1.x core, which has no pipeline.py."""
    name, branch = profile["project"]["repo"].split("/")[-1], profile["branches"]["integration"]
    begin = (
        f"python3 .claude/routines/core/bin/pipeline.py begin {routine['key']}"
        " (add --dry-run when this message contains DRY RUN)\n"
        if control_plane
        else ""
    )
    return (
        f"You are the routine `{routine['key']}` in .claude/routines/pipeline.yml.\n"
        f"Work in the {name} checkout; cd into it first if this session started in the folder above it.\n"
        f"git fetch origin {branch} --prune && git checkout origin/{branch}\n"
        f"{begin}"
        f"Read .claude/routines/pipeline.yml, .claude/routines/core/shared.md and {prompt_path(routine)}, "
        "and follow them exactly. Where they conflict, the stricter rule wins."
    )


def write_problems(label: str, writes) -> list[str]:
    """A role's `writes:` front matter: the structured list `pipeline.py post` enforces."""
    if writes is None:
        return []
    if not isinstance(writes, list):
        return [f"{label}: writes must be a list"]
    found = []
    for i, spec in enumerate(writes):
        where = f"{label}: writes[{i}]"
        if not isinstance(spec, dict):
            found.append(f"{where} must be a mapping like {{kind: comment, to: hub, marker: NAME}}")
            continue
        kind = spec.get("kind")
        if kind not in WRITE_KINDS:
            found.append(f"{where}.kind must be one of {sorted(WRITE_KINDS)}")
        if kind == "comment" and spec.get("to") not in COMMENT_TARGETS:
            found.append(f"{where}.to must be one of {sorted(COMMENT_TARGETS)}")
        if spec.get("dedupe") not in (None, *DEDUPE):
            found.append(f"{where}.dedupe must be one of {sorted(DEDUPE)}")
        if spec.get("max") is not None and not (isinstance(spec["max"], int) and spec["max"] > 0):
            found.append(f"{where}.max must be a positive integer")
        if "-->" in str(spec.get("marker") or ""):
            found.append(f"{where}.marker is written without <!-- -->")
        labels = spec.get("labels")
        if labels is not None and not (isinstance(labels, list) and all(isinstance(x, str) for x in labels)):
            found.append(f"{where}.labels must be a list of label names")
        elif APPROVAL_LABELS & set(labels or []):
            found.append(f"{where}.labels names an approval label: only a human approves")
    return found


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

    ledger = profile.get("ledger")
    if ledger is not None and not isinstance(ledger, dict):
        errors.append("ledger must be a mapping: {branch: pipeline-ledger, turso_url: null}")
    elif ledger:
        branch = ledger.get("branch")
        if branch is not None and (not re.fullmatch(r"[\w./-]+", str(branch)) or branch in (integration, production)):
            errors.append(
                "ledger.branch must be a plain branch name, other than the integration and production branches"
            )
        url = ledger.get("turso_url")
        if url and not re.match(r"^(libsql|https)://", str(url)):
            errors.append("ledger.turso_url must start with libsql:// or https://")

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
        if routine.get("environment_id") and not str(routine["environment_id"]).startswith("env_"):
            errors.append(f"routine {key}: environment_id must be a claude.ai environment id (env_…)")
        if bool(routine.get("role")) == bool(routine.get("prompt")):
            errors.append(f"routine {key}: give exactly one of role (a core role) or prompt (local/<file>.md)")
            continue

        if routine.get("role"):
            role_file = core / "roles" / f"{routine['role']}.md"
            if not role_file.exists():
                errors.append(f"routine {key}: no core role {routine['role']!r} ({role_file})")
                continue
            meta = front_matter(role_file)
            needs = meta.get("needs") or []
            text = role_file.read_text()
        else:
            local = root / ".claude" / "routines" / routine["prompt"]
            if not local.exists():
                errors.append(f"routine {key}: prompt file {local} does not exist")
                continue
            meta, needs, text = front_matter(local), [], local.read_text()
        if routine.get("prompt") or control_plane(core):  # a 1.x core's roles describe their writes in prose
            errors += write_problems(f"routine {key}", meta.get("writes"))

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
    missing_hooks = hook_problems(root)
    if missing_hooks:
        notes.append(f".claude/settings.json does not register {', '.join(missing_hooks)} (REFERENCE.md §2)")
    return errors, notes


def control_plane(core: Path) -> bool:
    """A 2.x core: it has `bin/pipeline.py`, and its roles declare structured writes."""
    return (core / "bin" / "pipeline.py").exists()


def hook_problems(root: Path) -> list[str]:
    settings = root / ".claude" / "settings.json"
    text = settings.read_text() if settings.exists() else ""
    return [hook for hook in HOOKS if hook not in text]


def rulesets(profile: dict) -> list[dict]:
    """Server-side rules that hold whatever an agent does. Routines act as the owner, so there are no bypass actors.

    Required approvals stay 0: routine PRs are authored by the owner's account, and GitHub forbids approving your own
    PR. Required checks go on the integration branch only, where PR CI runs.
    """
    integration, production = lookup(profile, "branches.integration"), lookup(profile, "branches.production")
    ledger = lookup(profile, "ledger.branch") or DEFAULT_LEDGER
    checks = [{"context": name} for name in lookup(profile, "ci.required") or []]
    keep = [{"type": "deletion"}, {"type": "non_fast_forward"}]
    via_pr = {
        "type": "pull_request",
        "parameters": {
            "required_approving_review_count": 0,
            "dismiss_stale_reviews_on_push": False,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": False,
        },
    }
    status = {
        "type": "required_status_checks",
        "parameters": {"strict_required_status_checks_policy": False, "required_status_checks": checks},
    }

    def ruleset(branch: str, rules: list[dict]) -> dict:
        return {
            "name": f"agent-pipeline: {branch}",
            "target": "branch",
            "enforcement": "active",
            "bypass_actors": [],
            "conditions": {"ref_name": {"include": [f"refs/heads/{branch}"], "exclude": []}},
            "rules": rules,
        }

    out = [ruleset(integration, keep + [via_pr] + ([status] if checks else []))]
    if production != integration:
        out.append(ruleset(production, keep + [via_pr]))
    out.append(ruleset(ledger, keep))
    return out


def gh_get(path: str):
    """(JSON, None) on success, (None, the HTTP status) on failure, through the owner's local `gh` login."""
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if proc.returncode:
        status = re.search(r"HTTP (\d{3})", proc.stderr)
        return None, (int(status.group(1)) if status else proc.stderr.strip()[:120])
    return json.loads(proc.stdout or "null"), None


def doctor(root: Path, profile: dict) -> tuple[list[str], list[str]]:
    """Check the live repo against the profile: hub, label, rulesets, ledger branch, CI names, hooks, core version."""
    errors: list[str] = []
    notes: list[str] = []
    repo = lookup(profile, "project.repo")
    info, failure = gh_get(f"repos/{repo}")
    if info is None:
        return [f"cannot read {repo} through gh api ({failure}): is gh logged in?"], notes
    hub = lookup(profile, "hub.issue")
    if hub:
        issue, _ = gh_get(f"repos/{repo}/issues/{hub}")
        if not issue or issue.get("state") != "open":
            errors.append(f"the hub issue #{hub} is missing or closed")
        elif not (issue.get("body") or "").startswith(str(lookup(profile, "hub.marker"))):
            notes.append(f"the hub issue #{hub} does not start with hub.marker yet; the audit writes it")
    if gh_get(f"repos/{repo}/labels/groomed")[0] is None:
        errors.append(f"the label `groomed` is missing: gh api repos/{repo}/labels -f name=groomed")
    present, failure = gh_get(f"repos/{repo}/rulesets")
    if present is None:
        notes.append(f"rulesets could not be read ({failure}); private repos need GitHub Pro, Team or Enterprise")
    else:
        names = {r.get("name") for r in present}
        for want in rulesets(profile):
            if want["name"] not in names:
                errors.append(
                    f"the ruleset {want['name']!r} is missing: apply `check.py --rulesets` (SKILL.md, Install)"
                )
    branch = lookup(profile, "ledger.branch") or DEFAULT_LEDGER
    if gh_get(f"repos/{repo}/branches/{branch}")[0] is None:
        notes.append(f"the ledger branch {branch} does not exist yet; the first run creates it")
    proof = lookup(profile, "ci.proof")
    wanted = (lookup(profile, "ci.required") or []) + ([proof] if proof else [])
    if wanted:
        integration = lookup(profile, "branches.integration")
        seen: set = set()
        for pr in gh_get(f"repos/{repo}/pulls?state=all&base={integration}&per_page=5")[0] or []:
            runs = gh_get(f"repos/{repo}/commits/{pr['head']['sha']}/check-runs?per_page=100")[0] or {}
            seen |= {r.get("name") for r in runs.get("check_runs", [])}
        for name in wanted:
            if seen and name not in seen:
                notes.append(
                    f"no recent PR into {integration} ran a check named {name!r}: compare ci.* with the job names"
                )
    missing_hooks = hook_problems(root)
    if missing_hooks:
        errors.append(f".claude/settings.json does not register {', '.join(missing_hooks)} (REFERENCE.md §2)")
    vendored = root / ".claude" / "routines" / "core" / "VERSION"
    upstream = (SKILL_CORE / "VERSION").read_text().strip()
    if not vendored.exists():
        notes.append(f"the vendored core predates 2.0; the skill's core is {upstream} (update the core)")
    elif vendored.read_text().strip() != upstream:
        notes.append(f"the vendored core is {vendored.read_text().strip()}; the skill's core is {upstream}")
    return errors, notes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="the repo root")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--launcher", metavar="KEY", help="print the claude.ai prompt for this routine")
    mode.add_argument("--rulesets", action="store_true", help="print the branch rulesets to apply, as a JSON array")
    mode.add_argument("--doctor", action="store_true", help="also check the live repo through gh api")
    args = ap.parse_args()

    profile_path = args.root / ".claude" / "routines" / "pipeline.yml"
    profile = yaml.safe_load(profile_path.read_text())
    vendored = args.root / ".claude" / "routines" / "core"
    core = vendored if (vendored / "shared.md").exists() else SKILL_CORE

    if args.launcher:
        routine = next((r for r in profile.get("routines") or [] if r.get("key") == args.launcher), None)
        if routine is None:
            sys.exit(f"no routine {args.launcher!r} in {profile_path}")
        print(launcher(profile, routine, control_plane(core)))
        return
    if args.rulesets:
        print(json.dumps(rulesets(profile), indent=2))
        return

    errors, notes = check(args.root, profile, core)
    if args.doctor:
        live_errors, live_notes = doctor(args.root, profile)
        errors, notes = errors + live_errors, notes + live_notes
    for line in errors:
        print(f"error: {line}")
    for line in notes:
        print(f"note:  {line}")
    print(f"{profile_path}: {len(errors)} error(s), {len(notes)} note(s) (core: {core})")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
