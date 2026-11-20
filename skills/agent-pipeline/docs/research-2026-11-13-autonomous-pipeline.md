# Autonomous development pipeline: review and research

*2026-11-13. Covers agent-pipeline core 1.x and the 2.0.0 changes made from this review.*

> **Correction, 2026-11-14.** The first draft of this review read a stale local clone (`f429f16`, 2026-10-23). By
> then GitHub's `main` (`c3985c6`, 2026-11-03) already had:
> - the `ci-doctor` and `pipeline-rnd` loops;
> - backlog-groom opening its own `groom-proposed` issues;
> - `page=N` paging in place of `--paginate`;
> - the hub body's size budget;
> - an evaluator scope that comes from the profile.
>
> 2.0.0 is built on that `main`, and §6 below separates what upstream had already solved from what 2.0.0 adds.

**The question.** How should `agent-pipeline` evolve into the best setup for autonomous software development that
transfers to any software project, with human-in-the-loop (HITL) checkpoints allowed? And does the pipeline's state
need a database besides GitHub?

**Method.** Three research passes over primary sources: Anthropic's docs and engineering posts, GitHub's docs and
changelog, OpenAI's docs, papers, and framework docs. All were fetched on 2026-11-13.
- Each claim carries its source.
- **UNVERIFIED** marks a claim that no official source confirmed.
- **Observed** marks a fact from this pipeline's own runs, which the docs do not state.

## Short answers

### 1. What works for autonomous development
The evidence supports eight practices. v1 already had the first three.
1. **Small, specified, checkable items.**
   - METR: Claude Opus 4.6 finishes about 12-hour tasks half the time, but only about 70-minute tasks 80% of the
     time. For GPT-5.4 the same figures are about 5.7 hours and 54 minutes ([METR data][metr-data]).
   - Agent PRs that fail are larger, touch more files, and fail CI more often ([Ehsani 2026][ehsani]).
   - On SWE-Bench Pro, scores fall as more files change ([paper][swepro]).
   - Size an item to about an expert-hour and a few files.
2. **Objective gates, never agent confidence.** Anthropic's harness forbids removing or editing tests
   ([harnesses][harness]). OpenAI dropped SWE-bench Verified after finding flawed tests in at least 59.4% of the
   problems it audited ([OpenAI][swev]). Whatever the agent claims, the test evidence must be sound and objective.
   v1's fail→pass proof job does this.
3. **A separate, skeptical evaluator, and a human merge.**
   - Maintainers would merge only about half of the agent patches that passed SWE-bench's tests ([METR][metr-merge]).
   - Anthropic found a separate skeptical evaluator "far more tractable" than having the builder critique itself
     ([harness design][harness2]).
   - "Building effective agents" says that for coding, "human review remains crucial" ([agents][bea]).
4. **Code decides what is eligible; the LLM only does judgement.** Start with "the simplest solution possible", and
   prefer fixed workflows to open-ended agents ([agents][bea]). In v1, the selection rules were prose that an LLM
   carried out.
5. **Least privilege, and treat input as untrusted.**
   - Routines act as you, and the GitHub proxy "doesn't limit which branches a push can update"
     ([cloud envs][cc-cloud]). So rules must hold on the server too.
   - Stage and vet all writes ([gh-aw security][ghaw-sec]).
   - Never let one role hold all three legs of the "lethal trifecta": private data, untrusted content, and a way to
     send data out ([Willison][trifecta]).
6. **Every run leaves a record.** A routine's run status describes "how the session ended, not whether Claude
   completed the work" ([routines][cc-routines]).
7. **Few, cheap human decisions, with their latency measured.** 67.9% of rejected agent PRs got no explicit feedback
   ([Nakashima 2026][nakashima]). Human attention is the bottleneck.
8. **Learning goes through reviewed changes.** The harness posts keep durable state in files and git history
   ([harnesses][harness]). Memory nobody reviews lets injected instructions persist.

### 2. What makes it transferable
The core may assume only four things about a repo:
- it is on GitHub;
- it has CI, or it runs in a reduced mode without CI;
- a profile states its facts;
- a human approver exists.

Everything stack-specific stays in the profile (`components`, CI names, the proof job) or a local routine (the audit
lens).

**"CI is the only evidence" is the property that makes the pipeline stack-agnostic.** A Windows or MFC build, or a
hardware-in-the-loop test, that the Linux sandbox cannot run still proves itself in CI.

