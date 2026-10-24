"""The two ungated loops (ci-doctor, pipeline-rnd) keep their caps, and the evaluator scope comes from the profile."""

import copy
import importlib.util
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[1]
ROLES = SKILL / "core" / "roles"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("check", SKILL / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def role(name: str) -> str:
    return (ROLES / f"{name}.md").read_text()


def test_ci_doctor_is_capped_and_pausable():
    text = role("ci-doctor")
    for cap in ("{ci.autofix.max_attempts}", "{ci.autofix.max_open}", "one attempt per run", "ci-blocked"):
        assert cap in text, cap
    assert "agent-pause" in text
    assert "Rerun a given run at most once" in text
    assert "never delete a test, never add a skip" in text


def test_pipeline_rnd_never_touches_live_config_or_loosens_a_guard():
    text = role("pipeline-rnd")
    assert "Never call\n  RemoteTrigger" in text or "Never call RemoteTrigger" in text
    assert "Never remove or weaken a hard rule" in text
    assert "Push only to `rnd/pipeline-*`" in text
    assert "{rnd.max_commits}" in text and "rnd-stop" in text and "agent-pause" in text
    assert "Cite\nonly pages you fetched" in text or "Cite only pages you fetched" in text


def test_evaluator_scope_comes_from_the_profile():
    text = role("pr-evaluator")
    assert "{evaluate.heads}" in text and "{evaluate.opt_in_label}" in text
    assert "its head starts with `groomed/`" not in text


def test_an_active_loop_without_its_profile_keys_is_an_error():
    profile = copy.deepcopy(yaml.safe_load((FIXTURES / "release-repo/.claude/routines/pipeline.yml").read_text()))
    profile["routines"] += [
        {"key": "ci-doctor", "role": "ci-doctor", "status": "active", "cron": "0 1 * * 1-5", "model": "m"},
        {"key": "pipeline-rnd", "role": "pipeline-rnd", "status": "active", "cron": "30 5 * * 1-5", "model": "m"},
    ]
    errors, _ = check.check(FIXTURES / "release-repo", profile, check.SKILL_CORE)
    assert any(e.startswith("routine ci-doctor: needs ci.watch, ci.autofix") for e in errors)
    assert any(e.startswith("routine pipeline-rnd: needs rnd.upstream") for e in errors)
