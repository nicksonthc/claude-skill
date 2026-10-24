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
      "environment_id": "<project.environment_id>",
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
  the clones and loads no repo hooks.
- **Enabled.** `status: active` maps to `enabled: true`. Create every routine disabled, DRY RUN it, then enable it.

## 2. Hook registration (`.claude/settings.json`)
Merge these entries into the repo's existing `hooks.PreToolUse` list:
```json
{"matcher": "Bash",
 "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/routines/core/hooks/push-guard.py\"", "timeout": 10}]},
{"matcher": "Bash|mcp__.*[Gg]it[Hh]ub.*",
 "hooks": [{"type": "command", "command": "if [ \"$CLAUDE_CODE_REMOTE\" = \"true\" ]; then exec \"$CLAUDE_PROJECT_DIR/.claude/routines/core/hooks/require-ai-marker.sh\"; fi", "timeout": 10}]}
```
- **The marker hook runs only in cloud sessions.** The repo's `.claude/settings.json` is shared with teammates, so a
  repo-wide marker check would block their own local `gh` writes. Routines need the check, because cloud sessions
  never read `~/.claude`. Locally, the owner's global `~/.claude/hooks/require-ai-marker.sh` still runs: keep the core
  copy out of `.claude/hooks/`, because the global copy steps aside when a repo copy exists there. If `jq` is missing,
  the hook does nothing.
- **The push guard** acts only when `CLAUDE_CODE_REMOTE` is `"true"`. It reads the integration and production branch
  names from `pipeline.yml`.

## 3. Markers
| Marker (line 1) | Written by | Read by |
|---|---|---|
| `hub.marker` (body) | the audit | humans; identifies the hub |
| `<!-- AUDIT-CHANGELOG -->` | the audit | humans |
| `<!-- BACKLOG-GROOM -->` + `<!-- groom-key: … -->` | backlog-groom | groom (dedup), the implementer and evaluator (requirement source), scorecard |
| `<!-- GATE issue=<n> gate=<Gx> base=<sha> -->` | gated-implementer | gated-implementer (no repeat skip comments) |
| `<!-- IMPLEMENTATION-RUN base=<sha> -->` | gated-implementer | backlog-groom (design-call skips) |
| `<!-- PR-EVALUATION sha=<head> verdict=<v> -->` | pr-evaluator | pr-evaluator (once per SHA), redo-executor (findings) |
| `<!-- REDO-DONE for=<comment id> sha=<sha> status=<s> -->` | redo-executor | redo-executor (answered), scorecard |
| `<!-- ROUTINE-SCORECARD week=<YYYY-Www> -->` | scorecard | scorecard (once per week) |
| `<!-- CI-DOCTOR sig=<signature> -->` | ci-doctor (issue body) | ci-doctor (one issue per signature), pipeline-rnd |
| `<!-- CI-DOCTOR-FLAKY -->` | ci-doctor (issue body) | ci-doctor (append a flake), pipeline-rnd |
| `<!-- CI-DOCTOR-VERIFIED sha=<head> -->` | ci-doctor | ci-doctor (once per SHA), humans |
| `<!-- RND-LOG week=<YYYY-Www> -->` | pipeline-rnd (PR body) | pipeline-rnd (its rolling PR), humans |
| `<!-- agent-pipeline core=<tree> run=<session> -->` (line 2) | every routine | humans: which core ran, and a link to the run log |

Labels the loops use (create them at install): `ci-failure`, `needs-human`, `ci-blocked`, `autofix-1` … `autofix-<max>`,
`flaky`, `agent-pause`, `rnd`, `rnd-stop`, and `evaluate.opt_in_label`.

Readers count a marker only on an app-`claude` post. Human commands (`#redo`) and approvals (the `groomed` label) count
only when app-null and made by an approver.
