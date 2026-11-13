# Agent pipeline reference

## 1. RemoteTrigger body (create / update)
The shape below mirrors what RemoteTrigger `get` returns for a live routine. When in doubt, `get` an existing routine
first and copy its shape.

```json
{
  "name": "[<repo-name>][<role>][<write action>] <title>",
  "cron_expression": "<cron, UTC>",
  "enabled": false,
  "job_config": {
    "ccr": {
      "environment_id": "<routine.environment_id, or project.environment_id>",
      "events": [
        {"data": {"message": {"content": "<check.py --launcher output>", "role": "user"},
                  "parent_tool_use_id": null, "session_id": "", "type": "user", "uuid": "<new uuid4>"}}
      ],
      "session_context": {
        "allowed_tools": ["<routine.tools, or the role's front-matter tools>"],
        "model": "<routine.model>",
        "sources": [{"git_repository": {"url": "https://github.com/<owner/repo>"}}]
      }
    }
  }
}
```
- **Name.** Use `routine.name` when it is set. Otherwise build `[<repo>][<role>][<write action>] <title>`, for example
  `[orders-api][release-manager][create PR] Release to master sync`.
- **Sources.** The routine's `sources`, or `[project.repo]`. A session with several repos starts in the folder above
  the clones and loads no repo hooks, so keep extra sources to read-only routines such as an audit.
- **Enabled.** `status: active` maps to `enabled: true`. Create every routine disabled, DRY RUN it, then enable it.
- **Environment.** A routine's own `environment_id` overrides the project's. Use that to run read-only roles in an
  environment with network access "None", where GitHub traffic still flows through the proxy. Confirm this with a
  DRY RUN before relying on it.

## 2. Hook registration (`.claude/settings.json`)
Merge these entries into the repo's existing `hooks.PreToolUse` list, and add the `Stop` entry:

```json
{"matcher": "Bash",
 "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/routines/core/hooks/push-guard.py\"", "timeout": 10}]},
{"matcher": "Bash|mcp__.*[Gg]it[Hh]ub.*",
 "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/routines/core/hooks/write-guard.py\"", "timeout": 10}]},
{"matcher": "Bash|mcp__.*[Gg]it[Hh]ub.*",
 "hooks": [{"type": "command", "command": "if [ \"$CLAUDE_CODE_REMOTE\" = \"true\" ]; then exec \"$CLAUDE_PROJECT_DIR/.claude/routines/core/hooks/require-ai-marker.sh\"; fi", "timeout": 10}]}
```

```json
"Stop": [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/routines/core/hooks/run-ledger.py\"", "timeout": 60}]}]
```

- **Every hook acts only in cloud sessions** (`CLAUDE_CODE_REMOTE` is `"true"`). The repo's `.claude/settings.json`
  is shared with teammates, so a repo-wide check would block their own local work.
  - Routines need these checks, because cloud sessions never read `~/.claude`.
  - Locally, the owner's global `~/.claude/hooks/require-ai-marker.sh` still runs. Keep the core copy out of
    `.claude/hooks/`, because the global copy steps aside when a repo copy exists there.
  - If `jq` is missing, the marker hook does nothing.
- **The push guard** reads the integration and production branch names from `pipeline.yml`.
- **The write guard** reads `project.repo` from `pipeline.yml`. It blocks:
  - merges, reviews, closing or reopening;
  - the approval label;
  - ref deletes and moves of protected branches;
  - settings changes;
  - writes to any other repo.
- **The ledger hook** blocks a run that has not finished, once, with the `finish` command as the reason. If the run
  still does not finish, the hook records it as failed. It never blocks on a storage error.
- **Hook scripts run from the session checkout**, and the session checkout stays on the integration branch
  (`core/shared.md`, Worktrees). That is why the guards always come from reviewed code.
- **Hooks take effect from the default branch.** A hook registered in `.claude/settings.json` applies only once it
  reaches the default branch.

## 3. Markers
`pipeline.py post` writes line 1 from `--marker` and line 2 itself. `select` reads markers only from app-`claude`
posts.

| Marker (line 1) | Written by | Read by |
|---|---|---|
| `hub.marker` (body) | the audit (`post --kind hub-body`) | humans; identifies the hub |
| `<!-- AUDIT-CHANGELOG -->` | the audit | humans |
| `<!-- BACKLOG-GROOM -->` + `<!-- groom-key: … -->` | backlog-groom | groom (dedup), `select` (the requirement for gated-implementer and pr-evaluator), scorecard |
| `<!-- GATE issue=<n> gate=<Gx> base=<sha> -->` | gated-implementer | the gateway (`dedupe: gate`: no repeat skip comments) |
| `<!-- IMPLEMENTATION-RUN base=<sha> -->` | gated-implementer | backlog-groom (design-call skips) |
| `<!-- PR-EVALUATION sha=<head> verdict=<v> -->` | pr-evaluator | `select` (once per SHA; CI-MISSING re-entry), redo-executor (findings) |
| `<!-- REDO-DONE for=<comment id> sha=<sha> status=<s> -->` | redo-executor | `select` (answered), scorecard |
| `<!-- ROUTINE-SCORECARD week=<YYYY-Www> -->` | scorecard | the gateway (`dedupe: marker`: once per week) |
| `<!-- CI-DOCTOR sig=<signature> -->` (issue body) | ci-doctor | the gateway (one open issue per signature), ci-doctor, pipeline-rnd |
| `<!-- CI-DOCTOR-FLAKY -->` (issue body) | ci-doctor | the gateway (one open issue), ci-doctor (a flake comment), pipeline-rnd |
| `<!-- CI-DOCTOR-VERIFIED sha=<head> -->` | ci-doctor | the gateway (once per SHA), humans |
| `<!-- RND-LOG week=<YYYY-Www> -->` (PR body) | pipeline-rnd | pipeline-rnd (its rolling PR), humans |
| `<!-- agent-pipeline core=<version>+<tree> run=<session> -->` (line 2) | the gateway, on every post | humans: which core ran, and the session to look up |

