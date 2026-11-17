# Refresh workflow: the scheduled, parallel refresh

Load this when scheduling the index: the GitHub Actions workflow (one job per repo, then one contracts job),
reaching a private database from the runner, choosing the runner, the container image for the API, the one-time
setup and the failure table. Other CI systems work the same way; the shape is plan -> parallel index -> one links job.

## 1. The workflow

**Not yet proven in production in this exact form.** The source project hard-codes the repo names in the plan step
and has one `if:` checkout step per repo. This version reads the repo config file (`kb-repos.json`, indexer.md
section 1) and emits a matrix of objects, so ONE checkout step serves every repo and the list lives in one place
(P56). Everything else (concurrency, the timeouts, the env, the index and links steps) is as it ran.

```yaml
# file: .github/workflows/kb-refresh.yml
name: Refresh knowledge

# Weekly and on demand: read each repository at its production branch and update the knowledge base. Runs on a
# self-hosted runner (embedding is CPU-bound), never on the API server. It checks the repos out with a read-only
# token, runs the indexer against the database, and keeps no repo credentials anywhere else. Nothing is pushed.
#
# In parallel: one job per repository (max-parallel sized from memory), then one job that builds the links between
# systems from all of them, checks the golden questions and, if asked, runs the paid evaluation. Progress is saved
# every 40 files, so a job that stops is continued by the next run.
#
# A repo that fails keeps its previous index (each is written in one transaction) and the run fails, so a bad week
# shows as a red run, never as a half-updated base. The links are still rebuilt from what the base holds.
#
# GitHub environment `knowledge` (no required reviewers: a scheduled run would wait forever):
#   secrets    KB_DATABASE_URL     postgres://user:password@host:5432/db  (no ?sslmode=)
#              KB_READ_TOKEN       fine-grained token, Contents: read on the indexed repos only
#              ANTHROPIC_API_KEY   only for the optional paid evaluation
#   variables  KB_DATABASE_SSL     off | require | verify-full   (default require)
#              KB_DB_VIA_TUNNEL    "true" when the runner cannot reach the database directly (section 4)
on:
  schedule:
    - cron: '0 1 * * 1' # E10: Monday 01:00 UTC; inside the hours the self-hosted runner is up
  workflow_dispatch:
    inputs:
      only:
        description: 'Only these repos, comma-separated (blank = all)'
        type: string
        default: ''
      run_eval:
        description: 'Then ask the golden questions (calls the Anthropic API, so it costs money)'
        type: boolean
        default: false

# One refresh at a time; a second one waits instead of cancelling the first.
concurrency:
  group: kb-refresh
  cancel-in-progress: false

env:
  ONNXRUNTIME_NODE_INSTALL: skip # the embedding runtime's CPU build is bundled; don't fetch its GPU build from nuget.org

permissions:
  contents: read

jobs:
  # Which repositories this run indexes: all of them, or the ones asked for (known names only).
  plan:
    runs-on: self-hosted # E10: your runner label
    timeout-minutes: 5
    outputs:
      repos: ${{ steps.plan.outputs.repos }}
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-node@v4 # for runners without Node on the PATH
        with:
          node-version: 22
      - id: plan
        env:
          ONLY: ${{ inputs.only }} # free text: through env, validated in the script, never inlined into the shell
        run: node scripts/kb-plan.mjs

  index:
    name: Index ${{ matrix.repo.name }}
    needs: plan
    runs-on: self-hosted # a 2-core hosted runner managed about one section a second
    timeout-minutes: 240 # first-run sized; resumability, not this number, is what finishes a first run
    environment: knowledge
    strategy:
      fail-fast: false # one failed repo must not cancel the others
      max-parallel: 3 # E10: each job holds the embedding model (~1.3 GB at most); size from the runner's memory
      matrix:
        repo: ${{ fromJSON(needs.plan.outputs.repos) }}
    permissions:
      contents: read
      id-token: write # only for a cloud-credential tunnel (section 4)
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false

      # No `cache: npm`: on a self-hosted runner with a shared npm cache, setup-node's cache would unpack over it
      # while other jobs read it.
      - uses: actions/setup-node@v4
        with:
          node-version: 22

      - run: npm ci

      # The embedding model (~160 MB), downloaded once and kept between runs. Key = model + quantisation.
      - uses: actions/cache@v4
        with:
          path: ${{ runner.temp }}/models
          key: embedding-model-jina-v2-base-code-q8

      # This job's repository and branch, at the tip, one commit deep.
      - uses: actions/checkout@v7
        with:
          repository: ${{ matrix.repo.repository }}
          ref: ${{ matrix.repo.ref }}
          path: repos/${{ matrix.repo.path }}
          token: ${{ secrets.KB_READ_TOKEN }}
          persist-credentials: false

      # E9: only when the runner cannot reach the database on its own (section 4). Insert the tunnel steps here.

      - name: Index
        shell: bash
        env:
          DATABASE_URL: ${{ env.DATABASE_URL_OVERRIDE || secrets.KB_DATABASE_URL }}
          DATABASE_SSL: ${{ env.DATABASE_SSL_OVERRIDE || vars.KB_DATABASE_SSL || 'require' }}
          KB_REPOS_DIR: ${{ github.workspace }}/repos
          KB_REF: head
          KB_CONTRACTS: 'off' # built once, after every repo (the links job)
          KB_MODEL_DIR: ${{ runner.temp }}/models
          REPO: ${{ matrix.repo.name }}
        run: |
          set +e
          npm run index -- --only "$REPO" 2>&1 | tee "$RUNNER_TEMP/index.log"
          code=${PIPESTATUS[0]}
          { echo "### $REPO"; echo '```'; grep -vE '^(>|$)' "$RUNNER_TEMP/index.log"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
          exit "$code"

  # After every repository (also when one failed: it keeps its previous index): the links between systems from all
  # the indexed code, then the golden questions.
  links:
    name: Links between systems, golden questions
    needs: index
    if: ${{ !cancelled() }}
    runs-on: self-hosted
    timeout-minutes: 30
    environment: knowledge
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci

      # E9: the same tunnel steps as in the index job, if used.

      - name: Links between systems
        shell: bash
        env:
          DATABASE_URL: ${{ env.DATABASE_URL_OVERRIDE || secrets.KB_DATABASE_URL }}
          DATABASE_SSL: ${{ env.DATABASE_SSL_OVERRIDE || vars.KB_DATABASE_SSL || 'require' }}
        run: |
          set +e
          npm run contracts 2>&1 | tee "$RUNNER_TEMP/links.log"
          code=${PIPESTATUS[0]}
          { echo '### Links between systems'; echo '```'; grep -vE '^(>|$)' "$RUNNER_TEMP/links.log"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
          exit "$code"

      # Free: every file a golden question expects is still in the base. A moved or deleted file shows up here as a
      # red step, not later as a wrong answer.
      - name: Check the golden questions still point at real files
        if: ${{ !cancelled() }}
        shell: bash
        env:
          DATABASE_URL: ${{ env.DATABASE_URL_OVERRIDE || secrets.KB_DATABASE_URL }}
          DATABASE_SSL: ${{ env.DATABASE_SSL_OVERRIDE || vars.KB_DATABASE_SSL || 'require' }}
        run: npm run eval -- --check

      - name: Ask the golden questions
        if: ${{ inputs.run_eval }}
        shell: bash
        env:
          DATABASE_URL: ${{ env.DATABASE_URL_OVERRIDE || secrets.KB_DATABASE_URL }}
          DATABASE_SSL: ${{ env.DATABASE_SSL_OVERRIDE || vars.KB_DATABASE_SSL || 'require' }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          set +e
          npm run eval 2>&1 | tee "$RUNNER_TEMP/eval.log"
          code=${PIPESTATUS[0]}
          { echo '### Golden questions'; echo '```'; grep -vE '^(>|$)' "$RUNNER_TEMP/eval.log"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
          exit "$code"
```

The plan script (part of the same unproven refactor; the validation rules are the source's):

```js
// file: scripts/kb-plan.mjs
// The refresh's matrix: every repo in the repo config ($KB_REPOS_FILE, default kb-repos.json), or the ones named in $ONLY. ONLY is free text from the
// workflow_dispatch form and ends up on a command line, so it is checked: a character class, then known names only.
import { appendFileSync, readFileSync } from 'node:fs'

const fail = (m) => {
  console.log(`::error::${m}`)
  process.exit(1)
}
const { repos } = JSON.parse(readFileSync(process.env.KB_REPOS_FILE?.trim() || 'kb-repos.json', 'utf8'))
const only = (process.env.ONLY ?? '').trim()
if (only && !/^[A-Za-z0-9_./,-]+$/.test(only)) fail("'only' must be repo names separated by commas")
const names = only ? only.split(',').filter(Boolean) : repos.map((r) => r.name)
const unknown = names.filter((n) => !repos.some((r) => r.name === n))
if (unknown.length) fail(`unknown repo ${unknown.join(', ')}. Known: ${repos.map((r) => r.name).join(', ')}`)
// path: the checkout folder the indexer reads in KB_REF=head mode (ciDir when one repo is indexed at two branches).
const matrix = repos.filter((r) => names.includes(r.name)).map((r) => ({ name: r.name, repository: r.repository, ref: r.branch, path: r.ciDir ?? r.dir }))
appendFileSync(process.env.GITHUB_OUTPUT, `repos=${JSON.stringify(matrix)}\n`)
```

## 2. The index step

- `set +e`, `tee`, then `${PIPESTATUS[0]}`: the exit code of `npm run index`, not of `tee` (P61). Without it a
  failed repo is a green step.
- `KB_REF=head`: CI has only the checked-out commit; the indexer reads `HEAD` of `ciDir ?? dir` (P10).
- `KB_CONTRACTS=off`: each job indexes one repo; contracts are rebuilt once in the links job (P41).
- `KB_MODEL_DIR` under `runner.temp`, cached by `actions/cache` keyed on model name + quantisation (P54). Change the
  key when the model or dtype changes.
- The step summary carries each repo's `+added ~changed -removed =unchanged skipped blocked redacted` line.

## 3. The links job

Runs when every index job has finished, failed ones included (`if: !cancelled()`, P50): contracts from what the
base holds, then the free golden check (`eval --check`, evals.md section 2), then the paid eval only when asked.

## 4. Reaching a private database (E9)

Two shapes:

1. **Direct**: the runner reaches the database. `DATABASE_URL` from the environment secret, `DATABASE_SSL` from a
   variable. Nothing else.
2. **Tunnel**: the database is private (the usual managed-Postgres setup). Open a port-forward on the runner, point
   the URL at `127.0.0.1:<port>`, and export it for the later steps. Worked example: AWS SSM through a host that
   can reach the database.

```yaml
# file: tunnel-steps.yml   (paste into the index and links jobs where the E9 comment is)
      - name: Cloud credentials
        if: ${{ vars.KB_DB_VIA_TUNNEL == 'true' }}
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - name: Reach the database through a tunnel
        if: ${{ vars.KB_DB_VIA_TUNNEL == 'true' }}
        shell: bash
        env:
          TUNNEL_TARGET: ${{ vars.KB_TUNNEL_TARGET }} # the host that can reach the database (an instance id for SSM)
          DB_HOST: ${{ vars.KB_DB_HOST }}             # the database's private host name
          DATABASE_URL: ${{ secrets.KB_DATABASE_URL }}
        run: scripts/kb-db-tunnel.sh
```

```bash
#!/usr/bin/env bash
# file: scripts/kb-db-tunnel.sh
# The refresh's way into a private database: a port-forward 127.0.0.1:$LOCAL_PORT -> $DB_HOST:$DB_PORT, kept open for
# the rest of the job. Then it exports DATABASE_URL_OVERRIDE (the same URL, host moved to the tunnel; masked) and
# DATABASE_SSL_OVERRIDE=require into the job.
# Needs: TUNNEL_TARGET, DB_HOST, DATABASE_URL (the real URL), and the tunnel's credentials.
# Worked example: AWS SSM Session Manager. For another tunnel, replace install_client and open_tunnel only.
set -euo pipefail
LOCAL_PORT="${LOCAL_PORT:-55432}"
DB_PORT="${DB_PORT:-5432}"
[[ -n "${TUNNEL_TARGET:-}" && -n "${DB_HOST:-}" ]] || { echo "::error::TUNNEL_TARGET and DB_HOST are needed for the tunnel"; exit 1; }

install_client() {
  command -v aws >/dev/null || { echo "::error::the AWS CLI is not on this runner"; exit 1; }
  # The Session Manager plugin, without root when it isn't installed: runner pods may have no sudo.
  if ! command -v session-manager-plugin >/dev/null; then
    arch="$([[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] && echo ubuntu_arm64 || echo ubuntu_64bit)"
    curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/$arch/session-manager-plugin.deb" -o "$RUNNER_TEMP/smp.deb"
    dpkg -x "$RUNNER_TEMP/smp.deb" "$RUNNER_TEMP/smp"
    export PATH="$RUNNER_TEMP/smp/usr/local/sessionmanagerplugin/bin:$PATH"
    echo "$RUNNER_TEMP/smp/usr/local/sessionmanagerplugin/bin" >> "$GITHUB_PATH"
  fi
}

open_tunnel() {
  nohup aws ssm start-session --target "$TUNNEL_TARGET" --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters "host=$DB_HOST,portNumber=$DB_PORT,localPortNumber=$LOCAL_PORT" > "$RUNNER_TEMP/tunnel.log" 2>&1 &
}

install_client
open_tunnel
for _ in $(seq 1 30); do (echo > "/dev/tcp/127.0.0.1/$LOCAL_PORT") 2>/dev/null && break; sleep 1; done
(echo > "/dev/tcp/127.0.0.1/$LOCAL_PORT") 2>/dev/null || { cat "$RUNNER_TEMP/tunnel.log"; echo "::error::the tunnel did not open"; exit 1; }

# The certificate is for the database's real name, so TLS is `require` (encrypted, not name-checked); the tunnel is
# authenticated by the cloud provider.
url="$(node -e 'const u = new URL(process.env.DATABASE_URL); u.hostname = "127.0.0.1"; u.port = process.argv[1]; process.stdout.write(u.href)' "$LOCAL_PORT")"
echo "::add-mask::$url"
echo "DATABASE_URL_OVERRIDE=$url" >> "$GITHUB_ENV"
echo "DATABASE_SSL_OVERRIDE=require" >> "$GITHUB_ENV"
```

The tunnel role also needs the permission to start the session (for SSM: `ssm:StartSession` on the target and the
port-forwarding document), and its OIDC trust must accept the environment's subject (P59).

## 5. Choosing the runner (E10)

- **Self-hosted, with real cores.** Embedding is CPU-bound. On a 2-core GitHub-hosted runner it managed about one
  section a second: the first full run (~19,000 sections) needed ~5 hours and the 2-hour limit stopped it after
  three repos. After the first run, a weekly refresh touches only changed files and takes minutes.
- **`max-parallel` from memory.** Each index job holds the embedding model: up to ~1.3 GB observed. Proven at 3 at
  a time on a VM that gives ~1 GB per job when all its runner pods are busy. Jobs = floor(free memory / 1.3 GB),
  and leave room for the database round trips.
- **Schedule inside the runner's uptime.** A self-hosted runner that sleeps at night leaves a 03:00 job queued; the
  source moved its cron from 03:00 to 09:00 local for this reason.
- **Timeout.** Proven at 240 minutes per repo job. The number matters less than resumability: sections are
  committed every 40 files, so a job that is stopped is continued by the next run.

## 6. Container image for the API (it embeds each query)

Adapted, not the source's file (which is two-stage and also builds a web front end): the proven parts are the
glibc base, `ONNXRUNTIME_NODE_INSTALL=skip`, the other-OS cleanup, the model bake with its dimension check, and
running as `node` (the baked model files are world-readable). Copy only what the API runs, and keep a
`.dockerignore` with `node_modules`, `.models` and `.env`, so a local build never ships them.

```dockerfile
# file: Dockerfile (the parts that matter for search)
# Debian, not Alpine: the ONNX runtime that runs the embedding model ships for glibc only.
FROM node:22-slim
# The ONNX runtime would download its GPU build from nuget.org while installing; the CPU build ships with the package,
# and that download has failed builds when nuget.org timed out.
ENV NODE_ENV=production ONNXRUNTIME_NODE_INSTALL=skip
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev \
 # the ONNX runtime ships native libraries for every OS; this image only needs Linux (saves ~220 MB)
 && rm -rf node_modules/onnxruntime-node/bin/napi-v*/darwin node_modules/onnxruntime-node/bin/napi-v*/win32
# The embedding model, fetched now so a server never downloads it (~160 MB). Assert the dimension (P7).
ENV KB_MODEL_DIR=/app/.models
RUN node -e "import('@huggingface/transformers').then(async ({ pipeline, env }) => { env.cacheDir = process.env.KB_MODEL_DIR; const e = await pipeline('feature-extraction', 'jinaai/jina-embeddings-v2-base-code', { dtype: 'q8' }); const v = (await e(['warm up'], { pooling: 'mean', normalize: true })).tolist()[0]; if (v.length !== 768) throw new Error('unexpected embedding size ' + v.length) })"
COPY src src
COPY migrations migrations
USER node
```

The API with the model loaded uses ~0.5 GB. Local development database: `pgvector/pgvector:0.8.6-pg17` (Postgres 17
with pgvector), which matches what managed Postgres 17 offers.

## 7. One-time setup checklist

1. A privileged database user runs `create extension if not exists pg_trgm;` and `create extension if not exists
   vector;` (P1). `\dx` shows both. On RDS, if refused, check the parameter group's `rds.allowed_extensions`.
2. Deploy the release with the migrations (or let the first refresh apply them: the indexer migrates too).
3. A GitHub environment (`knowledge`) holding the database secret, with **no required reviewers** (P58). Optionally
   restrict its deployment branches to `main`.
4. A fine-grained token (preferably from a bot account) with **Contents: read** on the indexed repos only. Put its
   expiry date in a calendar: expiry shows up as a 404 at the checkout step.
5. If a cloud role is assumed (tunnel), its OIDC trust lists the environment's subject
   `repo:<org>/<repo>:environment:<env-name>` as well as any branch subject (P59).
6. First run on one small repo (`only=<name>`), read its summary and the blocked/redacted counts; then all repos.
7. Check: `select name, branch, left(last_sha, 7), indexed_at from kb_repo order by name;` lists every entry.

## 8. If something fails

| What you see | Cause |
|---|---|
| New API container restarts; the log says "pg_trgm is not installed" | Step 1 was skipped. Run it, then restart. |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` (or your cloud's equivalent) on the refresh only | The role's trust lacks the environment subject (P59), or names the wrong repository. |
| `Repository not found` / 404 at a repo checkout step | The read token does not include that repository, was not approved by the organisation, or expired. |
| "the tunnel did not open" | The tunnel client download failed, or the role may not start the session; the step prints the client's own log. |
| A repo job hits its timeout on the first run | Expected on few cores; the next run continues from the last committed 40 files. Re-run, or give the runner more cores. |
| Refresh is green but answers look old | The refresh reads branch tips only: a change not yet on the indexed branch is not there (P62c). Check the branch per repo. |
| The free golden check is red | A golden question's expected file moved or was deleted; update or retire the question. |
| Meaning search is "unavailable" in the summary | The model failed to load (download, memory); the run continued word-only. Sections are back-filled next run. |

## 9. Run status under parallel jobs (not yet proven in production)

Each matrix job runs the indexer, so each inserts its own `kb_index_run` row, and a status route that reads only
the latest row can show "ok" while an earlier job of the same run failed. The source leaves this open. Proposed:
tag every row with the workflow run and aggregate.

```sql
-- file: migrations/003_kb_run_key.sql   (proposed, not yet proven in production)
alter table kb_index_run add column if not exists run_key text; -- e.g. "<github.run_id>-<github.run_attempt>"
```

Pass `KB_RUN_KEY: ${{ github.run_id }}-${{ github.run_attempt }}` to the index step, insert it with the run row
(`insert into kb_index_run (run_key) values ($1)`), and have the status route read:

```sql
select bool_or(status = 'failed') as failed, bool_or(status = 'running') as running, max(finished_at) as finished_at
  from kb_index_run
 where run_key is not distinct from (select run_key from kb_index_run order by id desc limit 1); -- a local run has none
```

## Pitfalls

- **P47. Run embedding on a self-hosted runner with real cores; a 2-core hosted runner managed about one section
  per second.** The first full run (~19,000 sections) needed ~5 hours there and hit the 2-hour limit after three
  repos.
- **P48. Size `max-parallel` from memory: each index job holds the embedding model (~1.3 GB at most observed).**
  Proven: 3 at a time on a VM that gives ~1 GB per job when all its pods are busy.
- **P49. Give the per-repo job a first-run-sized timeout (proven: 240 min) and rely on resumability, not on the
  timeout being enough.**
- **P50. `fail-fast: false` on the matrix and `if: !cancelled()` on the links job.** One failed repo must not
  cancel the others, and contracts are still rebuilt from what the base holds.
- **P51. One refresh at a time: a `concurrency` group with `cancel-in-progress: false`.**
- **P52. Schedule inside the hours the self-hosted runner is up.** A job queued while it is off waits.
- **P53. Set `ONNXRUNTIME_NODE_INSTALL=skip` wherever `npm ci` runs.** The install script downloads a GPU build
  from nuget.org; a timeout there failed a deploy. The CPU build ships in the package.
- **P54. Cache the model directory between runs, keyed by model name + quantisation.**
- **P55. On a self-hosted runner with a shared npm cache, leave out `setup-node`'s `cache: npm`.** It unpacks over
  the cache other jobs are reading.
- **P56. Keep the repo list in one file read by the indexer AND the workflow.** In the source it lived in three
  places that had to agree (the indexer's list, the plan step's list, one checkout step per repo).
- **P57. A repo indexed at two branches needs two checkout folders in CI (`ciDir`).** A laptop reads both from one
  checkout's remote refs; CI checks out one commit per folder.
- **P58. Check repos out with a read-only, repo-scoped token and `persist-credentials: false`; put the database
  secret in a GitHub environment with NO required reviewers.** A scheduled run waits for approval forever. Note the
  token's expiry date, because expiry shows up as a 404 at checkout.
- **P59. Jobs in a GitHub environment present a different OIDC subject (`repo:<org>/<repo>:environment:<name>`).**
  A cloud role that trusts only `ref:refs/heads/main` rejects the refresh and nothing else.
- **P60. Validate the free-text `only` input (character class + membership) and pass it through `env:`.** It ends
  up on a shell command line.
- **P61. Keep the exit code through `tee` with `set +e` and `${PIPESTATUS[0]}`.** Otherwise a failed index step is
  green.
- **P62. Tunnel to a private database: install the tunnel client without root, wait for the port (30 s) and print
  the client's own log on failure, mask the rewritten URL, export it through `$GITHUB_ENV`, and use TLS
  `require`.** Runner pods may have no sudo; the certificate names the real host, not 127.0.0.1.
- **P62a. Container: glibc base image (onnxruntime has no musl build), bake the model at build time and assert the
  vector length, delete other-OS native libraries (~220 MB).**
- **P62b. Warm the embedder in the background at API start, only when answering is enabled.** The first search is
  otherwise slow.
- **P62c. Green run, old answers: the refresh reads branch tips only.** A change not yet on the indexed branch is
  not there; index the branch production runs from, and check it is not a stale snapshot (in the source, one
  repo's `production` branch was a stale snapshot that lacked a whole client).

## Proven at

8 repo entries on a self-hosted runner, 3 jobs at a time, 240-minute job timeout; first full run ~19,000 sections;
weekly runs in minutes; contracts rebuild in a few hundred ms.
