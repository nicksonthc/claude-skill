---
name: harvest-skill
description: Harvest a feature from the current repo into a reusable Claude Code skill, saved to the claude-skill sync repo and symlinked globally so it replicates to any other project. Use when the user says "save this as a skill", "harvest this", "make a skill from this feature", "extract this to a skill", "add this to my skill repo", or wants a good pattern/feature from the codebase made replicable across repos.
---

# Harvest Skill

Turn a feature the user likes in the CURRENT repo into a generic, reusable
skill in the personal skill repo, so triggering that skill in any other repo
replicates the feature.

**Skill repo:** `/Users/nickson/Projects/claude-skill` (source of truth,
synced via git; `~/.claude/skills/` holds symlinks into it). If the repo is
missing on this machine, ask the user for its path or to clone
`git@github.com:nicksonthc/claude-skill.git` — never create a substitute
directory.

## Workflow

1. **Scope the feature.** Ask only if the user hasn't named it. Find every
   file that implements it and read them fully — entry component, helpers,
   config, styles/tokens. The harvest is done from complete understanding,
   never from one file's vibe.

2. **Load `writing-for-agents`** (if listed) before authoring — it carries the
   skill-writing rules (frontmatter, descriptions as context pointers,
   progressive disclosure).

3. **Check the repo's existing skills** (`skills/*/SKILL.md` one-line scan).
   If the feature overlaps one, extend that skill instead of duplicating; if
   it composes with siblings, cross-reference them by name the way the R3F
   suite does (`guided-placement` ↔ `r3f-hero-camera` ↔
   `interactive-3d-object`).

4. **Distill — the generic test.** The skill must work in a repo that shares
   nothing with this one:
   - Strip project imports, store names, file paths, domain nouns; keep them
     only as *examples*. Domain-specific logic becomes a named extension
     point (a `resolve` fn, a status map, a config object).
   - Derive sizes/distances from parameters (content size, footprint, fov
     math), never the source project's magic constants.
   - **Mine the code comments** — comments explaining a fix or a constraint
     are documented bugs someone already paid for; they become the Pitfalls
     section. This is usually the most valuable part of the harvest.
   - Note the stack + versions the code was proven on (e.g. "R3F 8, drei 9,
     three 0.169").

5. **Author** `skills/<name>/` in the skill repo, following the house style:
   - `SKILL.md` — frontmatter (`name` matching the directory, `description`
     front-loading trigger phrases the user would actually say), then:
     overview of the moving parts, a workflow checklist, core principles,
     pitfalls. Keep it under ~120 lines; it teaches judgment, not code.
   - `REFERENCE.md` — the copy-paste building blocks, genericized, one
     numbered section per component, with the why-comments preserved.
   - Kebab-case name describing the capability, not the source project.

6. **Wire it in:**
   - README table row (one line, what it does).
   - `ln -sfn "$REPO/skills/<name>" ~/.claude/skills/<name>`
   - Commit in the skill repo (conventional message; do NOT push unless
     asked — pushing publishes).

7. **Report**: skill name, what was genericized away, the extension points a
   future repo must fill in, and that it activates next session (or now via
   `/<name>`).

## Principles

- **Harvest patterns, not files.** A skill that says "copy X.jsx" dies with
  its source; a skill that teaches the architecture + hands over genericized
  code lives anywhere.
- **Pitfalls are the payload.** Anyone can rebuild the happy path; the fixed
  bugs, ordering constraints and "must be `false` here" details are what make
  replication cheap. Hunt them relentlessly.
- **One skill, one capability.** A feature that is really two independent
  capabilities (a camera rig AND an FX layer) becomes two skills that
  cross-reference — each triggers on its own.
- **The description is the trigger.** Write it as the branches of when to
  fire, in the user's vocabulary, front-loaded. A great skill behind a weak
  description never fires.
- **Leave the source repo untouched** unless the user asks — the harvest
  reads the project; it writes only to the skill repo and `~/.claude/skills`.
