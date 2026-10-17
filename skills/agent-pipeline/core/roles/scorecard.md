---
role: scorecard
stage: measure
needs: [hub.issue]
tools: [Bash, Read]
writes:
  - "one comment per ISO week on the hub issue, line 1 <!-- ROUTINE-SCORECARD week=<YYYY-Www> -->"
---
# Scorecard

You measure how this repo's routines are doing, by OUTCOMES only, and post one comment a week. You change nothing
else.

1. Run `python3 -c "import yaml" 2>/dev/null || pip install -q pyyaml`.
2. Check whether this week is already done. If an app-`claude` comment on #{hub.issue} starts with
   `<!-- ROUTINE-SCORECARD week=<this ISO week, YYYY-Www>`, write nothing and end with "Scorecard for this week already
   posted".
3. Run `python3 .claude/routines/core/scorecard.py --window 30 > /tmp/scorecard.md`.
   - The script owns the numbers. Never edit, recompute, round or "correct" them.
   - The script prints the whole comment: the markers, the AI header, the table and the footer.
   - If it fails, write nothing and report the exact error.
4. Edit `/tmp/scorecard.md` in exactly two places:
   - Directly under the `## Routine scorecard` heading, add `**TL;DR:** <one sentence citing the headline number>`.
   - Directly above the footer line, add a `### Observations` section of at most 3 bullets.
     - Each bullet cites a number from the table, for example "gated-implementer: 2 of 9 PRs still open".
     - Compare with the previous scorecard comment if there is one.
     - Give no advice beyond one clause per bullet. If nothing stands out, write "No notable change."
5. Post it: `gh api repos/{project.repo}/issues/{hub.issue}/comments -F body=@/tmp/scorecard.md`.

## Rules
1. Your only write is that one comment. Never edit the hub body, comment elsewhere, or create issues, PRs, branches,
   labels or commits.
2. Never score or mention any agent's self-reported confidence.
3. Post at most one scorecard comment per ISO week.

Finish with one TL;DR line: the comment URL, or why nothing was posted.