**Vendoring the core stays.** Cloud sessions do not load the plugins a repo's settings enable
([plugins][cc-plugins]).

**2.0.0 adds four portable pieces:**
- a control plane with tests;
- rulesets generated from the profile;
- a ledger that needs no setup;
- `check.py --doctor`.

### 3. Do you need a database?
**Not for the work.** GitHub holds the work items, the approvals and the idempotency markers, and should keep them,
because that is where humans act.

The real gap was a **run ledger**. It is now one record per run, in Turso when configured, otherwise in git. Tokens
and cost come from OpenTelemetry. Durable-execution engines are overkill here (§5).

## 1. Platform facts (Claude Code)
| Fact | Source |
|---|---|
| Routines are now called "scheduled tasks", and are in research preview. | [routines][cc-routines] |
| Triggers are schedule, an API (`/fire` with a per-task bearer token), and GitHub events. | [routines][cc-routines] |
| GitHub events cover pull requests, issues and releases. Comments, reviews and check runs are not in the list. | [routines][cc-routines] |
| Filters exist for pull requests only: author, title, body, branches, labels, draft, merged. No actor allowlist is documented. | [routines][cc-routines] |
| Events over the per-task and per-account hourly caps are dropped, not queued. Every event starts its own session. | [routines][cc-routines] |
| Cron cannot run more often than hourly. Scheduled runs are capped at 100 an hour per account. | [routines][cc-routines] |
| `/fire` takes an optional `text`, up to 65,536 characters and marked untrusted. It has no idempotency key, and returns a session id without waiting. | [routines-fire][cc-fire] |
| Each run clones each repo fresh from its default branch. | [routines][cc-routines] |
| Network access defaults to Limited. Environment variables are visible to everyone who uses the environment. Setup scripts are cached. | [cloud envs][cc-cloud] |
| GitHub GraphQL is rejected by the proxy, so `gh pr` and `gh issue` fail, while `gh api` REST works. Search is refused too (observed). | [cloud envs][cc-cloud] |
| Commits and PRs "carry your GitHub user". A rule "that access can bypass doesn't block a run's push". | [routines][cc-routines] |
| `performed_via_github_app.slug == "claude"` on routine posts is **observed** and works in production. The docs don't state it (UNVERIFIED). | — |
| Hooks run in cloud sessions. A multi-repo session reads only `enabledPlugins` and `extraKnownMarketplaces` from each repo's settings, so no repo hooks. | [cloud envs][cc-cloud], [settings][cc-settings] |
| Repo `.claude/skills/`, `.claude/agents/` and `.claude/commands/` load in cloud sessions. Plugins enabled in the repo's settings do not. | [settings][cc-settings], [plugins][cc-plugins] |
| A Stop hook can block with `decision: "block"`. After 8 consecutive blocks the next one is overridden. `stop_hook_active` tells the hook it is already continuing. | [hooks][cc-hooks] |
| OpenTelemetry works in cloud sessions: `claude_code.cost.usage`, `token.usage`, `pull_request.count`, and `api_request` events with `cost_usd`, all tagged `ccr.session.id`. | [monitoring][cc-otel] |
| A network secret attaches a header for the hosts you list, and those hosts skip the allowlist. | [cloud envs][cc-cloud] |
| `claude -p --output-format json` returns `total_cost_usd`, which is a client-side estimate. `--json-schema` gives structured output; there are also `--max-turns` and `--max-budget-usd`. | [headless][cc-headless], [cost][cc-cost] |
| `claude-code-action` takes an API key, `CLAUDE_CODE_OAUTH_TOKEN` (subscription), or OIDC. It triggers on `issue_comment`, `pull_request` and `schedule`, and loads `.claude/`, CLAUDE.md and `.mcp.json` from the base branch on PRs. | [GH Actions][cc-gha], [security.md][cca-sec] |
| Managed Agents (beta): scheduled deployments with minute-level cron, a per-run `budget`, run history, and webhooks. Billed by API key. | [managed agents][ma], [scheduled][ma-sched] |
| Agent SDK orchestrators cannot use claude.ai login. | [agent SDK][cc-sdk] |
| Claude Code reads AGENTS.md natively from v2.1.277 when there is no CLAUDE.md. A CLAUDE.md that imports `@AGENTS.md` works everywhere. | [memory][cc-memory] |

