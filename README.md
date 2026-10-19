# claude-skill

Version-controlled home for my personal Claude Code skills. This repo is the
source of truth; `~/.claude/skills/` holds symlinks back into it, so editing a
skill here immediately changes the skill Claude Code loads.

## Skills

| Skill                                    | What it does                                                                                  |
| ---------------------------------------- | --------------------------------------------------------------------------------------------- |
| [`network-diagram`](skills/network-diagram/) | Renders a printable engineering-blueprint network topology as one self-contained 1920x1080 HTML file. |
| [`r3f-hero-camera`](skills/r3f-hero-camera/) | Cinematic camera rig for React Three Fiber: shot vocabulary, stutter-free follow cam, attract orbit, ortho/perspective switching, writer-priority ladder. |
| [`interactive-3d-object`](skills/interactive-3d-object/) | AAA hover/select feedback for R3F objects: design tokens, status→color language, ObjectFX overlay (rings, glow, ripple, burst, label), hover tooltip, action previews. |
| [`guided-placement`](skills/guided-placement/) | Multi-stage drag-to-place choreography for R3F: glow + lift + flowing path + holo ring + magnetic snap + success pop, with object-aware placement policies. |
| [`r3f-scene-world`](skills/r3f-scene-world/) | Large hand-authored R3F worlds: one deformable authoring frame shared by geometry, placements, scatter and camera routes; merged bulk geometry; instanced-scatter triangle budget; per-frame store discipline; scripted first-person route with one camera owner; one-state weather with instanced drizzle and species-aware leaf shedding; Playwright stills + clearance sweeps. |
| [`harvest-skill`](skills/harvest-skill/) | Meta-skill: harvest a feature from whatever repo you're in into a new generic skill here — distill, genericize, author, symlink, commit. |
| [`system-status-popover`](skills/system-status-popover/) | Honest system-status indicator for a SPA + API app: beating status dot → popover with backend health, Socket.IO state, and build provenance (git SHA → Docker build args → /health + bundle). |
| [`keyboard-first-hotkeys`](skills/keyboard-first-hotkeys/) | Keyboard-first interaction system for kiosk / scan-gun React apps: one hotkey catalogue driving bindings + button hints + cheatsheet, a focus chain, and a focus guard that recovers focus lost to re-renders. |
| [`socketio-realtime-hooks`](skills/socketio-realtime-hooks/) | React hook suite for a Socket.IO feed: one authenticated connection, never-rebinding event listeners, auto re-joining rooms, X-Client-Id ↔ skip_sid echo suppression, presence, and poll-self-heal composition. |
| [`toast-notification-history`](skills/toast-notification-history/) | Toasts with an audit trail: drop-in sonner wrapper that mirrors every toast into a capped localStorage history with the acting user stamped on, shown in a floating-bell slide-over with unread badge. |
| [`bilingual-copy-store`](skills/bilingual-copy-store/) | Two-language (or N-language) UI with one shared copy dictionary, a Zustand-backed toggle that persists and stays in sync across every page of a multi-entry app, typed keys for dynamic/status text, and a safe overlay for translating strings that live in generator-owned JSON. |
| [`image-to-3d-blender`](skills/image-to-3d-blender/) | Reference image → GLB with headless Blender: silhouette extrusion for flat/transparent images, or reference-guided procedural studies (buildings, boats, trees, figures) via a shared `studio.py` helper library, with transparent preview, .blend and manifest entry. |
| [`smart-task-guide`](skills/smart-task-guide/) | In-app smart guide: Ctrl+K task search that navigates and spotlights each control until the user presses the final button, plus branching troubleshooting runbooks that read backend data read-only, suggest answers, stop with a reason and leave a copyable case summary; mock-backend + Playwright proof recipe. |
| [`agent-pipeline`](skills/agent-pipeline/) | Scheduled Claude Code cloud routines for any repo — audit → groom → gated implement → evaluate → `#redo` → release PR → weekly scorecard — run from one vendored generic core plus a per-repo `pipeline.yml` profile; install, sync, update-core and drift workflows, REST-only GitHub access, and cloud-only push-guard and AI-marker hooks. |
| [`guided-product-tour`](skills/guided-product-tour/) | Chaptered, role-filtered product tour for a React app: a spotlight card over the real screens that navigates and opens the menus and dialogs it points at, per-terminal progress ticks, first-run auto-start, and a hands-on sandbox finale built from the app's real components. |
| [`focused-task-flow`](skills/focused-task-flow/) | One-task operator / kiosk station screen: a derived task state, a big "Now" prompt, exactly one primary, bench-distance sizing tokens, inline why + how-to-fix error blocks keyed by API error codes, WebAudio success/error cues, and a 16-point review rubric. |
| [`ui-motion-system`](skills/ui-motion-system/) | Motion and feedback for dashboards and kiosks: one token set and CSS-only utilities, skeletons instead of blank or zeroed screens, arrival flashes for live rows, tweened counters, confirmation pops, tilt/lift touch cards, a toast countdown bar, and a reduced-motion mode that keeps outlines. |
| [`console-app-shell`](skills/console-app-shell/) | Shell for a multi-role internal app or shared kiosk: one nav registry behind a role-filtered sidebar, per-terminal page reordering, collapsible groups, registry-fed hub pages, a hover-intent account menu, and settings split into validated line-wide server settings and per-terminal preferences. |
| [`replayable-audit-trail`](skills/replayable-audit-trail/) | Append-only audit events staged in the same transaction with name-based payloads, so a restore script can replay a wiped record onto reseeded reference data; deletions that take a reason and a snapshot, and a Deletion log read back from the trail. |
| [`request-error-logging`](skills/request-error-logging/) | Database-backed access and error logging for FastAPI that can never break a request: a 500 guard, handlers that log and answer unchanged, user attribution from the bearer token, a noise gate for polling GETs, and an admin System Log page. |

