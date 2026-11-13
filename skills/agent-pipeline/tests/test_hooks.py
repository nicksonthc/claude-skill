"""The core's PreToolUse hooks, driven the way Claude Code drives them: tool-call JSON on stdin, exit 2 blocks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "core" / "hooks"


def run_hook(cmd: list[str], payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, env={**os.environ, **env})


@pytest.fixture
def repo(tmp_path):
    """A repo with the vendored push guard, a release/master profile, on branch groomed/1-fix."""
    root = tmp_path / "repo"
    hooks = root / ".claude/routines/core/hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOKS / "push-guard.py", hooks / "push-guard.py")
    (root / ".claude/routines/pipeline.yml").write_text("branches: {integration: release, production: master}\n")
    subprocess.run(["git", "init", "-q", "-b", "groomed/1-fix", str(root)], check=True)
    return root


def guard(repo: Path, command: str, remote: str = "true") -> int:
    script = repo / ".claude/routines/core/hooks/push-guard.py"
    env = {"CLAUDE_CODE_REMOTE": remote} if remote else {"CLAUDE_CODE_REMOTE": ""}
    payload = {"tool_input": {"command": command}, "cwd": str(repo)}
    return run_hook(["python3", str(script)], payload, env).returncode


@pytest.mark.parametrize(
    "command, code",
    [
        ("git push origin HEAD:release", 2),
        ("git push origin release", 2),
        ("git push origin HEAD:refs/heads/master", 2),
        ("git status && git push -u origin HEAD:release", 2),
        ("git push --force origin groomed/1-fix", 2),
        ("git push -uf origin groomed/1-fix", 2),
        ("git push origin +groomed/1-fix", 2),
        ("git push origin :groomed/1-fix", 2),
        ("git push --delete origin groomed/1-fix", 2),
        ("git push --all origin", 2),
        ("git push -u origin groomed/1-fix", 0),
        ("git push origin HEAD:groomed/1-fix", 0),
        ("git push origin HEAD", 0),
        ("git push", 0),
        ("git -C /tmp/x push -o ci.skip origin groomed/2-y", 0),
        ('echo "git push origin release"', 0),
        ("git status", 0),
    ],
)
def test_push_guard_in_a_cloud_session(repo, command, code):
    assert guard(repo, command) == code


def test_push_guard_blocks_a_bare_push_from_a_protected_branch(repo):
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "release"], check=True)
    assert guard(repo, "git push") == 2
    assert guard(repo, "git push origin HEAD") == 2


def test_push_guard_leaves_local_sessions_alone(repo):
    assert guard(repo, "git push --force origin HEAD:release", remote="") == 0


def test_push_guard_falls_back_to_main_and_master_without_a_profile(repo):
    (repo / ".claude/routines/pipeline.yml").unlink()
    assert guard(repo, "git push origin HEAD:main") == 2
    assert guard(repo, "git push origin HEAD:release") == 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="require-ai-marker.sh needs jq")
@pytest.mark.parametrize(
    "body, code",
    [
        (
            "> 🤖 **AI-generated** · Claude Code\n\nhi\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)",
            0,
        ),
        (
            "<!-- X -->\n> 🤖 **AI-generated** · Claude Code\nhi\n🤖 Generated with [Claude Code](https://claude.com/claude-code)",
            0,
        ),
        ("hi\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)", 2),
        ("> 🤖 **AI-generated** · Claude Code\nhi", 2),
    ],
)
def test_marker_hook_checks_body_files_posted_through_gh_api(tmp_path, body, code):
    body_file = tmp_path / "body.md"
    body_file.write_text(body)
    command = f"gh api repos/o/r/issues/1/comments -F body=@{body_file}"
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}
    result = run_hook([str(HOOKS / "require-ai-marker.sh")], payload, {"CLAUDE_PROJECT_DIR": ""})
    assert result.returncode == code


@pytest.fixture
def vendored(tmp_path):
    """A repo with the vendored write guard and a profile for acme/orders-api (release → master)."""
    hooks = tmp_path / ".claude/routines/core/hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOKS / "write-guard.py", hooks / "write-guard.py")
    (tmp_path / ".claude/routines/pipeline.yml").write_text(
        "project: {repo: acme/orders-api}\nbranches: {integration: release, production: master}\n"
    )
    (tmp_path / "hub.md").write_text("The bin state: closed. Approve by adding the label groomed.\n")
    return tmp_path


def write_guard(root: Path, tool: str, tool_input: dict, remote: str = "true") -> int:
    script = root / ".claude/routines/core/hooks/write-guard.py"
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(root)}
    return run_hook(["python3", str(script)], payload, {"CLAUDE_CODE_REMOTE": remote}).returncode


API = "gh api"  # spelled once, so the test table reads as data


@pytest.mark.parametrize(
    "command, code",
    [
        (f"{API} -X PUT repos/acme/orders-api/pulls/5/merge", 2),
        (f"cd x && {API} repos/{{owner}}/{{repo}}/pulls/5/merge -X PUT", 2),
        (f"{API} repos/acme/orders-api/pulls/5/reviews -f event=APPROVE", 2),
        (f"{API} repos/acme/orders-api/pulls/5/reviews -f event=COMMENT", 2),
        (f"{API} -X PATCH repos/acme/orders-api/issues/5 -f state=closed", 2),
        (f"{API} -X PATCH repos/acme/orders-api/pulls/5 -F state=open", 2),
        (f'{API} -X PATCH repos/acme/orders-api/issues/5 --input - <<\'EOF\'\n{{"state": "closed"}}\nEOF', 2),
        (f"{API} repos/acme/orders-api/issues/7/labels -f 'labels[]=groomed'", 2),
        ("gh issue edit 7 --add-label groomed", 2),
        ("gh pr merge 5 --squash", 2),
        (f"{API} -X DELETE repos/acme/orders-api/git/refs/heads/groomed/7", 2),
        (f"{API} -X PATCH repos/acme/orders-api/git/refs/heads/release -f sha=abc", 2),
        (f"{API} -X PUT repos/acme/orders-api/rulesets/1 --input r.json", 2),
        (f"{API} -X PATCH repos/acme/orders-api -f default_branch=x", 2),
        (f"{API} repos/other/repo/issues/1/reactions -f content=heart", 2),
        (f"GH_PAGER= {API} -X POST user/repos -f name=x", 2),
        (f"{API} repos/acme/orders-api/issues/7/labels -f 'labels[]=bug'", 0),
        (f"{API} -X PATCH repos/acme/orders-api/issues/42 -F text=@HUB", 0),
        (f"{API} repos/acme/orders-api/pulls/5", 0),
        (f"{API} repos/other/repo/contents/README.md", 0),
        (f'echo "{API} -X PUT repos/acme/orders-api/pulls/5/merge"', 0),
        (
            "python3 .claude/routines/core/bin/pipeline.py post --kind comment --marker BACKLOG-GROOM --body-file b.md",
            0,
        ),
        ("git push origin HEAD:groomed/7", 0),
    ],
)
def test_write_guard_blocks_what_no_routine_may_do_and_nothing_else(vendored, command, code):
    command = command.replace("@HUB", f"@{vendored / 'hub.md'}")
    assert write_guard(vendored, "Bash", {"command": command}) == code


@pytest.mark.parametrize(
    "tool, tool_input, code",
    [
        ("mcp__github__merge_pull_request", {"owner": "acme", "repo": "orders-api", "pullNumber": 5}, 2),
        ("mcp__github__create_pull_request_review", {"owner": "acme", "repo": "orders-api", "event": "APPROVE"}, 2),
        ("mcp__github__update_issue", {"owner": "acme", "repo": "orders-api", "issue_number": 5, "state": "closed"}, 2),
        ("mcp__github__issue_write", {"owner": "acme", "repo": "orders-api", "labels": ["groomed"]}, 2),
        ("mcp__github__add_issue_comment", {"owner": "other", "repo": "repo"}, 2),
        ("mcp__github__add_issue_comment", {"owner": "acme", "repo": "orders-api"}, 0),
        ("mcp__github__get_pull_request", {"owner": "other", "repo": "repo"}, 0),
    ],
)
def test_write_guard_applies_the_same_rules_to_github_mcp_tools(vendored, tool, tool_input, code):
    assert write_guard(vendored, tool, tool_input) == code


def test_write_guard_leaves_local_sessions_alone(vendored):
    command = f"{API} -X PUT repos/acme/orders-api/pulls/5/merge"
    assert write_guard(vendored, "Bash", {"command": command}, remote="") == 0


def test_a_new_issue_may_carry_a_proposal_label_but_never_the_approval(vendored):
    new = f"{API} repos/acme/orders-api/issues -f title=t"
    assert write_guard(vendored, "Bash", {"command": f"{new} -f 'labels[]=groom-proposed'"}) == 0
    assert write_guard(vendored, "Bash", {"command": f"{new} -f 'labels[]=groomed'"}) == 2


def test_pipeline_rnds_upstream_repo_is_the_one_other_repo_a_routine_may_write(vendored):
    profile = vendored / ".claude/routines/pipeline.yml"
    profile.write_text(profile.read_text() + "rnd: {upstream: acme/claude-skill}\n")
    upstream_pr = f"{API} repos/acme/claude-skill/pulls -f head=rnd/pipeline-2026-W46 -f base=main"
    assert write_guard(vendored, "Bash", {"command": upstream_pr}) == 0
    assert write_guard(vendored, "Bash", {"command": f"{API} -X PUT repos/acme/claude-skill/pulls/3/merge"}) == 2
    assert write_guard(vendored, "Bash", {"command": f"{API} repos/acme/elsewhere/pulls -f head=x"}) == 2
