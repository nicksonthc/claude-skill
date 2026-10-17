"""The two core hooks, driven the way Claude Code drives them: tool-call JSON on stdin, exit 2 blocks."""

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
