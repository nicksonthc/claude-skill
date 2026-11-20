# Calm Focused UI · `calm-focused-ui`

![calm-focused-ui demo](assets/calm-focused-ui.gif)

*The skill's demo screen, recorded from the real build: a support technician's "Service tickets" page — one
primary action, search plus one filter visible and the rest under **More filters**, one action per table row,
the ticket opening in a side sheet with its own single primary, a busy Save that lands on an inline
"why + how to fix" problem block, then the same screen in dark mode.*

Calm, simple, large UI for internal web tools used at a desk by operators, support technicians and
back-office staff, in React + Tailwind (Vue + Tailwind port notes included). One screen, one job, one
primary action — everything else one step away, never two. Ships semantic light/dark tokens (16 px body,
44 px controls, 3 : 1 control edges, focus outline), copy-paste components (Page, Button, Field, More,
Status, Sheet, Table, states) and a browser check for the numeric floors. Build only; auditing an existing
UI belongs to a separate review skill.

## Use it when
- building a new screen, page, form, table or the app's design tokens
- "make this simpler / cleaner / calmer / bigger / easier to read", "one thing at a time", "Apple-like"
- operators or technicians miss the next step, or a screen has too many buttons

## What's inside
| File | What |
|---|---|
| `SKILL.md` | the floors (numbers), the screen rules, workflow with done-criteria, pitfalls |
| `REFERENCE.md` | tokens + every component + a whole screen, exactly as built and checked; Tailwind v3 and Vue notes |
| `scripts/check-floors.mjs` | Playwright check: targets ≥ 24 / 44 px, no text < 14 px, one primary per surface |

## Works with
`ui-motion-system` (motion, skeleton shimmer) · `focused-task-flow` (bench / kiosk one-task screens) ·
`console-app-shell` (app chrome) · `keyboard-first-hotkeys` · `frontend-design` (brand direction).

## Sources
Distilled — paraphrased, nothing copied — from Apple's Human Interface Guidelines as summarised by
`emilkowalski/apple-design` (motion, press feedback, simplicity) and `dickwu/apple-design-skill`
(accessibility floors, review severity), NN/g "Progressive Disclosure" (two-level limit) and WCAG 2.2
(SC 2.5.8 target size, 1.4.3 / 1.4.11 contrast, 2.4.7 focus visible).

## Install
```bash
npx skills add nicksonthc/claude-skill@calm-focused-ui        # or symlink skills/calm-focused-ui into ~/.claude/skills
```
