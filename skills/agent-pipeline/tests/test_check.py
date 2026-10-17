"""check.py: profile validation and the launcher text."""

import copy
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("check", SKILL / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def load(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name / ".claude/routines/pipeline.yml").read_text())


def run(name: str, profile: dict | None = None) -> tuple[list[str], list[str]]:
    return check.check(FIXTURES / name, profile or load(name), check.SKILL_CORE)


def routine(profile: dict, key: str) -> dict:
    return next(r for r in profile["routines"] if r["key"] == key)


def test_release_repo_passes():
    errors, _ = run("release-repo")
    assert errors == []


def test_trunk_monorepo_passes_and_says_build_waits_for_ci():
    errors, notes = run("trunk-monorepo")
    assert errors == []
    assert any("gated-implementer: needs ci.required, ci.proof" in n for n in notes)
    assert any("{orient.invariants} is unset" in n for n in notes)


def test_an_active_routine_missing_what_it_needs_is_an_error():
    profile = copy.deepcopy(load("release-repo"))
    del profile["ci"]
    errors, _ = run("release-repo", profile)
    assert any("routine gated-implementer: needs ci.required, ci.proof" in e for e in errors)
    assert any("routine pr-evaluator: needs ci.required, ci.proof" in e for e in errors)


def test_release_manager_cannot_be_active_on_a_trunk_based_repo():
    profile = copy.deepcopy(load("release-repo"))
    profile["branches"]["production"] = "release"
    errors, _ = run("release-repo", profile)
    assert any("trunk-based (release), so release-manager must stay off" in e for e in errors)


def test_collect_needs_the_files_placeholder():
    profile = copy.deepcopy(load("release-repo"))
    profile["components"][0]["collect"] = "python -m pytest --collect-only -q"
    errors, _ = run("release-repo", profile)
    assert any("collect must contain {files}" in e for e in errors)


@pytest.mark.parametrize("extra", [{"prompt": "local/audit.md"}, {"role": None}])
def test_a_routine_has_exactly_one_of_role_or_prompt(extra):
    profile = copy.deepcopy(load("release-repo"))
    routine(profile, "scorecard").update(extra)
    errors, _ = run("release-repo", profile)
    assert any("routine scorecard: give exactly one of role" in e for e in errors)


def test_a_missing_local_prompt_is_an_error():
    profile = copy.deepcopy(load("release-repo"))
    routine(profile, "audit")["prompt"] = "local/nope.md"
    errors, _ = run("release-repo", profile)
    assert any("prompt file" in e and "nope.md" in e for e in errors)


def test_launcher_checks_out_integration_and_names_the_routine_and_its_prompt():
    profile = load("release-repo")
    text = check.launcher(profile, routine(profile, "pr-evaluator"))
    assert "You are the routine `pr-evaluator`" in text
    assert "cd into it first if this session started in the folder above it" in text
    assert "git fetch origin release --prune && git checkout origin/release" in text
    assert ".claude/routines/core/shared.md and .claude/routines/core/roles/pr-evaluator.md" in text
    assert ".claude/routines/local/audit.md" in check.launcher(profile, routine(profile, "audit"))


def exists(profile: dict, dotted: str) -> bool:
    node = profile
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def test_the_template_profile_defines_every_key_the_core_references():
    template = yaml.safe_load((SKILL / "templates/pipeline.yml").read_text())
    refs = set()
    for path in (SKILL / "core").rglob("*.md"):
        refs |= set(check.KEY_REF.findall(path.read_text()))
    assert refs, "the core should reference profile keys"
    assert sorted(r for r in refs if not exists(template, r)) == []


def test_the_template_profile_passes_with_only_notes(tmp_path):
    (tmp_path / ".claude/routines/local").mkdir(parents=True)
    (tmp_path / ".claude/routines/local/audit.md").write_text("audit, see core/hub-contract.md\n")
    profile = yaml.safe_load((SKILL / "templates/pipeline.yml").read_text())
    errors, notes = check.check(tmp_path, profile, check.SKILL_CORE)
    assert errors == []
    assert any("hub.issue is unset" in n for n in notes)


def test_role_front_matter_is_complete():
    for path in (SKILL / "core/roles").glob("*.md"):
        meta = check.front_matter(path)
        assert meta.get("role") == path.stem
        assert meta.get("tools") and isinstance(meta.get("needs"), list) and meta.get("writes")
        assert re.fullmatch(r"[a-z-]+", meta["role"])
