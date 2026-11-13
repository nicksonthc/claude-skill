---
name: agent-pipeline
description: Set up, sync or update a repo's scheduled agent pipeline, a set of Claude Code cloud routines that audit the code, groom a backlog, implement human-approved issues, evaluate and redo PRs, ship a release PR and post a weekly scorecard. All of them run from one generic core (a tested control plane, role prompts, hooks, a run ledger) plus a per-repo profile. Use when the user says "set up the agent pipeline / routines in this repo", "sync routines", "update the pipeline core", "check routine drift", "add a local routine", or wants a repo's hand-written routines made generic.
---

# Agent pipeline

One pipeline serves every repo, in three layers:
- **core**: a control plane (`bin/pipeline.py`), generic role prompts, shared rules, the scorecard and hooks. It is
  vendored into `<repo>/.claude/routines/core/`, and `core/VERSION` names its release.
- **profile**: `.claude/routines/pipeline.yml`, the repo's facts plus its live routine registry.
- **local routines**: `.claude/routines/local/*.md`, which carry domain logic (usually the audit).

Each claude.ai routine runs a short launcher. The launcher checks out the integration branch, opens the run's ledger
record (`pipeline.py begin`), and reads the profile, `core/shared.md` and the routine's prompt. Every run then follows
the same protocol: **select** (code picks the eligible work) → **judge** (the model) → **post** (every GitHub write
goes through one gateway) → **finish** (one ledger record per run).

The flow: find (local audit → hub issue) → groom (≤3 traced picks) → approve (a human labels the issue `groomed`) →
build → evaluate → revise (a human writes `#redo`) → ship → measure.

Two capped loops run beside the flow, with no human gate before they act and a human merge after. `ci-doctor` heals
red CI: it reruns once, opens one issue per failure, and makes at most `ci.autofix.max_attempts` fix attempts.
`pipeline-rnd` improves the pipeline itself, with one researched change per run to a rolling PR. The label
`agent-pause` on the hub stops both.

For the moving parts, see `core/README.md`. For the RemoteTrigger body, hook registration, markers, the ledger,
rulesets and the setup script, see `REFERENCE.md`. For why it is built this way, see
`docs/research-2026-11-13-autonomous-pipeline.md` (sources, alternatives, and the roadmap).

## Workflows

### Install: onboard a repo
1. **Read the repo before asking anything.** Find:
   - the default branch and any release branch;
   - CLAUDE.md (or AGENTS.md) and the docs;
   - each testable package's runner, test layout and fixtures;
   - the lint and format tools, at their pinned versions;
   - the CI job names (`gh api repos/<repo>/commits/<sha>/check-runs`);
   - existing `.claude/` hooks and skills.
2. **Ask the user only what the repo cannot tell you:**
   - the approvers;
   - the risky (T2) paths;
   - the guard skills;
   - any extra rules;
   - which routines to enable;
   - whether run records go to Turso or to git only.
3. **Write the profile.** Start `.claude/routines/pipeline.yml` from `templates/pipeline.yml`.
   - Add one `components[]` entry per testable package.
   - Scope each `static` command to `{files}` (the files a routine changed), at the repo's pinned versions.
   - Leave `ci` out when there is no test CI. Then only the audit, groom and scorecard can be enabled.
   - If the repo's CI or hooks run a formatter over the whole repo, exclude `.claude/routines/core/` from it.
4. **Vendor the core.** `rsync -a --delete --exclude __pycache__ <skill>/core/ <repo>/.claude/routines/core/`.
5. **Hooks** (`REFERENCE.md` §2).
   - Register `push-guard.py`, `write-guard.py`, the marker hook and the `run-ledger.py` Stop hook in
     `.claude/settings.json`. All four act only in cloud sessions.
   - Make every existing repo hook that needs local services exit 0 when `CLAUDE_CODE_REMOTE` is `"true"`.
