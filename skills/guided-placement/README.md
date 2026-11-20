# Guided Placement · `guided-placement`

![guided-placement demo](assets/guided-placement.gif)

*Pasar malam demo: dragging a new red-and-white canopy stall into an empty lot — lift and glow, a flowing path, a holo ring on the target, magnetic snap and a success pop.*

Multi-stage drag-to-place choreography for React Three Fiber: click → glow + anticipation dip, soft lift, a flowing path, a holographic ring on the candidate slot, gentle camera framing, a magnetic snap with proximity telegraph, then a scale pop with a ripple and a checkmark. Placement is object-aware through policies: a fixed single slot, or free placement over grid cells / zones with per-object validity rules.

## Use it when
- guided pick-and-place, "drag this there"
- drag-to-relocate on a grid
- tutorial placement hints

## What's inside
| File | What |
|---|---|
| `SKILL.md` | stages, policies, workflow |
| `REFERENCE.md` | copy-paste choreography code |

## Works with
`interactive-3d-object` (hover/select base), `r3f-hero-camera` (framing).

## Install
```bash
npx skills add nicksonthc/claude-skill@guided-placement        # or symlink skills/guided-placement into ~/.claude/skills
```
Claude Code picks it up from the trigger phrases above, or run it directly with `/guided-placement`.
