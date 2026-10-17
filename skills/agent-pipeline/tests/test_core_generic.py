"""The core must stay generic: no project's nouns may leak into it."""

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
# Nouns from the repos this pipeline was harvested from and first runs on. A hit means a fact belongs in a profile.
PROJECT_NOUNS = re.compile(r"\b(micron|mms|lmms|plc|pingspace|penta\w*|nicksonthc|mediq|shopfloor|#?189)\b", re.I)


def core_files():
    return [p for p in sorted(CORE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]


def test_core_has_no_project_nouns():
    hits = [
        f"{path.relative_to(CORE)}:{n}: {m.group(0)}"
        for path in core_files()
        for n, line in enumerate(path.read_text().splitlines(), 1)
        for m in PROJECT_NOUNS.finditer(line)
    ]
    assert hits == []


def test_every_post_carries_the_shared_header_and_nothing_uses_graphql_subcommands():
    for path in (CORE / "roles").glob("*.md"):
        text = path.read_text()
        # scorecard.py prints its own header lines; every other role takes them from shared.md
        assert "core/shared.md" in text or path.stem == "scorecard", path.name
    script = (CORE / "scorecard.py").read_text()
    assert "> 🤖 **AI-generated** · Claude Code" in script and "Generated with [Claude Code]" in script
    # prompts only: shared.md names the subcommands once, to forbid them
    for path in [p for p in core_files() if p.suffix == ".md" and p.name != "shared.md"]:
        assert not re.search(r"\bgh (pr|issue) (list|view|create|comment|edit|checks|diff)\b", path.read_text()), path
