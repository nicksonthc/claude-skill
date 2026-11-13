"""writes.py: the one way a role writes to GitHub — assembly, per-role limits, dedupe, DRY RUN."""

from __future__ import annotations

import gates
import ledger
import pytest
import writes
from conftest import ROUTINE, FakeGitHub, comment, issue, load_profile

PROFILE = load_profile()  # hub #42, integration release, production master
HEADER, FOOTER = writes.AI_HEADER, writes.FOOTER


@pytest.fixture
def run(run_dir):
    def start(key, dry_run=False):
        return ledger.begin(PROFILE, key, dry_run)

    return start


def hub_routes(**extra):
    return {"issues/42": issue(42), "issues/7": issue(7), "issues/5": {**issue(5), "pull_request": {}}, **extra}


def test_compose_puts_our_lines_around_the_body_once_even_when_the_body_already_carries_them():
    body = f"<!-- ROUTINE-SCORECARD week=2026-W46 -->\n<!-- agent-pipeline core=x run=y -->\n{HEADER}\n\n## Table\n| a |\n\n{FOOTER}\n"
    text = writes.compose(
        "<!-- ROUTINE-SCORECARD week=2026-W46 -->", "<!-- agent-pipeline core=2.0.0+abc run=s1 -->", body
    )
    lines = text.splitlines()
    assert lines[:4] == [
        "<!-- ROUTINE-SCORECARD week=2026-W46 -->",
        "<!-- agent-pipeline core=2.0.0+abc run=s1 -->",
        HEADER,
        "",
    ]
    assert lines[4:6] == ["## Table", "| a |"] and lines[-1] == FOOTER
    assert text.count(HEADER) == 1 and text.count(FOOTER) == 1


def test_a_marker_template_matches_one_token_per_placeholder():
    pattern = writes.marker_pattern("PR-EVALUATION sha=<head> verdict=<verdict>")
    assert pattern.fullmatch("PR-EVALUATION sha=abc verdict=PASS")
    assert not pattern.fullmatch("PR-EVALUATION sha=abc verdict=PASS extra")
    assert not pattern.fullmatch("PR-EVALUATION sha= verdict=PASS")


def test_nothing_is_written_before_begin(run_dir):
    with pytest.raises(writes.WriteRefused, match="begin"):
        writes.post(PROFILE, FakeGitHub(hub_routes()), "comment", body="x", marker="BACKLOG-GROOM")


def test_a_groom_comment_goes_on_the_hub_with_its_marker_and_is_recorded(run, tmp_path):
    run("backlog-groom")
    gh = FakeGitHub(hub_routes())
    result = writes.post(PROFILE, gh, "comment", body="**TL;DR:** 1 pick", marker="BACKLOG-GROOM")
    method, path, payload = gh.writes[0]
    assert (method, path) == ("POST", "issues/42/comments")
    assert payload["body"].startswith("<!-- BACKLOG-GROOM -->\n<!-- agent-pipeline core=")
    assert "**TL;DR:** 1 pick" in payload["body"] and payload["body"].rstrip().endswith(FOOTER)
    assert (
        result["url"].endswith("issues/42/comments") and ledger.load_state()["writes"][0]["marker"] == "BACKLOG-GROOM"
    )
    with pytest.raises(writes.WriteRefused, match="at most 1"):
        writes.post(PROFILE, gh, "comment", body="again", marker="BACKLOG-GROOM")


def test_a_role_may_only_make_the_writes_its_front_matter_declares(run):
    run("backlog-groom")
    gh = FakeGitHub(hub_routes())
    with pytest.raises(writes.WriteRefused, match="may not write a pr"):
        writes.post(PROFILE, gh, "pr", body="x", head="groomed/7", title="t")
    with pytest.raises(writes.WriteRefused, match="may not write a comment"):
        writes.post(PROFILE, gh, "comment", body="x", marker="PR-EVALUATION sha=a verdict=PASS")
    with pytest.raises(writes.WriteRefused, match="hub issue #42"):
        writes.post(PROFILE, gh, "comment", body="x", marker="BACKLOG-GROOM", number=7)
    with pytest.raises(writes.WriteRefused, match="empty"):
        writes.post(PROFILE, gh, "comment", body="  \n", marker="BACKLOG-GROOM")
    assert gh.writes == []


