---
name: calm-focused-ui
description: Build calm, simple, large, one-job-per-screen UI for a React + Tailwind (or Vue + Tailwind) web app used at a desk by operators, support technicians and back-office staff — design tokens (16 px body, 44 px controls, semantic light/dark colours, focus outline), a page anatomy with exactly one primary action, progressive disclosure capped at two levels, single-column forms with fix-it errors, technician tables with one visible row action, side-sheet details, honest loading / empty / problem states, and a browser check for the numeric floors. Use when building a new screen, page, form, table or design system, or when asked to make a UI simpler, cleaner, calmer, less cluttered, easier to read, bigger, "Apple-like", "one thing at a time", or more usable for operators and technicians.
---

# Calm Focused UI

The base layer for internal web tools: what every screen looks like before any special flow is added.
Distilled from Apple's HIG floors (via the `emilkowalski/apple-design` and `dickwu/apple-design-skill`
skills, paraphrased, nothing copied), NN/g progressive disclosure and WCAG 2.2; proven on Vite 6 ·
React 19 · Tailwind 4.3 · lucide-react with a demo that passes `scripts/check-floors.mjs` in every state.
Building only — auditing an existing UI is a separate review skill.

## The idea in one line

**One screen, one job, one primary action — everything else one step away, never two.**
A technician glances at the screen and knows what it is for and what the next click is; the rarer
options exist, folded, under a label that says what's inside.

## Floors (numbers, not adjectives)

| What | Floor |
|---|---|
| Body text | 16 px (`text-body`); 14 px (`text-meta`) only for metadata, hints, table heads; nothing smaller |
| Controls | 44 px tall (`h-control`); 36 px (`h-control-sm`) only inside dense table rows; 52 px (`h-control-lg`) for a sheet's primary; every target ≥ 24 × 24 px (WCAG 2.5.8) |
| Primary actions | 1 visible per surface (page; each open sheet/dialog) |
| Disclosure depth | 2 levels: the screen, then one `More` / sheet / menu. Never a `More` inside a `More` |
| Contrast | 4.5 : 1 text, 3 : 1 large text and control edges (`border-line-strong`); measured on the tokens: text 5.0–17.7 : 1, control edges 3.1 (light) / 3.7 (dark); `border-line` (1.4 : 1) is for dividers only |
| Focus | 3 px outline, 2 px offset, on every focusable thing (`:focus-visible`) |
| Status | icon + word + colour, always |
| Text scaling | layout survives 200 % zoom; `rem` everywhere, never shrink `html` |
| Press feedback | within one frame: `active:scale-[0.97]` over 100 ms, busy spinner when the action is async |

Apple's 44 **pt** and WCAG's CSS **px** are different units — use the px numbers above for the web.

## Moving parts

1. **Tokens** (`theme.css`) — semantic colours as CSS variables (light + `.dark`), type scale
   `meta/body/lead/title/page`, control sizes, radii, focus outline, reduced-motion floor. Components
   reference names only.
2. **Page** — title (the job, as a noun) + one-line description + one primary (verb + noun) + ≤ 2 quiet
   secondaries. Form pages `max-w-2xl`; list pages `max-w-6xl`.
3. **Button** — `primary · secondary · ghost · danger`, `sm · md · lg`; `aria-disabled` instead of
   `disabled` so focus never drops to `<body>`; `busy` shows a spinner and swallows clicks.
4. **Field** — label above, hint below, error = what's wrong — how to fix; one column.
5. **More** — native `<details>` for level 2 (`More filters`, `Advanced`).
6. **Sheet** — one record's detail beside the still-visible list; Esc closes; focus in, focus back.
7. **Table** — sticky head, 44 px rows, one visible row action, the rest in the row's `…` menu.
8. **States** — skeleton shaped like the content, empty state that carries the screen's primary,
   problem block (why + numbered how + retry) inline where the eyes are.
9. **Floors check** — `scripts/check-floors.mjs <url>…` measures targets, text size and primary count.

## Workflow (each step ends on its done-criterion)

1. **Name the job.** One sentence ("Technicians fix open machine tickets") and one primary verb + noun
   ("New ticket"). Done when both exist; if you need two primaries, it is two screens or a sheet.
2. **Install tokens** — `theme.css` from REFERENCE §1 imported once; dark class on `<html>`. Done when
   `bg-surface text-fg h-control` render.
3. **Sort every control** into: primary (1) · always visible (what ≥ 80 % of visits use) · level 2
   (`More`, row menu, sheet) · cut. Done when nothing is in two places.
4. **Build from the recipes** (REFERENCE §3–10), page → content → sheet. No raw colours, no px sizes.
5. **Write the three states** — loading, empty (carries the primary), problem (why/how/retry).
6. **Check** — `npx vite preview`, then `node scripts/check-floors.mjs` on every screen and state URL
   (light and dark). Done when all pass and a screenshot of each was looked at.

## Principles

- **Simple is not minimal.** Hide by frequency, not by tidiness: a control used on most visits stays
  visible even if it adds clutter; a rare one folds even if there is room.
- **Words over icons.** Icon-only buttons only for universally known actions (close, search, menu) and
  always with `aria-label`; everything else has a verb label.
- **Context stays, detail slides in.** Open a record in a sheet over its list, not a new page or a
  stacked modal; one sheet at a time.
- **Errors are instructions** in the user's words, next to the thing that failed; toasts are for
  history, not for errors that need action.
- **Steppers only for independent steps.** If users go back and forth between steps, use one form.
- **Desk first.** Desktop web at 1280–1920 px; touch targets are generous anyway, so a tablet works.
  Bench / kiosk / gloved use → `focused-task-flow`.

## Pitfalls

- A later utility silently loses: `inputClass + ' w-44'` kept `w-full`, and a `textarea` stayed one line
  under `h-control`. Shared class strings carry look only; width and height are set per control.
- Tailwind draws `ring-*` as `box-shadow` — a hover shadow erases it. Focus is an `outline` here.
- Tailwind v4 preflight drops `cursor: pointer` on buttons and `summary` — restored in the base layer.
- An empty state with its own "New ticket" next to the header's makes two primaries — drop the header
  one while the list is empty.
- `disabled` buttons drop keyboard focus to `<body>`; a double press fires twice before React re-renders
  — `aria-disabled` + ignore, and guard async actions with a ref.
- The soft divider colour on an input left its edge at 1.36 : 1 — invisible on a bright monitor. Control
  edges use `line-strong` (≥ 3 : 1); `line` stays for dividers and card outlines.
- `text-xs`/`text-[11px]` creep into tables and badges; the check fails anything under 14 px.
- Colour-only status disappears under glare and for colour-blind users — `Status` always shows a word.
- Translucent glass on content hurts legibility; use blur only on floating chrome, and drop it under
  `prefers-reduced-transparency`.

## Composes with

`ui-motion-system` (motion vocabulary, skeleton shimmer, arrivals) · `focused-task-flow` (bench / kiosk
one-task screens built on these tokens) · `console-app-shell` (sidebar, roles, settings) ·
`keyboard-first-hotkeys` (focus chain, shortcuts) · `frontend-design` (brand direction on top).

Code: [REFERENCE.md](REFERENCE.md). Floors check: [scripts/check-floors.mjs](scripts/check-floors.mjs).
