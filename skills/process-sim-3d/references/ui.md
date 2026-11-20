# Panels

Generated from the spec by `ui.js` (standalone) / `App.jsx` (React). Same layout in both:

| Area | Content | Source |
|---|---|---|
| Left top | title, subtitle, mode eyebrow | `spec.title / subtitle` |
| Left | end-to-end flow steps, lit while active | `spec.steps` + `status().flags` |
| Left bottom | last 5 log lines (sim mode) | `sim.log` |
| Right | machine card: counts, cell states, utilisation bars, KPI line | `status()` |
| Right | Timing & configuration: presets + one number + slider per param, grouped | `spec.params`, `spec.presets` |
| Bottom bar | play/pause, restart, clock, speed, views, mode (Walkthrough / Simulation), Compare, panels (Solid/Glass/Off), labels, auto-cam | `spec.views` |
| Centre bottom | walkthrough caption | `spec.tour[i].caption` |
| Dialog | comparison / analysis | `spec.compare` + experiment results |

Rules:
- Walkthrough mode hides every `.simOnly` element (metrics, log, config, Compare) — a story, not a dashboard.
- Restart-params rebuild the world; others apply to the next motion. Presets restart the run.
- Status text updates ~9×/s, never per frame; in React the sim lives in refs and panels read a snapshot.
- Movable layout blocks (e.g. trolley lanes along a long handler): right-click → menu with presets
  (Left / Center / Right) and **Drag to reposition…**; a plain drag always orbits. Snap to slots; restart
  the run on drop; log the move.
- Dialogs: cap height to the viewport (`max-height: calc(100dvh − 36px)`) and make the body
  `flex: 1; min-height: 0; overflow: auto` — `max-height: 100%` inside an auto-sized grid row scrolls nothing.
- Prefix new CSS classes per feature (`.bgrp`, `.adv*`) — a generic `.grp` collided with an existing rule
  and shifted a whole toolbar group.
- Bottom-bar label + its segment control live in one nowrap group so a wrap never orphans the label.
- Put the most-used setup toggles in the bar (e.g. "1 test rack / 2 test racks", "1 arm / 2 arms") with the
  engineer's default selected.
