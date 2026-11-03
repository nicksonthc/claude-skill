"""backlog-groom proposes; only a human approves. The proposal issue never carries its own approval."""

from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
GROOM = (CORE / "roles" / "backlog-groom.md").read_text()
HUB = (CORE / "hub-contract.md").read_text()


def test_the_groomer_opens_one_labelled_proposal_per_pick():
    assert "groom-proposed" in GROOM
    assert "at most one issue per pick, so at most 3 per run" in GROOM.lower()
    # labels are silently dropped without push access, so the issue is read back
    assert "Read it back" in GROOM


def test_the_groomer_never_approves_its_own_proposal():
    assert "Never add `groomed`" in GROOM
    assert "Never create a PR, branch,\n   label or commit" in GROOM
    assert "an approver adds\n`groomed`" in GROOM


def test_the_proposal_body_is_the_requirement_and_the_title_path_survives():
    assert "that body is the requirement" in HUB
    assert "Convert to issue" in HUB  # the fallback for a hand-converted task line
    assert "the only link back" in HUB
