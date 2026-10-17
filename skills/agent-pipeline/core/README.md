# Agent pipeline (core)

This folder is vendored from the `agent-pipeline` skill (the claude-skill repo, `skills/agent-pipeline/core`).
Change it upstream, then re-vendor it with the skill ("update the pipeline core"), so every repo runs the same core.
While nobody has edited it locally, `git rev-parse HEAD:.claude/routines/core` equals the upstream folder's tree hash.

## Moving parts
| Path | What it is |
|---|---|
| `../pipeline.yml` | this repo's profile (its facts) and its live routine registry. Edit this. |
| `../local/*.md` | routines only this repo has, such as its audit |
| `shared.md` | the rules every routine follows |
| `hub-contract.md` | the hub issue format: audits write it, backlog-groom reads it |
| `roles/*.md` | the six generic roles; the front matter lists default tools and what each role needs from the profile |
| `scorecard.py` | weekly outcome metrics, REST only |
| `hooks/` | two cloud-only hooks, registered in `.claude/settings.json`: `require-ai-marker.sh` (every GitHub write carries the AI header and footer) and `push-guard.py` (blocks pushes to the integration or production branch, force-pushes and branch deletes) |

## The flow
find (a local audit) → groom → approve (a human labels the issue `groomed`) → build → evaluate → revise (a human
writes `#redo`) → ship → measure

## How a routine runs
Each routine's claude.ai prompt is a short launcher. Run `check.py --launcher <key>` in the skill to print it.
1. It checks out the integration branch.
2. It reads `pipeline.yml`, `core/shared.md` and the routine's prompt.
3. It follows them.

The instructions are read at run time, so merging a PR changes behaviour without a claude.ai edit. Cron, model,
tools and sources live on claude.ai; the skill syncs them from `pipeline.yml` when asked to "sync routines".
`.claude/**` changes what the agents do, so it always gets human review and is never auto-merged.

## Changing things
| To change | Edit | Then |
|---|---|---|
| a fact about this repo (branches, checks, paths, approvers) | `pipeline.yml` | merge the PR |
| a repo-only routine | `local/<key>.md` + its entry in `pipeline.yml` | merge, then "sync routines" |
| schedule, model, tools | `pipeline.yml` | merge, then "sync routines" |
| generic behaviour | the skill, upstream | "update the pipeline core" in each repo |

## Try before enabling
Run a routine from claude.ai with the message `DRY RUN`. It prints every write it would make and makes none.

## Drift
Ask Claude Code to "check routine drift". It compares each routine's live config with `pipeline.yml`, and this
folder's tree hash with upstream. To pause or delete a routine, use https://claude.ai/code/routines (the API cannot
delete one). Never put secrets in these files.
