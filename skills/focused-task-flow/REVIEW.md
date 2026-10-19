# Focused Task Flow — review rubric

For auditing an existing operator / kiosk / station screen. Work from the real
screen, not the code alone: run the app, open a subject at each state the screen
has, and capture it (headless Chrome over CDP, Playwright, or the browser tool)
at the terminal's real resolution and at a phone width.

**Done when** every check below has a verdict (pass / partial / fail) backed by
a screenshot or a `file:line`, and the findings are ranked.

## Capture set

1. Idle (nothing open, the scan / start box).
2. Loaded, not started (the start action).
3. A live step — one with a typed/scanned field, one with a picked verdict.
4. A client-side rejection (a mismatched scan).
5. A server refusal (a wrong-place subject, a full batch, a duplicate part).
6. Ready to finish, and the completed state.
7. The same live step at phone width.

## Checks

| # | Check | Pass when | How to look |
|---|---|---|---|
| 1 | **The question** | The live instruction is the largest text in the content area and reads as a verb + object | screenshot; scaled to 50 %, still readable |
| 2 | **One primary** | Exactly one enabled primary in every state; nothing grey-and-big competing with it | count `[data-primary]:not(:disabled)` per state |
| 3 | **Focus lands right** | After every transition `document.activeElement` is the next input or the primary | evaluate `document.activeElement` after each step |
| 4 | **Bench size** | Inputs ≥ 48 px, primary ≥ 72 px (≥ 88 px touch-first), every tappable ≥ 44 px, prompt ≥ 28 px | computed heights |
| 5 | **Clutter** | Done and locked steps are one line each; nav/rail/meta are small and above | screenshot |
| 6 | **State language** | Every state has icon + word + colour; no colour-only signal | screenshot in greyscale |
| 7 | **Client rejection** | Inline, says what was expected, keeps the bad value selected for re-scan, blocks submit | capture 4 |
| 8 | **Server refusal** | Inline under the live step with why + how; not only a corner toast | capture 5; grep the action wrapper's `catch` |
| 9 | **Bench words** | No ids, enum names or stack text in what operators read | grep backend `HTTPException(` / raise strings |
| 10 | **Recovery** | The next normal action (re-scan, re-press) clears the problem; nothing to dismiss | repeat capture 4/5 then fix |
| 11 | **Busy** | Spinner + disabled within one frame; double Enter fires once | press Enter twice quickly; count requests |
| 12 | **Way out** | Every dead-end state (wrong place, on hold, unknown) has a focused exit | capture 5; `activeElement` |
| 13 | **Sound** | Success and blocking-error cues exist, own actions only, mutable per terminal | grep `AudioContext` / audio |
| 14 | **Verdicts** | Picked values don't dead-end the Enter chain; no verdict is ever autofocused | ST-style gate step |
| 15 | **Narrow screen** | Live step visible without scrolling past context; nothing floats over the primary | capture 7 |
| 16 | **Others' changes** | Another operator's update names them, stays silent, and doesn't move focus | read the socket handler |

## Report

Rank findings by **bench impact**: (1) can cause a wrong record, (2) stops the
flow, (3) slows every unit, (4) polish. For each: the check number, what was
seen (screenshot / `file:line`), and the fix from `REFERENCE.md`. List what
already passes, briefly — it is what the next change must not break.