The R3F skills compose: `guided-placement` delegates camera framing to
`r3f-hero-camera` and layers onto `interactive-3d-object`'s hover/select base;
`r3f-scene-world` builds the world those three act in, and hands its GLB
authoring to `image-to-3d-blender`. Each also stands alone.

The shop-floor app skills compose the same way: `console-app-shell` hosts the
rest — the `system-status-popover` dot in its status row, the
`toast-notification-history` bell, `keyboard-first-hotkeys`, the
`guided-product-tour` action in its Guide group, and the admin pages of
`request-error-logging` and `replayable-audit-trail` in its management hub.
`ui-motion-system` is the motion vocabulary they share, and
`socketio-realtime-hooks` feeds their live data. `focused-task-flow` is the
station screen built on `keyboard-first-hotkeys`. Each also stands alone.

## Install

### With the skills CLI (any machine, one command)

```bash
npx skills add nicksonthc/claude-skill            # pick skills interactively
npx skills add nicksonthc/claude-skill -g         # global (~/.claude/skills)
npx skills add nicksonthc/claude-skill@r3f-hero-camera   # just one skill
```

The [skills CLI](https://skills.sh) scans the repo for `SKILL.md` files, so the
`skills/<name>/` layout here is picked up automatically.

### By symlink (my laptops — repo stays the live source of truth)

```bash
git clone git@github.com:nicksonthc/claude-skill.git
cd claude-skill
for s in skills/*/; do
  ln -sfn "$PWD/$s" "$HOME/.claude/skills/$(basename "$s")"
done
```

Editing a skill in the repo then immediately changes what Claude Code loads.
Verify with `/skills`, or invoke one as `/<name>`.

## Layout

```
skills/<name>/
├── SKILL.md            # entry point, <100 lines, frontmatter name + description
├── REFERENCE.md        # full spec, loaded only when needed
├── INPUT-TEMPLATE.md   # fill-in form for the skill's inputs
└── examples/           # canonical reference output + provenance
```

`SKILL.md`'s `description` is the only text Claude sees when choosing a skill,
so it carries the trigger words. Keep detail in `REFERENCE.md`.

## Provenance

`network-diagram` began as a copy-paste prompt
(`skills/network-diagram/examples/original-prompt.v1.md`) that lived only in
gitignored directories in two unrelated repos. It was converted to a skill and
corrected against its own reference render — see
[skills/network-diagram/CHANGELOG.md](skills/network-diagram/CHANGELOG.md) for
what was wrong.

Because it grew out of real client work, every identifier was genericised
before this repo was made public: the bundled reference render is a fictional
project on fictional hosts, and the skill now refuses to put credentials in a
drawing at all. The `v3` entry in that changelog lists exactly what changed.