## 2. What others do

### GitHub Copilot coding agent
- **Who can trigger it:** only users with write access.
- **Where it pushes:** only to its own `copilot/` branch, or to the existing PR's branch.
- **Approval:** it cannot approve or merge, and the person who asked for a PR cannot approve it.
- **CI:** Actions on its PRs wait for "Approve and run workflows".
- **Untrusted input:** comments from users without write access are never shown to the agent, and HTML comments
  are stripped.

Source: [risks and mitigations][copilot-risks].

### GitHub Agentic Workflows (gh-aw, GA 2026-10-28)
- **Structure:** Markdown with frontmatter, compiled to a `.lock.yml` Actions workflow ([repo][ghaw-repo],
  [GA][ghaw-ga]).
- **Safe outputs:** the agent job is read-only. Its writes are saved as artifacts, checked by a threat-detection job,
  and applied by separate jobs with minimal permissions. Each write type has a cap ([architecture][ghaw-arch],
  [safe outputs][ghaw-safe]).
- **Who can trigger it:** `roles` defaults to admin, maintainer and write. Fork PRs are blocked. A `label_command`
  removes its label once it fires ([triggers][ghaw-trig]).
- **Principles:** "defense in depth, don't trust agents with secrets, stage and vet all writes, and log everything"
  ([security post][ghaw-sec]).

v2's `pipeline.py post` is the in-session form of safe outputs.

### Codex and the open standards
- **`codex exec`:** a read-only sandbox by default, with `--output-schema` for structured output
  ([non-interactive][codex-exec]).
- **Codex review:** flags only P0 and P1 issues, with its rules in AGENTS.md ([review][codex-review]).
- **The Agentic AI Foundation** (Linux Foundation, 2025-12-09) took in MCP, goose and AGENTS.md ([LF][aaif]).
- **Agent Skills** moved to the foundation on 2026-10-22 ([Anthropic][skills-aaif]).

The role prompts are plain Markdown, which keeps the door open to other runners.

### Spec-driven development (for the "features from a human spec" phase)
- **GitHub Spec Kit:** four phases "with clear checkpoints". Its artifacts are `spec.md`, `plan.md` and `tasks.md`,
  plus a constitution. Open questions are marked `[NEEDS CLARIFICATION]` ([spec-driven.md][speckit]).
- **Kiro:** `requirements.md` in EARS form ("WHEN … THE SYSTEM SHALL …"), then `design.md` and `tasks.md`. Its
  "Quick Spec" mode skips the approval gates between phases, so the normal flow has them ([Kiro specs][kiro]).

## 3. Evidence on agent PRs
- **AIDev:** 456k agent PRs. Acceptance was Codex 64%, Devin 49%, Copilot 35%: 15–40 points below humans, and worst
  on features ([AIDev][aidev]).
- **Claude Code PRs:** 83.8% merged; 54.9% of those were merged without changes ([Watanabe][watanabe]).
- **Why agent PRs fail:** duplicates, unwanted features, and no reviewer engagement ([Ehsani][ehsani]).
- **METR's productivity study:** experienced developers were 19% slower with AI while believing they were 20% faster
  ([METR][metr-rct]). The 2026 follow-up is, in METR's words, "a bad proxy" ([update][metr-2026]).
- **What this means:** small items, a separate evaluator, a human merge, and measuring outcomes rather than activity
  — the scorecard's first-pass rate, reverts and human latency.

## 4. Security
- **Injected issues.** A malicious public issue led an agent to leak private-repo data into a public PR
  ([Invariant][invariant]). Issue text put into the prompts of write-token agents affected several AI Actions
  ([Aikido][promptpwnd]).
- **`claude-code-action`** checks that the triggering user has write access. It calls `allowed_non_write_users` "a
  significant security risk" ([security.md][cca-sec]).
- **Meta's "Rule of Two":** an agent should never hold all three trifecta capabilities unsupervised ([Meta][rule2]).
- **What 2.0.0 adopts:**
  - writes go through one gateway, with per-role caps;
  - hidden HTML is stripped from requirements, and flagged;
  - `write-guard.py` blocks merges, reviews, closes, approvals, settings changes and other repos;
  - rulesets have no bypass actors;
  - worktrees, so a PR under review can never replace the hooks.
- **Next:**
  - give routines an environment with network "None", or one without connectors;
  - a bot identity (§7).