**Labels to create at install.** Every routine reads or writes these; no routine creates one:
- `groomed` and `groom-proposed`;
- the loops' `ci-failure`, `needs-human`, `ci-blocked`, `autofix-1` … `autofix-<max>`, `flaky`, `agent-pause`, `rnd`
  and `rnd-stop`;
- `evaluate.opt_in_label`.

Readers count a marker only on an app-`claude` post. Human commands (`#redo`) and approvals (the `groomed` label) count
only when app-null and made by an approver.

## 4. The run ledger
Every run stores one record, from `pipeline.py begin`, completed by `pipeline.py finish`. The Stop hook makes sure
the record is written.

**Record (schema v1):**
- `repo`, `routine`, `role`;
- `session` (`CLAUDE_CODE_REMOTE_SESSION_ID`, or `local-<id>`), `trigger`, `dry_run`;
- `started_at`, `ended_at`;
- `outcome` (`wrote` | `noop` | `gated` | `failed`) and a one-line `summary`;
- `items` (`[{kind, number, result}]`) and `writes` (each gateway write, with its URL);
- `core` (`<VERSION>+<tree>`), `model`, and `fallback` when Turso failed.

**Where it goes:**
- **git (the default, zero setup).** One file per run, `runs/YYYY/MM/DD/<routine>--<session>.json`, on the
  `ledger.branch` branch (`pipeline-ledger`).
  - It is written through the Contents API, with `[skip ci]` in the commit message, and retried on 409.
  - The first run creates the branch as an orphan.
  - The scorecard also writes `metrics/<YYYY-Www>.json` there.
  - DuckDB or `jq` can query the files directly.
- **Turso (when `ledger.turso_url` is set).** Records are upserted into `pipeline_runs`. When Turso fails, the
  record goes to git with `fallback` set, so it is never lost. The scorecard reads both. To set it up:
  1. Create a database, and put its `libsql://…` URL in `ledger.turso_url`.
  2. Create the table once, locally: `PIPELINE_LEDGER_TOKEN=<token> python3 .claude/routines/core/bin/pipeline.py ledger init-db`.
  3. In the routines' cloud environment, add a **network secret** for the database host that sends
     `Authorization: Bearer <token>`. The token then never enters the sandbox.

  ```sql
  CREATE TABLE IF NOT EXISTS pipeline_runs (session TEXT NOT NULL, routine TEXT NOT NULL, repo TEXT NOT NULL,
    started_at TEXT NOT NULL, outcome TEXT, record TEXT NOT NULL, PRIMARY KEY (session, routine));
  CREATE INDEX IF NOT EXISTS pipeline_runs_repo_started ON pipeline_runs (repo, started_at);
  ```

**Tokens and cost: OpenTelemetry** (optional, no code). Claude Code exports cost and token metrics from cloud
sessions when the environment sets these variables:
```
CLAUDE_CODE_ENABLE_TELEMETRY=1
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=https://<collector>
OTEL_EXPORTER_OTLP_HEADERS=<auth header for the collector>
```
- Add the collector's domain to the environment's allowed domains.
- Each metric carries `ccr.session.id`, which equals the ledger's `session`. Join on it to get cost per run.
- Environment variables are visible to everyone who uses the environment. Use server-managed settings where you have
  them.

## 5. Rulesets
`python3 <skill>/check.py <repo> --rulesets` prints the rulesets for this profile as a JSON array:
- **integration:** no deletion, no force-push, changes only through a PR, and the `ci.required` checks required.
- **production** (when it is a separate branch): no deletion, no force-push, changes only through a PR.
- **the ledger branch:** no deletion, no force-push.

There are no bypass actors. Routines act as the owner, so a rule the owner can bypass would not stop a routine either.
Required approvals stay at 0: routine PRs are authored by the owner's account, and GitHub forbids approving your own
PR.

To apply them:
```bash
python3 <skill>/check.py <repo> --rulesets > /tmp/rulesets.json
jq -c '.[]' /tmp/rulesets.json | while read -r r; do printf '%s' "$r" | gh api -X POST repos/<owner>/<repo>/rulesets --input -; done
```
On private repos, rulesets need GitHub Pro, Team or Enterprise. `check.py --doctor` reports when they are missing.
The "changes only through a PR" rule also stops people pushing straight to the branch: drop that rule from the JSON if
your team pushes directly.

## 6. Cloud environment setup script
The control plane needs PyYAML, and the cloud image may lack it. Add this to the environment's setup script, which is
cached between runs:
```bash
python3 -m pip install -q pyyaml
```
`pcfg.py` falls back to installing it at run time, which needs the environment's network access to reach PyPI.
