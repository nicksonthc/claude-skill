"""scorecard.py: REST paging, human vs routine attribution, #redo detection, merged vs closed."""

import importlib.util
import re
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("scorecard", Path(__file__).resolve().parents[1] / "core/scorecard.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

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


def test_gh_items_flattens_pages_printed_back_to_back(monkeypatch):
    outputs = {
        "repos/o/r/pulls": '[{"n": 1}, {"n": 2}]\n[{"n": 3}]\n',
        "search/issues?q=x": '{"total_count": 3, "items": [{"n": 1}]}{"total_count": 3, "items": [{"n": 2}]}',
    }
    monkeypatch.setattr(
        sc.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=outputs[cmd[-1]], stderr=""),
    )
    assert [i["n"] for i in sc.gh_items("repos/o/r/pulls")] == [1, 2, 3]
    assert [i["n"] for i in sc.gh_items("search/issues?q=x")] == [1, 2]


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


def test_pr_items_keeps_prs_and_reverts_are_found_among_them(monkeypatch):
    items = [
        {"number": 5, "title": "fix: a", "pull_request": {}, "body": ""},
        {"number": 6, "title": "an issue", "body": ""},
        {"number": 7, "title": 'Revert "fix: a"', "pull_request": {}, "body": "Reverts o/r#5"},
    ]
    monkeypatch.setattr(sc, "gh_items", lambda path: items)
    prs = sc.pr_items("o/r")
    assert [i["number"] for i in prs] == [5, 7]
    assert sc.reverted_numbers(prs, [pr(number=5, title="fix: a")]) == {5}
