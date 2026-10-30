"""The Claude Code GitHub proxy serves only `repos/<owner>/<repo>/…` paths, so nothing in the core reaches past them.

Every other path form — `search/…`, `orgs/…`, `notifications` — comes back 403 ("sessions are bound to their
configured repositories. Use repository-scoped endpoints"). The refusal is about the path, not the credential, so a
role that copies such a command from the core loses the step whatever token it holds.
"""

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
SHARED = (CORE / "shared.md").read_text()
# `gh api <path>`, with or without quotes, as the prompts and the scorecard spell it
GH_API_PATH = re.compile(r"""gh api\s+(?:-X\s+\w+\s+)?["']?/?([A-Za-z_][\w./{}-]*)""")
SERVED_ELSEWHERE = ("repos/", "user", "rate_limit")


def core_texts():
    return {
        p.relative_to(CORE): p.read_text()
        for p in sorted(CORE.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def test_no_core_file_reaches_a_path_the_proxy_refuses():
    hits = [
        f"{name}: gh api {m.group(1)}"
        for name, text in core_texts().items()
        for m in GH_API_PATH.finditer(text)
        if not m.group(1).startswith(SERVED_ELSEWHERE)
    ]
    assert hits == []


def test_the_rest_section_says_why_and_what_to_do_instead():
    assert "Only `repos/<owner>/<repo>/…` paths, for a repo attached to the session." in SHARED
    assert "no text search" in SHARED
    rows = [line for line in SHARED.splitlines() if line.startswith("|")]
    assert rows, "the REST cheat-sheet table went missing"
    assert [line for line in rows if line.startswith("| find an issue or PR by text")]
