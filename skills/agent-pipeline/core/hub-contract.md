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

## Size
The body is a fixed container with a producer that only grows. GitHub caps an issue body at **65,536 codepoints**
and answers a longer PATCH with `422 Validation failed: Body is too long (maximum is 65536 characters)`. The
endpoint's own reference documents no limit, so a run meets the cap for the first time as a failed write that loses
the whole rewrite. A comment is the larger container — up to 262,144 bytes — which is why overflow moves into one.

- **Measure before you write.** Count the codepoints of the body you assembled. Above **60,000**, relocate until it
  fits: that floor leaves one run's growth of headroom, and a body already over it is relocated this run, not next.
- **Relocate, never truncate.** What does not fit moves **verbatim** into this run's `<!-- AUDIT-CHANGELOG -->`
  comment, and the body keeps a one-line pointer naming the section and linking that comment. Relocating is not
  dropping: a finding you actually drop still belongs under `Removed this run` with its reason.
- **Eviction order**, from the back: `Verified closed` (7) first, then the oldest carried findings of the lowest
  grade in the findings sections (5).
- **Never relocate** sections 1-4 or **6**. backlog-groom parses `Enhancement suggestions` out of the **body**, and
  1-3 are how every reader identifies the hub; move either and the next groom run reads a hub that looks empty.
- **Say what moved** in the change-log comment, so the next audit run and backlog-groom can find it again.

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
backlog-groom opens one `groom-proposed` issue per pick: its title is the item's task line and its body is the item
itself, groom-key included. A human approves it by adding `groomed`, and that body is the requirement.

A human may instead approve the task line itself with "Convert to issue", which makes an issue whose title is that
line and whose body is empty. The groom-key never reaches such an issue, so the title is the only link back.
gated-implementer and pr-evaluator find an empty-bodied issue's groom item this way:
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

A non-empty issue body is the requirement — whether a human wrote it or backlog-groom did — and a groom item found
by title is then only background.