def test_a_dry_run_prints_the_post_and_writes_nothing(run, capsys):
    run("backlog-groom", dry_run=True)
    gh = FakeGitHub(hub_routes())
    result = writes.post(PROFILE, gh, "comment", body="**TL;DR:** 1 pick", marker="BACKLOG-GROOM")
    assert gh.writes == [] and result["dry_run"] is True
    out = capsys.readouterr().out
    assert "DRY RUN: would POST repos/acme/orders-api/issues/42/comments" in out and "<!-- BACKLOG-GROOM -->" in out


def test_an_evaluation_goes_on_a_pr_only_once_per_marker(run):
    run("pr-evaluator")
    marker = "PR-EVALUATION sha=abc verdict=PASS"
    posted = comment(f"<!-- {marker} -->\n{HEADER}", app=ROUTINE)
    gh = FakeGitHub(hub_routes(**{"issues/5/comments?per_page=100": [posted]}))
    assert "already posted" in writes.post(PROFILE, gh, "comment", body="x", marker=marker, number=5)["skipped"]
    new = writes.post(PROFILE, gh, "comment", body="x", marker="PR-EVALUATION sha=def verdict=PASS", number=5)
    assert new["target"] == "comment on #5"
    with pytest.raises(writes.WriteRefused, match="is an issue"):
        writes.post(PROFILE, gh, "comment", body="x", marker="PR-EVALUATION sha=g verdict=PASS", number=7)


def test_a_gate_skip_is_said_once_until_the_gate_changes_or_a_human_replies(run):
    run("gated-implementer")
    said = comment("<!-- GATE issue=7 gate=G5 base=abc -->\nq", app=ROUTINE, at="2026-11-01T00:00:00Z")
    gh = FakeGitHub(hub_routes(**{"issues/7/comments?per_page=100": [said]}))
    assert "skipped" in writes.post(PROFILE, gh, "comment", body="q", marker="GATE issue=7 gate=G5 base=def", number=7)
    assert "skipped" not in writes.post(
        PROFILE, gh, "comment", body="q", marker="GATE issue=7 gate=G6 base=def", number=7
    )
    reply = comment("answer", at="2026-11-02T00:00:00Z")
    gh.routes["issues/7/comments?per_page=100"] = [said, reply]
    assert "skipped" not in writes.post(
        PROFILE, gh, "comment", body="q", marker="GATE issue=7 gate=G5 base=def", number=7
    )


def test_a_pr_must_come_from_the_role_prefix_and_go_into_integration(run):
    run("gated-implementer")
    gh = FakeGitHub(hub_routes())
    with pytest.raises(writes.WriteRefused, match="must start with `groomed/`"):
        writes.post(PROFILE, gh, "pr", body="x", head="feature/7", title="t")
    with pytest.raises(writes.WriteRefused, match="go into `release`"):
        writes.post(PROFILE, gh, "pr", body="x", head="groomed/7", base="master", title="t")
    writes.post(PROFILE, gh, "pr", body="Closes #7", head="groomed/7", title="fix: t")
    method, path, payload = gh.writes[-1]
    assert (method, path, payload["head"], payload["base"]) == ("POST", "pulls", "groomed/7", "release")


def test_the_release_pr_is_built_from_the_selection_and_updated_in_place(run, monkeypatch):
    run("release-manager")
    sel = {
        "role": "release-manager",
        "integration": "release",
        "production": "master",
        "ahead": 2,
        "release_pr": None,
        "title": "Release: merge release into master (2026-11-13)",
        "closes": [7],
        "commits": ["c2 fix: b"],
        "omitted": 0,
        "files_changed": "1 file changed",
        "largest": [],
    }
    monkeypatch.setattr(gates, "select_release", lambda *a: sel)
    gh = FakeGitHub(hub_routes())
    with pytest.raises(writes.WriteRefused, match="--tldr"):
        writes.post(PROFILE, gh, "release-pr")
    writes.post(PROFILE, gh, "release-pr", tldr="bin fixes")
    method, path, payload = gh.writes[-1]
    assert (method, path, payload["head"], payload["base"]) == ("POST", "pulls", "release", "master")
    assert "**TL;DR:** 2 commit(s) ahead of master — bin fixes." in payload["body"] and "Closes #7" in payload["body"]