6. **The audit.** Write it from `templates/local-audit.md`. It must follow `core/hub-contract.md`.
7. **CI proof job.** If the repo has test CI, add the proof job from `templates/agent-proof.yml`, adapting its setup
   steps.
8. **The hub issue and the labels.**
   - Create the hub issue with a body of the marker line, the AI header and "awaiting the first audit", then record
     its number in the profile.
   - Create the labels the routines read and write: at least `groomed` and `groom-proposed`, plus the loops' labels
     (`REFERENCE.md` §3). No routine ever creates a label.
9. **Environment.** Configure the cloud environment:
   - add `python3 -m pip install -q pyyaml` to its setup script (`REFERENCE.md` §6);
   - when Turso is wanted, set `ledger.turso_url`, run `pipeline.py ledger init-db` locally, and add the network
     secret (`REFERENCE.md` §4);
   - to see token and cost per run, add the OpenTelemetry variables.
10. **Check and PR.** `python3 <skill>/check.py <repo>` must report 0 errors. Then open the PR. `.claude/**` always
    gets human review and is never auto-merged.
11. **Go live.** Wait until the PR has merged and `.claude/settings.json` is on the default branch. Then:
    - apply the rulesets: `check.py <repo> --rulesets` (`REFERENCE.md` §5), after the user confirms. The
      PR-only rule changes how people push to those branches.
    - `python3 <skill>/check.py <repo> --doctor` must report 0 errors;
    - *sync* every routine with `enabled: false`;
    - run each one now with the message `DRY RUN`, and read its run log. It shows `select`'s JSON, each post it
      would make, and its ledger record;
    - enable it.

Install is done when every enabled routine has a clean DRY RUN log and `check.py --doctor` passes.

### Sync routines (pipeline.yml → claude.ai)
For each routine, build the body (`REFERENCE.md` §1). Its prompt is the output of
`python3 <skill>/check.py <repo> --launcher <key>`.
- `id: null`: RemoteTrigger `create`. Then clear the account's default connectors unless `mcp` lists some, and record
  the new id in the profile through a PR.
- Otherwise: RemoteTrigger `update`.

Sync is done when `get` on every id matches the profile.

### Update the core
1. `rsync -a --delete --exclude __pycache__ <skill>/core/ <repo>/.claude/routines/core/`.
2. Write the PR body:
   - List the upstream changes since the repo's old core: the `CHANGELOG.md` entries between the two `core/VERSION`s,
     and the `git log` of `skills/agent-pipeline/core` since the commit whose tree hash equals the repo's old
     `HEAD:.claude/routines/core`.
   - Call out anything the release asks of the repo, such as new hook registrations, profile keys or setup-script
     lines.
3. `check.py` passes. After the merge, `check.py --doctor` passes.

The update is done when, after the merge, the repo's core tree hash equals upstream's.

Roll a new core release out to one repo first. Watch a week of its scorecard (runs, missed slots, first-pass rate)
before updating the rest.

### Check routine drift
1. `get` every id.
2. Compare cron, enabled, model, tools, sources, environment and the launcher text against the profile and
   `check.py --launcher`.
3. Compare `git rev-parse HEAD:.claude/routines/core` (repo) with `git rev-parse HEAD:skills/agent-pipeline/core`
   (skill), and the two `VERSION` files.
4. Report each difference and fix one side or the other, so the two never stay out of step.

### Add a local routine
1. Write `local/<key>.md`. If it writes to GitHub, give it a `writes:` front matter like `templates/local-audit.md`.
   Without one, the gateway treats it as an audit.
2. Add `{key, prompt: local/<key>.md, cron, model, tools, sources}` to the profile.
3. Run check, open the PR, then sync.

## Principles
- **Instructions live in git; the schedule lives on claude.ai.** A merged PR changes behaviour. Only *sync* touches
  claude.ai.
- **Core is generic; the profile holds the facts.** A project noun in `core/` is a bug: move it to the profile or into
  a local routine.
