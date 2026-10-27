"""`gh api --paginate` is unusable behind the Claude Code GitHub proxy, so nothing in the core reaches for it.

`gh` follows the response's `Link: rel="next"`, which GitHub writes in the numeric-ID form `repositories/{id}/…`,
and the proxy refuses that form with a 403. Page 1 still prints, so the failure only appears once a list outgrows
`per_page` — silently, in whichever routine reads the longest list.
"""

from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
SHARED = (CORE / "shared.md").read_text()


def test_the_scorecard_never_passes_paginate_to_gh():
    assert '"--paginate"' not in (CORE / "scorecard.py").read_text()


def test_no_command_in_the_rest_table_uses_paginate():
    rows = [line for line in SHARED.splitlines() if line.startswith("|")]
    assert rows, "the REST cheat-sheet table went missing"
    assert not [line for line in rows if "--paginate" in line]


def test_the_rest_section_says_how_to_page_instead():
    assert "Never `--paginate`" in SHARED
    assert "add `&page=<n>` and repeat until a page comes back with fewer than `per_page` entries" in SHARED
