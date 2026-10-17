---
name: agent-pipeline
description: Set up, sync or update a repo's scheduled agent pipeline, a set of Claude Code cloud routines that audit the code, groom a backlog, implement human-approved issues, evaluate and redo PRs, ship a release PR and post a weekly scorecard. All of them run from one generic core plus a per-repo profile. Use when the user says "set up the agent pipeline / routines in this repo", "sync routines", "update the pipeline core", "check routine drift", "add a local routine", or wants a repo's hand-written routines made generic.
---

# Agent pipeline

One pipeline serves every repo, in three layers:
- **core**: generic role prompts, shared rules, the scorecard and hooks. It is vendored into
  `<repo>/.claude/routines/core/`.
- **profile**: `.claude/routines/pipeline.yml`, the repo's facts plus its live routine registry.
- **local routines**: `.claude/routines/local/*.md`, which carry domain logic (usually the audit).

Each claude.ai routine runs a short launcher. The launcher reads the profile, `core/shared.md` and the routine's
prompt from the integration branch at run time.

The flow: find (local audit → hub issue) → groom (≤3 traced picks) → approve (a human labels the issue `groomed`) →
build → evaluate → revise (a human writes `#redo`) → ship → measure.

For the moving parts, see `core/README.md`. For the RemoteTrigger body, the hook registration and the marker table, see
`REFERENCE.md`.

## Workflows

### Install: onboard a repo
1. **Read the repo before asking anything.** Find:
   - the default branch and any release branch;
   - CLAUDE.md and the docs;
   - each testable package's runner, test layout and fixtures;
   - the lint and format tools, at their pinned versions;
   - the CI job names (`gh api repos/<repo>/commits/<sha>/check-runs`);
   - existing `.claude/` hooks and skills.
2. **Ask the user only what the repo cannot tell you:** the approvers, the risky (T2) paths, the guard skills, any
   extra rules, and which routines to enable.
3. **Write the profile.** Start `.claude/routines/pipeline.yml` from `templates/pipeline.yml`.
   - Add one `components[]` entry per testable package.
   - Scope each `static` command to `{files}` (the files a routine changed), at the repo's pinned versions.
   - Leave `ci` out when there is no test CI. Then only the audit, groom and scorecard can be enabled.
   - If the repo's CI or hooks run a formatter over the whole repo, exclude `.claude/routines/core/` from it.
4. **Vendor the core.** `rsync -a --delete <skill>/core/ <repo>/.claude/routines/core/`.
5. **Hooks** (`REFERENCE.md` §2).
   - Register `push-guard.py`, and the cloud-only `require-ai-marker.sh`, in `.claude/settings.json`.
   - Make every existing repo hook that needs local services exit 0 when `CLAUDE_CODE_REMOTE` is `"true"`.
6. **The audit.** Write it from `templates/local-audit.md`. It must follow `core/hub-contract.md`.
7. **CI proof job.** If the repo has test CI, add the proof job from `templates/agent-proof.yml`, adapting its setup
   steps.
8. **The hub issue.** Create it with a body of the marker line, the AI header and "awaiting the first audit", then
   record its number in the profile.
9. **Check and PR.** `python3 <skill>/check.py <repo>` must report 0 errors. Then open the PR. `.claude/**` always
   gets human review and is never auto-merged.
10. **Go live.** Wait until the PR has merged and `.claude/settings.json` is on the default branch. Then:
    - *sync* every routine with `enabled: false`;
    - Run each one now with the message `DRY RUN`, and read its run log;
    - enable it.

Install is done when every enabled routine has a clean DRY RUN log and `check.py` passes.

### Sync routines (pipeline.yml → claude.ai)
For each routine, build the body (`REFERENCE.md` §1). Its prompt is the output of
`python3 <skill>/check.py <repo> --launcher <key>`.
- `id: null`: RemoteTrigger `create`. Then clear the account's default connectors unless `mcp` lists some, and record
  the new id in the profile through a PR.
- Otherwise: RemoteTrigger `update`.

Sync is done when `get` on every id matches the profile.

### Update the core
1. `rsync -a --delete <skill>/core/ <repo>/.claude/routines/core/`.
2. In the PR body, list the upstream commits since the repo's old core. Run `git log` on `skills/agent-pipeline/core`,
   starting from the commit whose tree hash equals the repo's old `HEAD:.claude/routines/core`.
3. `check.py` passes.

The update is done when, after the merge, the repo's core tree hash equals upstream's.

### Check routine drift
1. `get` every id.
2. Compare cron, enabled, model, tools, sources and the launcher text against the profile and `check.py --launcher`.
3. Compare `git rev-parse HEAD:.claude/routines/core` (repo) with `git rev-parse HEAD:skills/agent-pipeline/core`
   (skill).
4. Report each difference and fix one side or the other, so the two never stay out of step.

### Add a local routine
1. Write `local/<key>.md`.
2. Add `{key, prompt: local/<key>.md, cron, model, tools, sources}` to the profile.
3. Run check, open the PR, then sync.

## Principles
- **Instructions live in git; the schedule lives on claude.ai.** A merged PR changes behaviour. Only *sync* touches
  claude.ai.
- **Core is generic; the profile holds the facts.** A project noun in `core/` is a bug: move it to the profile or into
  a local routine.
- **Gates are objective.** CI is the only test evidence. Agent confidence is reported, never gated on.
- **Humans decide twice:** with the `groomed` label, and with the merge.

## Pitfalls (each one cost a real run)
- `gh pr …` and `gh issue …` use GraphQL, which Claude Code sessions block with a 403. A script that calls them fails
  every week. Use `gh api` (REST).
- Every routine post shows the owner's login. `performed_via_github_app.slug == "claude"` marks a routine, and null
  marks a human. Gate human commands and approvals on that field, never on the login.
- People write `#redo` below their feedback, not first. Match any line `^\s*#redo\b`.
- PRs into a non-default integration branch never fire `Closes #N`. The release PR has to carry those references.
- "Convert to issue" leaves an empty body, so the acceptance criteria stay in the groom comment.
- Sessions start on the default branch. A hook registered in `.claude/settings.json` takes effect only once it reaches
  that branch, but hook scripts run from whatever branch is checked out.
- Repo hooks run in cloud sessions too. A hook that needs a local database blocks every routine push.
- Multi-repo sessions start in the folder above the clones and load no repo hooks.
- A green run status does not mean the task succeeded. Read `get_run_log`.
- RemoteTrigger `list` returns only the first page, and the API cannot delete a routine; use the console.
- New triggers inherit the account's default connectors.
- PyYAML can be missing from the cloud image. Launchers don't need it, and the scorecard installs it.
- Whole-repo format checks are often already red (micron-be: black wants 16 files reformatted). A gate on
  `black --check .` can never pass, so scope `static` to `{files}`.
