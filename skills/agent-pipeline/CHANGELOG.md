# agent-pipeline changelog

The core's release is in `core/VERSION`. The list under each release says what it asks of a repo when the core is
re-vendored there.

## 2.0.0 — 2026-11-14
Code selects the work, gates every write and records every run; the model judges. Built on `main` as of `c3985c6`
(2026-11-03), so it keeps every 1.x change below. Background and sources:
`docs/research-2026-11-13-autonomous-pipeline.md`.

**What it asks of a repo:**
- **Hooks.** Register `core/hooks/write-guard.py` (PreToolUse) and the `core/hooks/run-ledger.py` Stop hook in
  `.claude/settings.json` (`REFERENCE.md` §2).
- **Setup script.** Add `python3 -m pip install -q pyyaml` to the cloud environment's setup script (`REFERENCE.md` §6).
- **Rulesets.** Apply them, after the owner confirms, where the repo's plan allows rulesets: `check.py <repo> --rulesets`
  (`REFERENCE.md` §5).
- **Local routines.** Re-vendor their prompts, or post through `pipeline.py post`: `templates/local-audit.md`. Direct
  `gh api` writes still work.
- **Optional.** Set `ledger.turso_url` and its network secret, and the OpenTelemetry variables (`REFERENCE.md` §4).
- **Launchers.** Re-sync every routine after the core merges, because the launcher gains a
  `pipeline.py begin <key>` step. Until then, `check.py --launcher` keeps printing the 1.x launcher for a repo whose
  vendored core has no `bin/pipeline.py`.

**Added:**
- **`core/bin/pipeline.py`**, the control plane:
  - `begin`;
  - `select <role>` (eligibility as JSON);
  - `overlap` (G4);
  - `post` (the write gateway);
  - `finish`;
  - `ledger init-db | metrics`.
- **`gates.py`.** The selection rules that were prose, now in code with tests:
  - WIP and its budget;
  - G1 human approval;
  - G2 in flight;
  - the requirement resolver: issue body, groom item, or an opted-in PR's own body;
  - evaluator scope from `evaluate.heads` and the opt-in label;
  - CI and proof states, with CI-MISSING re-entry; a ci-fix PR's proof marked n/a;
  - `#redo` screening and briefs;
  - the groom inputs, including its open proposals and the label preflight;
  - the computed release.
- **`writes.py`.** Every post is built the same way, and roles declare their writes in front matter (`kind`, `to`,
  `marker`, `labels`, `max`, `dedupe`).
  - **Kinds:** `comment`, `issue` (labels read back), `pr`, `pr-body`, `hub-body`, and `release-pr`.
  - **Refused:** duplicate evaluations, redo replies, scorecards, gate skips, and CI-DOCTOR issues.
  - **The hub body** is refused over its 60,000-codepoint budget.
  - **DRY RUN** prints instead of posting.
- **`ledger.py` and the Stop hook.** One record per run:
  - Turso when `ledger.turso_url` is set;
  - otherwise one JSON file per run on the `pipeline-ledger` branch;
  - git whenever Turso fails.
- **`write-guard.py`.** Blocks:
  - merges, reviews, closes and reopens;
  - the approval label, including on a new issue;
  - ref deletes and settings changes;
  - writes to any repo other than this one and `rnd.upstream`.
- **Rulesets, generated from the profile.** No bypass actors; required CI on integration.
- **Scorecard.**
  - a run-ledger section: runs, outcomes, and missed cron slots;
  - guardrail breaches, from actions made through the Claude app;
  - metrics JSON on the ledger branch;
  - bounded `since=` listings.
- **`check.py`.** `--rulesets` and `--doctor`, plus validation of `ledger:`, the per-routine `environment_id` and
  structured `writes:`. A repo still on a 1.x core gets the 1.x launcher.
- **`core/VERSION`, and this changelog.**

**Changed:**
- **Worktrees.** The session checkout stays on the integration branch, and PR and fix work happens in
  `git worktree`s. Hooks therefore always come from reviewed code.
- **Atomic claim.** The implementer's branch is `groomed/<N>`, without a slug. The push is the claim, and legacy
  `groomed/<N>-<slug>` branches still count as in flight.
- **pr-evaluator.** PRs with running checks wait without using one of the run's 3 slots.
- **ci-doctor.**
  - its issues, comments and fix PR go through the gateway;
  - a flake is a comment on the CI-DOCTOR-FLAKY issue, not an edit of its body;
  - fix branches are built in worktrees;
  - every run ends with `finish`.
- **pipeline-rnd.** Its own repo's PR and PR body go through the gateway, and every run ends with `finish`.
- **Provenance.** Line 2 reads `core=<VERSION>+<tree>`.
- **No-op runs.** A run with nothing to do still writes no issue or PR comment, but it does write its ledger record.
- **Scorecard path.** `core/scorecard.py` moved to `core/bin/scorecard.py`.

## 1.x — 2026-10-17 to 2026-11-02
- **The first generic pipeline:** core plus profile plus local routines; REST-only access; outcome scorecard; the push
  guard and marker hook.
- **Static checks** scoped to the changed files.
- **Groom items** found by their converted title.
- **Scorecard** lists PRs through repository-scoped REST.
- **ci-doctor** (heal loop) and **pipeline-rnd** (improve loop). The evaluator's scope comes from the profile; a
  ci-fix PR's proof is its CI-DOCTOR evidence.
- **backlog-groom opens its own `groom-proposed` issue** per pick.
- **Paging.** REST lists page with `page=N`, never `gh --paginate`.
- **Paths.** Only `repos/<owner>/<repo>/…`; there is no search.
- **Permission denials.** A tooling denial is neither the service's answer nor a retry signal.
- **Hub body budget.** Relocate the overflow, and never move what groom parses.
