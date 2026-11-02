"""The hub body is a fixed container: GitHub refuses an issue body over 65,536 codepoints.

The cap is real but undocumented on the endpoint, so a run meets it as a lost write, not as a warning. The contract
therefore has to carry the number, a budget strictly under it, and — the part that actually matters — which sections
may never be the ones that move, because backlog-groom parses `Enhancement suggestions` out of the body.
"""

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
CONTRACT = (CORE / "hub-contract.md").read_text()
GITHUB_BODY_CAP = 65536


def budget() -> int:
    """The codepoint budget the contract tells an audit to stay under."""
    section = CONTRACT.split("## Size", 1)[-1].split("\n## ", 1)[0]
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\*\*([\d,]{4,})\*\*", section)]
    under_cap = [n for n in numbers if n < GITHUB_BODY_CAP]
    assert under_cap, f"the Size section states no budget below {GITHUB_BODY_CAP}: {numbers}"
    return max(under_cap)


def test_the_contract_states_githubs_cap_and_a_budget_under_it():
    assert "## Size" in CONTRACT, "the hub contract lost its Size section"
    assert str(GITHUB_BODY_CAP) in CONTRACT
    assert budget() < GITHUB_BODY_CAP


def test_the_budget_leaves_room_for_a_run_of_growth():
    # A run that lands exactly on the budget must still have somewhere to put the next run's findings.
    assert GITHUB_BODY_CAP - budget() >= 2000


def test_the_section_backlog_groom_parses_is_never_the_one_that_moves():
    never = [line for line in CONTRACT.splitlines() if line.lstrip("- ").startswith("**Never relocate**")]
    assert never, "the Size section no longer protects any section from relocation"
    assert "Enhancement suggestions" in "\n".join(never)


def test_overflow_is_relocated_whole_and_not_summarised():
    section = CONTRACT.split("## Size", 1)[-1].split("\n## ", 1)[0]
    assert "verbatim" in section
    assert "AUDIT-CHANGELOG" in section, "overflow has no named destination"