## 5. Where state lives (the database question)

### State, and where each kind belongs
| State | Home | When a database would be worth it |
|---|---|---|
| Work items and lifecycle | issues, PRs, labels (issue fields optional) | never, for this pipeline |
| Human decisions | the `groomed` label and `#redo`, checked against the event's actor and app | never: approvals belong where people act |
| Idempotency keys | marker comments, counted only on routine posts | when concurrent sessions work the same key, or writes near 80/min or 500/h |
| Claims (locks) | the `groomed/<N>` branch: the push is the claim, and force-push is blocked | several sessions per role at once, needing claims that expire |
| **Run ledger (new)** | **Turso when configured, else one JSON file per run on `pipeline-ledger`** | live SQL across repos |
| Metrics history | the scorecard comment, plus `metrics/<week>.json` on the ledger branch (DuckDB can query them) | never: it is derived data |
| Agent learnings | CLAUDE.md and rules, through reviewed PRs | never: unreviewed memory lets injections persist |
| Tokens and cost | OpenTelemetry, joined on `ccr.session.id` | that is a telemetry backend, not a database |
| Cross-repo portfolio | a weekly read-only job over each repo's ledger | about 5+ repos, or a tool outside GitHub that needs live data |

Sources: GitHub REST rate limits are 5,000 an hour per user, shared by every routine because they all act as you,
plus secondary limits of 80 content-creating requests a minute and 500 an hour ([rate limits][gh-rate]). Contents API
writes conflict with 409 ([contents][gh-contents]).

### Options considered and rejected
- **Durable execution** — LangGraph checkpointers, Temporal, Inngest, Restate. Each persists work that is still in
  progress ([LangGraph][lg], [Temporal][temporal], [Inngest][inngest], [Restate][restate]). The roles are short,
  re-runnable jobs that rebuild state from GitHub each run, and markers make their writes safe to repeat, so these
  are overkill.
- **Check runs and statuses as a store.** Only an App can create check runs, and since 2026-10-01 both are deleted
  after the retention period ([checks][gh-checks], [retention][gh-retention]).
- **Projects v2.** It has REST since 2025-09 ([changelog][gh-projects]), but sessions cannot reach it. Use it as a
  human board.
- **Git notes and tags.** The proxy only pushes branches ([cloud envs][cc-cloud]).
- **Lark Base.** It rejects concurrent writes, and needs an `app_id`/`app_secret` exchange for a 2-hour token
  ([batch create][lark-batch], [token][lark-token]). It is fine as a dashboard copy written by one weekly job.
- **Supabase.** Free projects pause after a week of low activity ([pausing][supabase-pause]).
- **Cloudflare D1.** Its REST API is "best suited for administrative use" ([D1 limits][d1]).
- **Turso was chosen.** It takes HTTP `POST /v2/pipeline` with a bearer token, which a network secret can supply
  ([Turso HTTP][turso]).

## 6. Review of v1 (core `77a9c17`, GitHub `main` as of 2026-11-03)
**Already solved upstream** (between 2026-10-24 and 11-02), and kept in 2.0.0:
- **Unapproved picks.** backlog-groom opens a `groom-proposed` issue per pick, so approving is one label. Before,
  six picks sat unapproved for 12 days.
- **Paging.** `page=N` paging, because `--paginate` follows numeric-ID links the proxy refuses.
- **Paths.** Only `repos/<owner>/<repo>/…` paths reach GitHub.
- **Permission denials.** A tooling permission denial is neither the service's answer nor a retry signal.
- **The hub body** has a 60,000-codepoint budget under GitHub's 65,536 cap. Overflow is relocated, never truncated.
- **ci-doctor:** a capped heal loop for red CI.
- **pipeline-rnd:** a capped improvement loop. The pilot repo removed it on 2026-11-03, because every write to the
  upstream repo was refused.
- **Evaluator scope.** `evaluate.heads`, plus an opt-in label an approver adds.

**Keep:**
- the three layers, and the test that keeps project nouns out of the core;
- prompts read from git at run time;
- the fail→pass proof job;
- a read-only evaluator that runs once per SHA;
- app-field approval checks;
- the WIP limit, DRY RUN and REST-only access;
- the outcome-only scorecard.

**Fixed in 2.0.0:**
1. **Selection was prose.** Implementer G1–G3, evaluator eligibility, redo screening and groom-item matching were
   carried out by an LLM, with no tests. They are now `core/bin/gates.py`, with tests.
