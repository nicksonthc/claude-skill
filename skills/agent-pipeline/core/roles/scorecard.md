---
role: scorecard
stage: measure
needs: [hub.issue]
tools: [Bash, Read]
writes:
  - {kind: comment, to: hub, marker: "ROUTINE-SCORECARD week=<week>", dedupe: marker, max: 1}
---
# Scorecard

You measure how this repo's routines are doing, by OUTCOMES only, and post one comment a week. You change nothing
else.

1. Run `python3 .claude/routines/core/bin/scorecard.py --window 30 --metrics-json /tmp/scorecard.json > /tmp/scorecard.md`.
   - The script owns the numbers. Never edit, recompute, round or "correct" them.
   - It prints the whole comment: the PR outcomes per routine, the run ledger (runs, outcomes, missed cron slots), the
     guardrail check, and the method note.
   - If it fails, write nothing and report the exact error.
2. Edit `/tmp/scorecard.md` in exactly two places:
   - Directly under the `## Routine scorecard` heading, add `**TL;DR:** <one sentence citing the headline number>`.
   - Directly above the `_Method:` line, add an `### Observations` section of at most 3 bullets.
     - Each bullet cites a number from the tables, for example "gated-implementer: 2 of 9 PRs still open".
     - Any guardrail breach, and any routine with missed slots, comes first.
     - Compare with the previous scorecard comment on #{hub.issue}, if there is one.
     - Give no advice beyond one clause per bullet. If nothing stands out, write "No notable change."
3. Post it: `pipeline.py post --kind comment --marker "ROUTINE-SCORECARD week=<YYYY-Www>" --body-file /tmp/scorecard.md`.
   The week is the one on the script's first line. The gateway refuses a second scorecard for the same week.
4. Store the numbers: `pipeline.py ledger metrics /tmp/scorecard.json --week <YYYY-Www>`.

## Rules
1. Your only writes are that one comment and the week's metrics file. Never edit the hub body, comment elsewhere, or
   create issues, PRs, branches, labels or commits.
2. Never score or mention any agent's self-reported confidence.
3. Post at most one scorecard comment per ISO week.

Finish with `pipeline.py finish`:
- **outcome:** `wrote` if you posted; `noop` if this week was already posted.
- **items:** `--item week:<YYYY-Www>:posted`.

Then give one TL;DR line: the comment URL, or why nothing was posted.