- **Code selects, the model judges.** Eligibility, gates, dedupe and write limits are code in `core/bin/`, and the
  tests cover them. Prompts hold only the judgement steps.
- **Gates are objective.** CI is the only test evidence. Agent confidence is reported, never gated on. "CI is the only
  evidence" is also what keeps the pipeline stack-agnostic: whatever the sandbox cannot build, CI still proves.
- **Humans decide twice:** with the `groomed` label, and with the merge.
- **Every run leaves a record.** GitHub holds the work and the decisions; the ledger holds what each run did.
- **Enforce on the server too.** Prompt rules, then hooks, then rulesets.

## Pitfalls (each one cost a real run, or would have)
- `gh pr …` and `gh issue …` use GraphQL, which Claude Code sessions block with a 403. So do the `search/`
  endpoints. A script that calls them fails every week. Use `gh api` (REST) on repository-scoped paths.
- Every routine post shows the owner's login. `performed_via_github_app.slug == "claude"` marks a routine, and null
  marks a human. Gate human commands and approvals on that field, never on the login.
- **Routines act as the owner.** A ruleset the owner can bypass does not stop a routine's push, and the GitHub proxy
  does not limit which branch a push updates. Rulesets need an empty bypass list, and `write-guard.py` covers what
  GitHub cannot tell apart, such as a merge.
- **Hook scripts run from whatever is checked out in the session.** A routine that checks out a PR head runs the PR's
  version of the hooks, so a PR could switch off `push-guard.py`. The session checkout stays on the integration
  branch, and PR work happens in `git worktree`s under `/tmp/wt/`.
- **YAML 1.1 reads `on:`, `yes:` and `off:` as booleans.** `{on: hub}` parses as `{True: 'hub'}`, so the `writes:` key
  is `to:`.
- People write `#redo` below their feedback, not first. Match any line `^\s*#redo\b`.
- PRs into a non-default integration branch never fire `Closes #N`. The release PR has to carry those references.
- **Picks that only a human can turn into issues sit unapproved:** six of them in one 12-day stretch, with the
  implementer idle. backlog-groom opens the proposal issue itself, labelled `groom-proposed`, so approving is one
  label. "Convert to issue" stays the fallback. It leaves an empty body and takes the whole task line as the title,
  which is why that line is still the bare title (`core/hub-contract.md`, Groom items).
- **Never `gh api --paginate` in a cloud session.** It follows `Link: rel="next"`, which GitHub writes as a numeric-ID
  path that the proxy refuses (403). Page 1 still prints, so the failure appears only once a list outgrows it.
  `pipeline.py` walks `page=N` instead.
- **A routine's writes to a second repo were refused in practice.** pilot-repo's pipeline-rnd shipped nothing upstream
  in six runs, and was removed on 2026-11-03. DRY RUN such a route before relying on it.
- Sessions start on the default branch. A hook registered in `.claude/settings.json` takes effect only once it reaches
  that branch.
- Repo hooks run in cloud sessions too. A hook that needs a local database blocks every routine push.
- Multi-repo sessions start in the folder above the clones and load no repo hooks. Keep extra `sources` to read-only
  routines.
- A green run status does not mean the task succeeded. Read `get_run_log`, or the run's ledger record.
- RemoteTrigger `list` returns only the first page, and the API cannot delete a routine; use the console.
- New triggers inherit the account's default connectors.
- Routines can also fire on GitHub PR, issue and release events and through an API `/fire` call, not only on cron.
  - Comments are not an event source.
  - Events over the hourly caps are dropped, not queued.
  - `/fire` has no idempotency key.

  Keep cron as the backstop if you add event triggers.
- PyYAML can be missing from the cloud image. Install it in the environment's setup script; `pcfg.py` falls back to
  pip.
- Whole-repo format checks are often already red (pilot-repo: black wants 16 files reformatted). A gate on
  `black --check .` can never pass, so scope `static` to `{files}`.
