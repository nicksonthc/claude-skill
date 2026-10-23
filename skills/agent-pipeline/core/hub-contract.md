# Hub issue contract

Issue #{hub.issue} is this repo's **hub**. An audit routine owns its body. backlog-groom, gated-implementer and
scorecard post their comments there. Any local audit routine must produce the body below, because backlog-groom
parses it.

## Body
The audit rewrites the whole body on every run, in this order:
1. Line 1 is `{hub.marker}`, line 2 is the provenance marker, then the AI header (`core/shared.md`).
2. `**TL;DR:** <counts per grade> — <n> new, <m> resolved this run; top fix: <rank-1 enhancement>`.
3. `Last updated:` the UTC time, plus the commit SHA of every repo the audit read.
4. A scoreboard table. The audit's prompt defines the columns.
5. One or more findings sections. The audit's prompt names them. Each finding is one line:
   `- [ ] **<grade>** - <area> - <step> - <what breaks for the user> - grounding: <file:line> - fix: <one line>`
6. A section whose heading starts with `Enhancement suggestions`. It is a ranked list, highest user impact first,
   and each item names its repo. backlog-groom reads this list.
7. A section whose heading starts with `Verified closed`, inside `<details>`. Each entry names the commit that fixed it.
8. A `Removed this run` line for every finding dropped this run, with the reason.

## Rules
- Edit #{hub.issue} in place. If it is closed or missing, stop and report. The skill's *install* creates the hub, and
  you never open a second one. `{hub.legacy_markers}` are older spellings of the same marker: replace one with
  `{hub.marker}` when you rewrite the body.
- Preserve human input. A ticked checkbox stays ticked while its finding still exists. A finding that is now fixed
  moves to Verified closed with the fixing commit. A finding you drop goes under Removed this run with the reason.
- Every grade carries the `file:line` you read this run. A grade you cannot verify is `unverified`, together with
  what you would need to read.
- Comment only when something moved: a new finding, a resolved one, or a changed grade. Post one comment with line 1
  `<!-- AUDIT-CHANGELOG -->`, a TL;DR naming what moved, then one bullet per change. A run where nothing moved posts
  nothing.
- Prefer fewer real findings over a long speculative list. An ungrounded grade is worse than no grade.

## Groom items
A human approves a groom item with "Convert to issue", which makes an issue whose title is the item's task line and
whose body is empty. The groom-key never reaches the issue, so the title is the only link back. gated-implementer and
pr-evaluator find an empty-bodied issue's groom item this way:
1. **Normalise** a title: remove every `**`, cut from the first ` — score` to the end (older groom lines carried the
   score there), and trim the whitespace.
2. **Search** the app-`claude` comments on #{hub.issue} whose line 1 is `<!-- BACKLOG-GROOM -->`, newest first. The
   item is the first task line (`- [ ]` or `- [x]`) whose normalised text equals the issue's normalised title, or
   whose text is `#<N>`. It runs to the next task line or the next line starting `**`.
3. **Use it.** Its **Acceptance criteria** are the requirement; its **Trace** and **Failing test to add** are where
   the work starts. Cite the groom comment's URL wherever you state the requirement. An audit finding with a similar
   title is never the requirement.
4. **No match** (the title was edited, or the item never existed) means no requirement: say so, and ask a human to
   paste the acceptance criteria into the issue body.

A non-empty issue body written by a human is the requirement, and the groom item is only background.
