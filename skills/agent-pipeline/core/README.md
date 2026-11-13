# Agent pipeline (core)

This folder is vendored from the `agent-pipeline` skill (the claude-skill repo, `skills/agent-pipeline/core`).
Change it upstream, then re-vendor it with the skill ("update the pipeline core"), so every repo runs the same core.
`VERSION` names the release, and the skill's `CHANGELOG.md` says what changed. While nobody has edited the folder
locally, `git rev-parse HEAD:.claude/routines/core` equals the upstream folder's tree hash.

## Moving parts
| Path | What it is |
|---|---|
| `../pipeline.yml` | this repo's profile (its facts) and its live routine registry. Edit this. |
| `../local/*.md` | routines only this repo has, such as its audit |
| `shared.md` | the rules every routine follows, including the run protocol |
| `hub-contract.md` | the hub issue format (audits write it, backlog-groom reads it) and how an issue finds its groom item |
| `roles/*.md` | the eight generic roles: the six of the flow, and the two loops `ci-doctor` and `pipeline-rnd`. The front matter lists default tools, what each role needs from the profile, and the writes it may make. |
| `bin/pipeline.py` | the control plane: `begin`, `select <role>`, `overlap`, `post`, `finish`. Code selects the work and gates every write; the model judges. |
| `bin/gates.py` | the selection rules (WIP, approval, in-flight, requirement, CI state, `#redo` screening) |
| `bin/writes.py` | the write gateway: marker, provenance, header and footer; per-role limits; dedupe; DRY RUN |
| `bin/ledger.py` | the run ledger: one record per run, to Turso when `ledger.turso_url` is set, else to the `pipeline-ledger` branch |
| `bin/scorecard.py` | weekly outcome metrics, the run ledger and guardrail breaches, REST only |
| `hooks/` | four cloud-only hooks, registered in `.claude/settings.json`; see the next table |
| `VERSION` | the core's release |

| Hook | What it does |
|---|---|
| `push-guard.py` | blocks pushes to integration or production, force-pushes and branch deletes |
| `write-guard.py` | blocks merges, reviews, closes, approval labels, ref deletes, settings changes and writes to other repos |
| `require-ai-marker.sh` | every GitHub write carries the AI header and footer |
| `run-ledger.py` | a Stop hook: no run ends without its ledger record |

## The flow
find (a local audit) → groom → approve (a human labels the issue `groomed`) → build → evaluate → revise (a human
writes `#redo`) → ship → measure

Two loops run beside it without a human gate, each capped, and each ships only PRs a human merges:
- **heal** (`ci-doctor`): a failed watched workflow → rerun once (flaky or broken) → one issue per signature → a
  fix PR on its own branch → CI on that branch → at most `ci.autofix.max_attempts` tries, then `ci-blocked`.
- **improve** (`pipeline-rnd`): last week's pipeline evidence + fetched sources → one change per run to a rolling
  `rnd/pipeline-<week>` PR, upstream for generic changes and in the repo for its own facts.

The label `agent-pause` on the hub issue stops both loops.

## How a routine runs
Each routine's claude.ai prompt is a short launcher. Run `check.py --launcher <key>` in the skill to print it.
1. It checks out the integration branch, which stays checked out for the whole run. Work on other branches happens in
   worktrees, so hooks and prompts always come from reviewed code.
2. It runs `pipeline.py begin <key>`, which opens the run's ledger record.
3. It reads `pipeline.yml`, `core/shared.md` and the routine's prompt, and follows them. The run protocol is select →
   judge → post → finish.

The instructions are read at run time, so merging a PR changes behaviour without a claude.ai edit. Cron, model,
tools and sources live on claude.ai; the skill syncs them from `pipeline.yml` when asked to "sync routines".
`.claude/**` changes what the agents do, so it always gets human review and is never auto-merged.

## Changing things
| To change | Edit | Then |
|---|---|---|
| a fact about this repo (branches, checks, paths, approvers) | `pipeline.yml` | merge the PR |
| a repo-only routine | `local/<key>.md` + its entry in `pipeline.yml` | merge, then "sync routines" |
| schedule, model, tools | `pipeline.yml` | merge, then "sync routines" |
| where run records go | `ledger:` in `pipeline.yml` | merge the PR |
| generic behaviour | the skill, upstream | "update the pipeline core" in each repo |

## Try before enabling
Run a routine from claude.ai with the message `DRY RUN`. It prints every write it would make, and the ledger record
it would store, and makes none.

## Drift
Ask Claude Code to "check routine drift". It compares each routine's live config with `pipeline.yml`, and this
folder's tree hash with upstream. `check.py <repo> --doctor` checks the live repo itself: the hub, the label, the
rulesets, the ledger branch, the CI names and the hooks.

To pause or delete a routine, use https://claude.ai/code/routines; the API cannot delete one. Never put secrets in
these files.
