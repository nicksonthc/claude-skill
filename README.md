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
| [`r3f-scene-world`](skills/r3f-scene-world/) | Large hand-authored R3F worlds: one deformable authoring frame shared by geometry, placements, scatter and camera routes; merged bulk geometry; instanced-scatter triangle budget; per-frame store discipline; scripted first-person route with one camera owner; Playwright stills + clearance sweeps. |
| [`harvest-skill`](skills/harvest-skill/) | Meta-skill: harvest a feature from whatever repo you're in into a new generic skill here — distill, genericize, author, symlink, commit. |
| [`system-status-popover`](skills/system-status-popover/) | Honest system-status indicator for a SPA + API app: beating status dot → popover with backend health, Socket.IO state, and build provenance (git SHA → Docker build args → /health + bundle). |
| [`keyboard-first-hotkeys`](skills/keyboard-first-hotkeys/) | Keyboard-first interaction system for kiosk / scan-gun React apps: one hotkey catalogue driving bindings + button hints + cheatsheet, a focus chain, and a focus guard that recovers focus lost to re-renders. |
| [`socketio-realtime-hooks`](skills/socketio-realtime-hooks/) | React hook suite for a Socket.IO feed: one authenticated connection, never-rebinding event listeners, auto re-joining rooms, X-Client-Id ↔ skip_sid echo suppression, presence, and poll-self-heal composition. |
| [`toast-notification-history`](skills/toast-notification-history/) | Toasts with an audit trail: drop-in sonner wrapper that mirrors every toast into a capped localStorage history with the acting user stamped on, shown in a floating-bell slide-over with unread badge. |
| [`bilingual-copy-store`](skills/bilingual-copy-store/) | Two-language (or N-language) UI with one shared copy dictionary, a Zustand-backed toggle that persists and stays in sync across every page of a multi-entry app, typed keys for dynamic/status text, and a safe overlay for translating strings that live in generator-owned JSON. |
| [`image-to-3d-blender`](skills/image-to-3d-blender/) | Reference image → GLB with headless Blender: silhouette extrusion for flat/transparent images, or reference-guided procedural studies (buildings, boats, trees, figures) via a shared `studio.py` helper library, with transparent preview, .blend and manifest entry. |

The R3F skills compose: `guided-placement` delegates camera framing to
`r3f-hero-camera` and layers onto `interactive-3d-object`'s hover/select base;
`r3f-scene-world` builds the world those three act in, and hands its GLB
authoring to `image-to-3d-blender`. Each also stands alone.

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