2. **Hooks ran from the checked-out branch** (v1's own pitfall). The evaluator and redo-executor checked out PR heads,
   so a PR could switch off `push-guard.py`. Work now happens in worktrees, and the session checkout stays on the
   integration branch.
3. **Routines act as the owner, with only prompt prose against merges.** Fixed with `write-guard.py`, rulesets with
   no bypass, and a guardrail-breach row on the scorecard.
4. **No run ledger.** No-op and crashed runs were invisible. Fixed with the ledger, the Stop hook, and missed-slot
   detection on the scorecard.
5. **The scorecard listed every issue ever** (`scorecard.py:102`, `:198`). Fixed with `since=`.
6. **The core version was an opaque tree hash.** Fixed with `core/VERSION` and the changelog.
7. **The in-flight claim was check-then-act.** Fixed: the `groomed/<N>` push is the claim.

**Open (roadmap):**
- cron is the only trigger;
- there is one change type for the main flow (a traced defect), besides ci-doctor's CI fixes;
- the improvement loop cannot write upstream from a cloud session;
- routines run under your own identity.

## 7. Roadmap
- **Phase 2: features from a human spec.**
  - **Spec drafting.** A human issue labelled `spec` goes to a `spec-writer` role. It drafts EARS acceptance
    criteria, design notes, `[NEEDS CLARIFICATION]` markers, and a slice plan of about 1 expert-hour per slice.
  - **Approval.** A human resolves the markers and adds `spec-approved`, which is checked by actor, like `groomed`.
  - **Slices.** The writer creates sub-issues over REST, which enter gated-implementer as they are. The proof job
    works unchanged, because new tests fail on the base.
  - **Groom.** Already done upstream: groom opens `groom-proposed` issues itself, and title matching stays only as
    the fallback.
  - **Lark Base as a spec source.** A deterministic sync job reads the rows marked ready in a Lark Base table. It is
    a scheduled GitHub Action with no LLM, and it holds the Lark app credentials as Actions secrets.
    - **Into GitHub.** It opens one `spec` issue per row in the repo the row names, with a link back to the record.
    - **Back to Lark.** It writes the issue, PR and release status back to the row, so product owners follow
      progress in Lark.
    - **Trust boundary.** The agents never hold Lark credentials, and the approval stays the GitHub `spec-approved`
      label.
    - **Why one serial job.** A table rejects concurrent writes ([batch create][lark-batch]), and every token comes
      from an `app_id`/`app_secret` exchange ([token][lark-token]). So this is one writer, outside the sandbox.
- **Phase 3: event triggers.**
  - **Redo.** A PR `labeled: redo` event, with a label filter, replaces the `#redo` comment as the trigger. The
    feedback stays in comments.
  - **Issues.** `labeled` events wake `select`, which exits fast when there is nothing to do.
  - **Evaluator.** A small Action on `check_suite: completed` calls `/fire`.
  - **Cron** stays as a daily sweeper, because events over the caps are dropped.
- **Phase 4: identity and runtime.** A bot identity through `claude-code-action` with a custom GitHub App, keeping
  subscription billing through `CLAUDE_CODE_OAUTH_TOKEN`. The alternative is Managed Agents: API-billed, with a
  per-run budget and run history. Either way you could approve agent PRs, rulesets could target the bot, and
  comments could trigger work.
- **Phase 5.**
  - **Learning loop.** pipeline-rnd already mines last week's evidence into one reviewed change per run. What it
    lacks is a write route upstream. A run that writes only its own repo's profile and rules (`rnd.paths`), plus a
    proposal for the upstream change, would work today. The ledger and scorecard metrics give it better evidence.
  - **Evals.** pass^k on a sandbox repo with seeded defects before each core release. Start with 20–50 tasks drawn
    from real failures, and grade outcomes ([evals][evals]).
  - **Roll-out.** A canary repo before every other repo.
  - **Portfolio.** A read model in Turso once you run about 5 repos.
- **Autonomy (documented only).** A human merges every PR. A later "earned auto-merge" would apply only to
  tests-only and docs-only PRs, after an evaluator PASS and green CI, with a track record of at least 20 merges, at
  least 80% first-pass, and no reverts. A revert would turn it back off, and turning it on would itself be a
  human-merged PR to `pipeline.yml`.

## About the sources
The research passes fetched every linked source on 2026-11-13. Figures are quoted as each source states them. The
inline links lead to the originals, and their targets are listed below.

[cc-routines]: https://code.claude.com/docs/en/routines
[cc-fire]: https://platform.claude.com/docs/en/api/claude-code/routines-fire
[cc-cloud]: https://code.claude.com/docs/en/cloud-environments
[cc-settings]: https://code.claude.com/docs/en/settings
[cc-plugins]: https://code.claude.com/docs/en/plugins/install
[cc-hooks]: https://code.claude.com/docs/en/hooks
[cc-otel]: https://code.claude.com/docs/en/monitoring-usage
[cc-headless]: https://code.claude.com/docs/en/headless
[cc-cost]: https://code.claude.com/docs/en/agent-sdk/cost-tracking
[cc-gha]: https://code.claude.com/docs/en/github-actions
[cca-sec]: https://github.com/anthropics/claude-code-action/blob/main/docs/security.md
[cc-sdk]: https://code.claude.com/docs/en/agent-sdk/overview
[cc-memory]: https://code.claude.com/docs/en/memory
[ma]: https://platform.claude.com/docs/en/managed-agents/overview
[ma-sched]: https://platform.claude.com/docs/en/managed-agents/scheduled-deployments
[harness]: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
[harness2]: https://www.anthropic.com/engineering/harness-design-long-running-apps
[bea]: https://www.anthropic.com/engineering/building-effective-agents
[evals]: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
[skills-aaif]: https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation
[copilot-risks]: https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations
[ghaw-repo]: https://github.com/githubnext/gh-aw
[ghaw-ga]: https://github.blog/changelog/2026-10-28-github-agentic-workflows-generally-available
[ghaw-arch]: https://github.github.com/gh-aw/introduction/architecture/
[ghaw-safe]: https://github.github.com/gh-aw/reference/safe-outputs/
[ghaw-trig]: https://github.github.com/gh-aw/reference/triggers/
[ghaw-sec]: https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/
[codex-exec]: https://learn.chatgpt.com/docs/non-interactive-mode
[codex-review]: https://learn.chatgpt.com/docs/third-party/github
[aaif]: https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation
[speckit]: https://github.com/github/spec-kit/blob/main/spec-driven.md
[kiro]: https://kiro.dev/docs/specs/
[aidev]: https://arxiv.org/abs/2507.15003
[ehsani]: https://arxiv.org/abs/2601.15195
[nakashima]: https://arxiv.org/abs/2602.04226
[watanabe]: https://arxiv.org/abs/2509.14745
[metr-rct]: https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
[metr-2026]: https://metr.org/blog/2026-02-24-uplift-update/
[metr-data]: https://metr.org/assets/benchmark_results_1_1.yaml
[metr-merge]: https://metr.org/notes/2026-03-10-many-swe-bench-passing-prs-would-not-be-merged-into-main/
[swev]: https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
[swepro]: https://arxiv.org/abs/2509.16941
[invariant]: https://invariantlabs.ai/blog/mcp-github-vulnerability
[promptpwnd]: https://aikido.dev/blog/promptpwnd-github-actions-ai-agents
[trifecta]: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
[rule2]: https://ai.meta.com/blog/practical-ai-agent-security/
[gh-rate]: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
[gh-contents]: https://docs.github.com/en/rest/repos/contents
[gh-checks]: https://docs.github.com/en/rest/checks/runs
[gh-retention]: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository
[gh-projects]: https://github.blog/changelog/2025-09-11-a-rest-api-for-github-projects-sub-issues-improvements-and-more/
[lg]: https://docs.langchain.com/oss/python/langgraph/persistence
[temporal]: https://docs.temporal.io/workflow-execution/event
[inngest]: https://www.inngest.com/docs/learn/how-functions-are-executed
[restate]: https://docs.restate.dev/concepts/durable_execution
[lark-batch]: https://open.larksuite.com/document/server-docs/docs/bitable-v1/app-table-record/batch_create
[lark-token]: https://open.larksuite.com/document/server-docs/getting-started/api-access-token/auth-v3/tenant_access_token_internal
[supabase-pause]: https://supabase.com/kb/faqs/platform/free-project-pausing
[d1]: https://developers.cloudflare.com/d1/platform/limits/
[turso]: https://docs.turso.tech/sdk/http/reference