def test_a_local_audit_without_front_matter_may_write_the_hub_body_and_its_changelog(run):
    run("audit")  # fixture's local/audit.md has no front matter
    gh = FakeGitHub(hub_routes())
    writes.post(PROFILE, gh, "hub-body", body="**TL;DR:** 3 weak")
    method, path, payload = gh.writes[-1]
    assert (method, path) == ("PATCH", "issues/42") and payload["body"].startswith("<!-- ORDERS-AUDIT-MASTER -->\n")
    writes.post(PROFILE, gh, "comment", body="moved", marker="AUDIT-CHANGELOG")
    with pytest.raises(writes.WriteRefused):
        writes.post(PROFILE, gh, "pr", body="x", head="groomed/1", title="t")


def loop_profile():
    """The release fixture plus ci-doctor's keys and routine, as upstream's loops need them."""
    import copy

    profile = copy.deepcopy(PROFILE)
    profile["ci"]["autofix"] = {"prefix": "ci-fix/", "max_attempts": 3, "max_open": 2}
    profile["ci"]["watch"] = ["ci.yml"]
    profile["routines"].append(
        {"key": "ci-doctor", "role": "ci-doctor", "status": "active", "cron": "0 1 * * 1-5", "model": "m"}
    )
    return profile


def test_a_groom_proposal_is_an_issue_with_its_label_read_back(run):
    run("backlog-groom")
    created = {"number": 51, "html_url": "https://github.com/acme/orders-api/issues/51"}
    gh = FakeGitHub({**hub_routes(), ("POST", "issues"): created, "issues/51": {"labels": []}})
    result = writes.post(PROFILE, gh, "issue", body="- **Why implement:** …", title="Bin stalls with no message")
    method, path, payload = gh.writes[-1]
    assert (method, path, payload["labels"], payload["title"]) == (
        "POST",
        "issues",
        ["groom-proposed"],
        "Bin stalls with no message",
    )
    assert result["labelled"] is False, "a token without push access drops labels silently, so the read-back says so"
    gh.routes["issues/52"] = {"labels": [{"name": "groom-proposed"}]}
    gh.routes[("POST", "issues")] = {"number": 52, "html_url": "u"}
    assert writes.post(PROFILE, gh, "issue", body="x", title="Second")["labelled"] is True


def test_ci_doctor_opens_one_issue_per_signature_and_its_pr_head_comes_from_the_profile(run_dir):
    profile = loop_profile()
    ledger.begin(profile, "ci-doctor")
    marker = "CI-DOCTOR sig=ci.yml::tests/test_a.py::test_b"
    open_issue = {"number": 9, "html_url": "u9", "performed_via_github_app": ROUTINE, "body": f"<!-- {marker} -->\nx"}
    gh = FakeGitHub(hub_routes(**{"issues?labels=ci-failure&state=open&per_page=100": [open_issue]}))
    assert "already open: #9" in writes.post(profile, gh, "issue", body="x", title="t", marker=marker)["skipped"]
    with pytest.raises(writes.WriteRefused, match="must start with `ci-fix/`"):
        writes.post(profile, gh, "pr", body="Closes #9", head="groomed/9", title="fix: t")
    writes.post(profile, gh, "pr", body="Closes #9", head="ci-fix/9-flaky-clock", title="fix: t")
    assert gh.writes[-1][2]["head"] == "ci-fix/9-flaky-clock"


def test_a_pr_body_rewrite_is_for_the_roles_own_open_pr_only(run_dir):
    profile = loop_profile()
    ledger.begin(profile, "ci-doctor")
    gh = FakeGitHub(hub_routes(**{"pulls/3": {"head": {"ref": "feature/x"}, "state": "open"}}))
    with pytest.raises(writes.WriteRefused):  # ci-doctor declares no pr-body write at all
        writes.post(profile, gh, "pr-body", body="x", number=3)


def test_the_hub_body_is_refused_over_its_budget_before_github_would_lose_the_rewrite(run):
    run("audit")
    gh = FakeGitHub(hub_routes())
    with pytest.raises(writes.WriteRefused, match="budget"):
        writes.post(PROFILE, gh, "hub-body", body="x" * (writes.HUB_BUDGET + 1))
    assert gh.writes == []
