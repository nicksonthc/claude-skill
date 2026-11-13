"""scorecard.py: human vs routine attribution, #redo detection, merged vs closed, the run ledger and guardrails."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import scorecard as sc
from conftest import load_profile

APPROVERS = {"alice"}
ROUTINE = {"slug": "claude"}


def post(login, body, created="2026-10-01T02:00:00Z", app=None):
    return {"user": {"login": login}, "body": body, "created_at": created, "performed_via_github_app": app}


def pr(**over):
    base = {
        "number": 1,
        "title": "t",
        "head": "groomed/1-x",
        "base": "release",
        "state": "open",
        "created_at": "2026-10-01T00:00:00Z",
        "merged_at": None,
        "author": "alice",
        "by_routine": True,
        "commits": ["2026-10-01T00:01:00Z"],
        "comments": [],
        "reviews": [],
    }
    return {**base, **over}


def serve(monkeypatch, outputs: dict) -> list[str]:
    """Answer each `gh api <path>` from `outputs`, and record the paths asked for."""
    asked: list[str] = []

    def run(cmd, **kw):
        asked.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, stdout=outputs[cmd[-1]], stderr="")

    monkeypatch.setattr(sc.subprocess, "run", run)
    return asked


def test_gh_items_walks_page_n_and_stops_on_a_short_page(monkeypatch):
    asked = serve(
        monkeypatch,
        {
            "repos/o/r/pulls?per_page=2&page=1": '[{"n": 1}, {"n": 2}]',
            "repos/o/r/pulls?per_page=2&page=2": '[{"n": 3}]',
            "search/issues?q=x&per_page=1&page=1": '{"total_count": 2, "items": [{"n": 1}]}',
            "search/issues?q=x&per_page=1&page=2": '{"total_count": 2, "items": []}',
        },
    )
    assert [i["n"] for i in sc.gh_items("repos/o/r/pulls?per_page=2")] == [1, 2, 3]
    assert [i["n"] for i in sc.gh_items("search/issues?q=x&per_page=1")] == [1]
    assert asked[:2] == ["repos/o/r/pulls?per_page=2&page=1", "repos/o/r/pulls?per_page=2&page=2"]


def test_gh_pages_asks_once_for_a_single_object(monkeypatch):
    asked = serve(monkeypatch, {"repos/o/r/pulls/7?page=1": '{"number": 7}'})
    assert sc.gh_pages("repos/o/r/pulls/7") == [{"number": 7}]
    assert asked == ["repos/o/r/pulls/7?page=1"]


def test_a_redo_line_below_the_feedback_counts():
    feedback = post("alice", "You mentioned the bin empties first.\nPlease cover that case.\n\n#redo")
    assert sc.redo_requests(pr(comments=[feedback]), APPROVERS) == [feedback]


def test_redo_from_a_routine_or_a_non_approver_does_not_count():
    comments = [post("alice", "#redo now", app=ROUTINE), post("mallory", "#redo please")]
    assert sc.redo_requests(pr(comments=comments), APPROVERS) == []


def test_done_replies_count_the_marker_and_the_legacy_words():
    comments = [
        post("alice", "<!-- REDO-DONE for=5 sha=abc status=done -->\n> 🤖 **AI-generated** · Claude Code", app=ROUTINE),
        post("alice", "<!-- REDO-DONE for=6 sha=none status=ask -->", app=ROUTINE),
        post("alice", "done redo · **TL;DR:** fixed", app=ROUTINE),
    ]
    assert sc.redo_replies(pr(comments=comments)) == 2


def test_closed_unmerged_uses_merged_at_because_rest_closed_includes_merged():
    merged = sc.pr_facts(pr(state="closed", merged_at="2026-10-02T00:00:00Z"), APPROVERS)
    closed = sc.pr_facts(pr(state="closed"), APPROVERS)
    assert (merged["merged"], merged["closed_unmerged"]) == (True, False)
    assert (closed["merged"], closed["closed_unmerged"]) == (False, True)


def test_the_owner_reviewing_a_routine_pr_is_a_human_touch_but_not_on_their_own_pr():
    owner_comment = post("alice", "looks right", created="2026-10-01T03:00:00Z")
    on_routine_pr = sc.pr_facts(pr(by_routine=True, comments=[owner_comment]), APPROVERS)
    on_own_pr = sc.pr_facts(pr(by_routine=False, comments=[owner_comment]), APPROVERS)
    assert on_routine_pr["review_hours"] == 3.0
    assert on_own_pr["review_hours"] is None


def test_routine_and_bot_posts_are_not_a_human_touch():
    comments = [post("alice", "evaluation", app=ROUTINE), post("coderabbitai[bot]", "summary")]
    assert sc.pr_facts(pr(comments=comments), APPROVERS)["review_hours"] is None


def test_first_pass_needs_a_merge_with_no_late_push_and_no_redo():
    clean = pr(state="closed", merged_at="2026-10-02T00:00:00Z")
    late_push = {**clean, "commits": ["2026-10-01T00:01:00Z", "2026-10-01T05:00:00Z"]}
    assert sc.pr_facts(clean, APPROVERS)["first_pass"] is True
    assert sc.pr_facts(late_push, APPROVERS)["first_pass"] is False


def test_no_search_endpoint_because_cloud_sessions_refuse_it():
    assert not re.search(r"[\"']search/", Path(sc.__file__).read_text())


def test_pr_items_keeps_prs_updated_in_the_window_and_reverts_are_found_among_them(monkeypatch):
    items = [
        {"number": 5, "title": "fix: a", "pull_request": {}, "body": ""},
        {"number": 6, "title": "an issue", "body": ""},
        {"number": 7, "title": 'Revert "fix: a"', "pull_request": {}, "body": "Reverts o/r#5"},
    ]
    asked = []
    monkeypatch.setattr(sc, "gh_items", lambda path: asked.append(path) or items)
    prs = sc.pr_items("o/r", datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert asked == ["repos/o/r/issues?state=all&per_page=100&since=2026-10-14T00:00:00Z"]
    assert [i["number"] for i in prs] == [5, 7]
    assert sc.reverted_numbers(prs, [pr(number=5, title="fix: a")]) == {5}


def test_core_bin_never_calls_search_or_graphql_subcommands():
    for path in (Path(sc.__file__).parent).glob("*.py"):
        text = path.read_text()
        assert not re.search(r"[\"']search/", text), path.name
        assert not re.search(r"[\"']gh[\"'],\s*[\"'](pr|issue)[\"']", text), path.name


def run(routine, started, outcome="noop", ended=None, dry_run=False):
    return {
        "routine": routine,
        "session": started,
        "started_at": started,
        "ended_at": ended or started,
        "outcome": outcome,
        "dry_run": dry_run,
    }


def test_the_ledger_section_counts_outcomes_and_cron_slots_with_no_run():
    profile = load_profile()  # pr-evaluator cron "0 2,5,8 * * *"; scorecard "30 1 * * 1"
    since, now = datetime(2026, 11, 10, tzinfo=timezone.utc), datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
    records = [
        run("pr-evaluator", "2026-11-10T02:01:00Z", "wrote", "2026-11-10T02:11:00Z"),
        run("pr-evaluator", "2026-11-10T05:02:00Z"),
        run("pr-evaluator", "2026-11-11T02:00:30Z", "failed"),
        run("pr-evaluator", "2026-11-11T05:00:00Z", dry_run=True),
    ]
    lines, data = sc.ledger_section(profile, records, since, now)
    evaluator = data["pr-evaluator"]
    assert (evaluator["runs"], evaluator["wrote"], evaluator["noop"], evaluator["failed"]) == (3, 1, 1, 1)
    # slots from the first record (11-10 02:01) to now − 90 min (11-11 07:30): 11-10 05, 08 · 11-11 02, 05.
    # 11-10 08 has no run, and the only run near 11-11 05 is a DRY RUN, so 2 are missed.
    assert evaluator["missed_slots"] == 2
    assert any(line.startswith("| pr-evaluator | 3 | 1 | 1 | 0 | 1 | 2 |") for line in lines)
    assert sc.ledger_section(profile, [], since, now)[0][0].startswith("_No run records yet")


def test_a_merge_or_close_made_through_the_claude_app_is_a_guardrail_breach():
    by_app = {"event": "merged", "performed_via_github_app": {"slug": "claude"}}
    by_human = {"event": "closed", "performed_via_github_app": None}
    labelled = {"event": "labeled", "performed_via_github_app": {"slug": "claude"}}
    assert sc.pr_breaches([pr(number=3, events=[by_app, by_human, labelled])]) == ["#3 merged"]
