# Indexer: from git objects to embedded sections

Load this when building the part that reads repositories into the database: the repo config, the git reader, the
file filter, the secret scrubber, the per-repo file refresh, the chunker, the embedder and the section refresh.
TypeScript on Node 22 (type-stripped `.ts`, no build step) and `pg`; the shapes carry to any language.

Layout assumed by the imports: the indexer (`index.ts`, `git.ts`, `filter.ts`, `secrets.ts`, `sections.ts`,
`repos.ts`) and the files it shares with the API (`kb-chunks.ts`, `kb-embed.ts`, `kb-contracts.ts`, `systems.ts`,
`db.ts`, `config.ts`) sit side by side. In a monorepo put the shared ones in a package both apps import.

## 1. Repo config and system vocabulary (E1, E2, E7)

One file is the single source of truth for what is indexed, read by the indexer AND the refresh workflow (P56).
JSON so the workflow can read it without TypeScript.

```json
{
  "repos": [
    { "name": "orders-api", "repository": "acme/orders-api", "dir": "orders-api", "branch": "production" },
    { "name": "dispatch", "repository": "acme/dispatch", "dir": "dispatch", "branch": "release" },
    { "name": "platform/worker", "repository": "acme/platform", "dir": "platform", "ciDir": "platform-release", "branch": "release", "subdir": "worker" },
    { "name": "platform/scheduler", "repository": "acme/platform", "dir": "platform", "branch": "feat/scheduler", "subdir": "scheduler" }
  ]
}
```

The last two show the two awkward cases: two services in one repo (`subdir`), and one repo indexed at two branches
(`ciDir`, P57). Example names only. The file is found through `KB_REPOS_FILE` (default `kb-repos.json` in the
working directory), in both the indexer and the workflow.

```ts
// file: repos.ts
import { readFileSync } from 'node:fs'

// What the knowledge base is built from. One entry per indexed repo and branch; change a branch here, not in code.
// The branches are the ones each repo's production runs from (E2): check none is a stale snapshot.
export type RepoSpec = {
  // The name people and citations use. Two entries may share a checkout (one repo holding two services).
  name: string
  // owner/repo, for the workflow's checkout step.
  repository: string
  // The checkout, relative to KB_REPOS_DIR.
  dir: string
  // Where the workflow checks this branch out (KB_REF=head). Only needed when a repo is indexed at two branches:
  // a laptop reads both from one checkout's origin refs, CI checks each branch out on its own.
  ciDir?: string
  branch: string
  // Index only this folder of the checkout. Stored paths are relative to it.
  subdir?: string
}

// KB_REPOS_FILE: where the config lives (default: kb-repos.json in the working directory). The workflow's plan step
// reads the same variable, so in a monorepo point both at one file.
export const REPOS: RepoSpec[] = JSON.parse(readFileSync(process.env.KB_REPOS_FILE?.trim() || 'kb-repos.json', 'utf8')).repos
```

System vocabulary (E7) lives in one small file shared by the chunker, search, contracts and the progress lines.
With a single system, leave all three tables empty: the system boost and the connector lift switch themselves off.

```ts
// file: systems.ts
// The indexed repositories as people know them. Two repos may share one system name (a service and its worker):
// contracts compare SYSTEMS, so the two never "call each other" (P46a).
export const SYSTEM_NAMES: Record<string, string> = {
  // example: 'orders-api': 'the order service', 'platform/worker': 'the platform', 'platform/scheduler': 'the platform',
}
export const systemName = (repo: string) => SYSTEM_NAMES[repo] ?? repo

// Short names as people type them, and what the code calls them. Two- or three-letter names are too short to search
// for (and match everything), but the code spells them out (P33).
export const SYSTEM_WORDS: Record<string, string> = {
  // example: oms: 'order management', crm: 'customer relationship',
}

// Which systems a question names, as their repos. Whole words only: "smart" must not match "sm".
export const SYSTEM_REPOS: [RegExp, string[]][] = [
  // example: [/\boms\b|order management/, ['orders-api']],
  // example: [/\bdispatch\b/, ['dispatch', 'dispatch-worker']],
]
```

## 2. Git reader

```ts
// file: git.ts
import { execFile, spawn } from 'node:child_process'
import { promisify } from 'node:util'

const run = promisify(execFile)

// Everything here reads git objects at a ref. It never checks anything out, so the working tree (and whatever
// branch a person has open there) is never touched, and nothing is ever written to a repo.

export async function git(dir: string, args: string[]): Promise<string> {
  const { stdout } = await run('git', ['-C', dir, ...args], { maxBuffer: 256 * 1024 * 1024 })
  return stdout
}

export const revParse = async (dir: string, ref: string) => (await git(dir, ['rev-parse', '--verify', `${ref}^{commit}`])).trim()

export type TreeEntry = { path: string; sha: string; size: number }

// Files (not symlinks or submodules) under `subdir` at `ref`. Paths are relative to `subdir`.
export async function listTree(dir: string, ref: string, subdir?: string): Promise<TreeEntry[]> {
  const prefix = subdir ? `${subdir.replace(/\/+$/, '')}/` : ''
  const args = ['ls-tree', '-r', '-z', '--long', ref]
  if (prefix) args.push('--', prefix)
  const out = await git(dir, args)
  const entries: TreeEntry[] = []
  for (const rec of out.split('\0')) {
    if (!rec) continue
    // <mode> SP <type> SP <sha> SP <size, right-aligned> TAB <path>
    const tab = rec.indexOf('\t')
    const [mode, type, sha, size] = rec.slice(0, tab).split(/\s+/)
    if (type !== 'blob' || mode === '120000') continue
    entries.push({ path: rec.slice(tab + 1).slice(prefix.length), sha, size: Number(size) })
  }
  return entries
}

// Contents of many blobs through one `git cat-file --batch` process, in the order asked.
export function readBlobs(dir: string, shas: string[]): Promise<Map<string, Buffer>> {
  return new Promise((resolve, reject) => {
    const out = new Map<string, Buffer>()
    if (!shas.length) return resolve(out)
    const child = spawn('git', ['-C', dir, 'cat-file', '--batch'], { stdio: ['pipe', 'pipe', 'inherit'] })
    const chunks: Buffer[] = []
    child.stdout.on('data', (c: Buffer) => chunks.push(c))
    child.on('error', reject)
    child.on('close', (code) => {
      if (code !== 0) return reject(new Error(`git cat-file exited ${code}`))
      const buf = Buffer.concat(chunks)
      let at = 0
      while (at < buf.length) {
        const nl = buf.indexOf(0x0a, at)
        if (nl < 0) break
        const [sha, type, len] = buf.subarray(at, nl).toString('ascii').split(' ')
        if (type === 'missing') {
          at = nl + 1
          continue
        }
        const size = Number(len)
        out.set(sha, buf.subarray(nl + 1, nl + 1 + size))
        at = nl + 1 + size + 1
      }
      resolve(out)
    })
    child.stdin.end(shas.join('\n') + '\n')
  })
}
```

## 3. File filter (E3)

An allowlist: anything not recognised is left out (P18). The lists are the extension point; the order of the
checks is the part to keep (allowed env samples before the secret-path deny rules, P19).

```ts
// file: filter.ts
// Which files enter the knowledge base, and what kind each one is. Anything not recognised is left out: the
// base holds what explains the software, not whatever a repo happens to track.

export type Kind = 'code' | 'test' | 'doc' | 'setting' | 'schema'

export const MAX_BYTES = 300_000 // proven at: 300 KB; likely also what keeps whole-file tsvectors under Postgres's 1 MB cap (inferred)

// A path with any of these folders anywhere in it is never indexed.
const SKIP_DIRS = new Set([
  'node_modules', 'bin', 'obj', 'dist', 'build', 'out', 'target', 'coverage', 'vendor', '__pycache__', '.venv', 'venv',
  '.git', '.github', '.idea', '.vs', '.next', '.nuxt', '.cache', 'logfile', 'logs', 'wwwroot',
])

// Secrets and customer data: skipped whatever else they look like.
const SKIP_PATHS: RegExp[] = [
  /(^|\/)\.env($|\.)/i, // .env, .env.local, .env.staging ... (samples are allowed below)
  /(^|\/)env\//i, // a folder of per-customer env files (example from the source project)
  /(^|\/)appsettings[^/]*\.json$/i, // .NET settings, several named for customers
  /\.(pem|key|pfx|p12|jks|keystore|crt|cer|der)$/i,
  /(^|\/)id_(rsa|dsa|ecdsa|ed25519)/i,
  /(^|\/)(secrets?|credentials?)\.(json|ya?ml|txt)$/i,
  /(^|\/)\.npmrc$/i,
  /(^|\/)\.pypirc$/i,
]
const ALLOWED_ENV_SAMPLES = /(^|\/)(\.env[._-]?(sample|example)|sample\.env|\.env\.example|\.env_sample)(_prod)?$/i

// Generated or not human-readable.
const SKIP_FILES: RegExp[] = [
  /(^|\/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|Pipfile\.lock|composer\.lock|packages\.lock\.json|go\.sum)$/i,
  /\.min\.(js|css)$/i,
  /\.(map|snap|svg|png|jpe?g|gif|webp|ico|bmp|tiff?|woff2?|ttf|otf|eot|mp[34]|mov|zip|gz|tgz|tar|7z|rar|jar|dll|exe|so|dylib|a|o|class|pyc|whl|bin|dat|db|sqlite3?|pdf|docx?|pptx?|xlsx?|csv|tsv|parquet|log|lock)$/i,
  /\.designer\.cs$/i,
  /\.g\.cs$/i,
]

// SQL carries schema and seed data. Only migration or schema folders are kept, and never seed or dump files.
const SQL_OK = /(^|\/)(migrations?|schema|schemas)\//i
const SQL_NEVER = /(seed|dump|backup|data|fixture|sample)/i

const CODE = new Set([
  'py', 'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs', 'vue', 'cs', 'razor', 'cshtml', 'rs', 'go', 'java', 'kt', 'rb', 'php',
  'sh', 'bash', 'ps1', 'html', 'css', 'scss', 'less', 'tf', 'dockerfile',
])
const DOC = new Set(['md', 'mdx', 'rst', 'adoc', 'txt'])
const SETTING = new Set(['json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'properties', 'csproj', 'props', 'xml', 'env'])
const SCHEMA = new Set(['sql', 'proto', 'graphql', 'gql', 'prisma'])

const LANG: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  vue: 'vue', cs: 'csharp', razor: 'csharp', cshtml: 'csharp', rs: 'rust', go: 'go', java: 'java', kt: 'kotlin', rb: 'ruby',
  php: 'php', sh: 'shell', bash: 'shell', ps1: 'powershell', html: 'html', css: 'css', scss: 'css', less: 'css', tf: 'terraform',
  sql: 'sql', proto: 'protobuf', graphql: 'graphql', gql: 'graphql', md: 'markdown', mdx: 'markdown', json: 'json',
  yaml: 'yaml', yml: 'yaml', toml: 'toml',
}

const TEST_DIR = /(^|\/)(tests?|__tests__|spec|specs|e2e|cypress)\//i
const TEST_FILE = /(^|\/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(spec|test)\.[jt]sx?|[^/]+Tests?\.cs)$/i

function ext(path: string): string {
  const name = path.slice(path.lastIndexOf('/') + 1).toLowerCase()
  if (name === 'dockerfile' || name.startsWith('dockerfile.')) return 'dockerfile'
  if (ALLOWED_ENV_SAMPLES.test(path)) return 'env'
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1)
}

// null: leave this file out.
export function classify(path: string, size: number): { kind: Kind; language: string | null } | null {
  if (size === 0 || size > MAX_BYTES) return null
  const parts = path.split('/')
  if (parts.slice(0, -1).some((p) => SKIP_DIRS.has(p))) return null
  if (ALLOWED_ENV_SAMPLES.test(path)) return { kind: 'setting', language: null } // before SKIP_PATHS: .env.example matches .env*
  if (SKIP_PATHS.some((re) => re.test(path))) return null
  if (SKIP_FILES.some((re) => re.test(path))) return null

  const e = ext(path)
  if (e === 'sql' && (!SQL_OK.test(path) || SQL_NEVER.test(path.slice(path.lastIndexOf('/') + 1)))) return null
  const language = LANG[e] ?? null

  if (SCHEMA.has(e)) return { kind: 'schema', language }
  if (DOC.has(e)) return { kind: 'doc', language }
  if (CODE.has(e)) return { kind: TEST_DIR.test(path) || TEST_FILE.test(path) ? 'test' : 'code', language }
  if (SETTING.has(e)) return { kind: TEST_DIR.test(path) ? 'test' : 'setting', language }
  return null
}
```

Cases your filter must pass (after adapting the lists, keep these green):

```ts
// file: indexer.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { classify } from './filter.ts'
import { scan } from './secrets.ts'

const kind = (path: string, size = 1000) => classify(path, size)?.kind ?? null

test('keeps the files that explain the software', () => {
  assert.equal(kind('app/settings/limits.py'), 'code')
  assert.equal(kind('tests/test_retry_policy.py'), 'test')
  assert.equal(kind('src/orders/orders.spec.ts'), 'test')
  assert.equal(kind('docs/PROJECT-GUIDE.md'), 'doc')
  assert.equal(kind('libs/database/migrations/1700-AddZone.ts'), 'code')
  assert.equal(kind('db/migrations/001_init.sql'), 'schema')
  assert.equal(kind('docker-compose.local.yml'), 'setting')
  assert.equal(kind('src/App/Services/OrdersClient.cs'), 'code')
  assert.equal(kind('public/docs/guide.md'), 'doc')
})

test('leaves out secrets, customer config and generated files', () => {
  for (const path of [
    '.env',
    'apps/api/.env.production',
    'env/.env.customer-a',
    'src/Host/appsettings.CustomerA.json',
    'src/Host/appsettings.json',
    'keys/server.pem',
    'package-lock.json',
    'dist/app.min.js',
    'node_modules/x/index.js',
    'assets/logo.png',
    'errors.xlsx',
    'db/seed.sql',
    'scripts/dump.sql',
    'bin/Debug/app.cs',
  ]) {
    assert.equal(kind(path), null, path)
  }
})

test('keeps reviewed env samples', () => {
  assert.equal(kind('.env_sample'), 'setting')
  assert.equal(kind('.env.example'), 'setting')
  assert.equal(kind('apps/api/sample.env'), 'setting')
})

test('leaves out empty and oversized files', () => {
  assert.equal(kind('a.py', 0), null)
  assert.equal(kind('a.py', 300_001), null)
})
```

## 4. Secret scrubber (E4)

The always-on floor. BLOCK rules skip the whole file; REDACT rules replace the value and keep the file. Only the
rule name is ever reported (P16, P17). An external scanner (gitleaks) can run in front of it.

```ts
// file: secrets.ts
// The always-on secret guard. It runs on every file before it is stored. A CI scanner (gitleaks) can be added in
// front of it; this is the floor, so a repo that slipped a key into source never reaches the database.

// A match means a real credential: the whole file is left out. Only the rule name is ever reported, never the match.
const BLOCK: { rule: string; re: RegExp }[] = [
  { rule: 'private-key', re: /-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----/ },
  { rule: 'aws-access-key', re: /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/ },
  { rule: 'aws-secret-key', re: /aws_?secret_?access_?key["']?\s*[:=]\s*["']?[A-Za-z0-9/+=]{40}\b/i },
  { rule: 'anthropic-or-openai-key', re: /\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}/ },
  { rule: 'github-token', re: /\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b/ },
  { rule: 'slack-token', re: /\bxox[abprs]-[A-Za-z0-9-]{10,}/ },
  { rule: 'jwt', re: /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/ },
]

// A match is likely a credential but the file is useful: the value is replaced and the rest kept.
const REDACT: RegExp[] = [
  // password = "hunter2xx", "api_key": "abcd...", token: 'xyz...'
  /((?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)["']?\s*[:=]\s*["'])([^"'\s]{8,})(["'])/gi,
  // postgres://user:password@host
  /(\b[a-z][a-z0-9+.-]*:\/\/[^\s:/@]+:)([^\s@/]+)(@)/gi,
]

export type Scan = { blocked: string | null; content: string; redacted: number }

export function scan(text: string): Scan {
  for (const { rule, re } of BLOCK) if (re.test(text)) return { blocked: rule, content: '', redacted: 0 }
  let redacted = 0
  let content = text
  for (const re of REDACT) {
    content = content.replace(re, (_m, pre: string, _value: string, post: string) => {
      redacted++
      return `${pre}[REDACTED]${post}`
    })
  }
  return { blocked: null, content, redacted }
}
```

The tests build the fake credentials from parts, so this skill file and the test file never trip a secret scanner
themselves:

```ts
// file: indexer.test.ts (continued)
test('blocks a file holding a real credential, and says only which rule', () => {
  const key = ['-----BEGIN RSA', 'PRIVATE KEY-----'].join(' ')
  assert.equal(scan(`x\n${key}\nabc`).blocked, 'private-key')
  const aws = 'AKIA' + 'ABCDEFGHIJKLMNOP'
  assert.equal(scan(`key = "${aws}"`).blocked, 'aws-access-key')
  const jwt = ['eyJhbGciOiJIUzI1NiJ9', 'eyJzdWIiOiIxMjM0NTY3ODkwIn0', 'SflKxwRJSMeKKF2QT4fwpM'].join('.')
  assert.equal(scan(`t = '${jwt}'`).blocked, 'jwt')
  assert.equal(scan('x').content, 'x')
})

test('redacts a likely password but keeps the code readable', () => {
  const s = scan('db_password = "hunter2hunter2"\nRETRY_LIMIT = 50\nurl = "postgres://app:s3cretpass@db:5432/x"')
  assert.equal(s.blocked, null)
  assert.equal(s.redacted, 2)
  assert.match(s.content, /db_password = "\[REDACTED\]"/)
  assert.match(s.content, /RETRY_LIMIT = 50/)
  assert.match(s.content, /postgres:\/\/app:\[REDACTED\]@db/)
  assert.doesNotMatch(s.content, /hunter2|s3cretpass/)
})
```

Read what the first full run blocks. In the source project it found two real credentials committed to source.

## 5. Per-repo file refresh and the run loop

```ts
// file: index.ts
import { join } from 'node:path'
import pg from 'pg'
// The same DATABASE_URL / DATABASE_SSL rules as the API, so one .env serves both.
import { databaseConfig } from './config.ts'
import { REPOS, type RepoSpec } from './repos.ts'
import { classify } from './filter.ts'
import { scan } from './secrets.ts'
import { migrate } from './db.ts'
import { listTree, readBlobs, revParse } from './git.ts'
import { prepareMeaning, refreshSections, type SectionResult } from './sections.ts'
import { refreshContracts } from './kb-contracts.ts'

// Refresh the knowledge base: for each repo, read the files at the branch tip and store what changed. Run by the
// scheduled workflow (refresh-workflow.md), or by hand:
//
//   npm run index                       every repo
//   npm run index -- --only a,b         some repos
//   npm run dry-run                     count only; writes nothing
//
// KB_REPOS_DIR  where the checkouts live (default ./repos)
// KB_REF        origin (read origin/<branch>, the default: works from any local checkout without switching it;
//                       run `git fetch` first or you index stale code)
//               or head (the checkout is already at the branch, as in CI after actions/checkout)

const args = process.argv.slice(2)
const dryRun = args.includes('--dry-run')
const only = args.find((a, i) => args[i - 1] === '--only')?.split(',').map((s) => s.trim()).filter(Boolean)
const reposDir = process.env.KB_REPOS_DIR?.trim() || join(process.cwd(), 'repos')
const refMode = process.env.KB_REF?.trim() || 'origin'
if (refMode !== 'origin' && refMode !== 'head') throw new Error(`KB_REF must be origin or head, got "${refMode}".`)

type RepoResult = { name: string; branch: string; sha: string | null; added: number; changed: number; removed: number; unchanged: number; skipped: number; blocked: number; redacted: number; repoId?: number; sections?: SectionResult; error?: string }

const BATCH = 150 // blobs per `git cat-file --batch` process

async function indexRepo(db: pg.Pool, spec: RepoSpec): Promise<RepoResult> {
  const result: RepoResult = { name: spec.name, branch: spec.branch, sha: null, added: 0, changed: 0, removed: 0, unchanged: 0, skipped: 0, blocked: 0, redacted: 0 }
  const dir = join(reposDir, refMode === 'head' ? (spec.ciDir ?? spec.dir) : spec.dir)
  const ref = refMode === 'head' ? 'HEAD' : `origin/${spec.branch}`
  result.sha = await revParse(dir, ref)

  const tree = await listTree(dir, ref, spec.subdir)
  const wanted = new Map<string, { sha: string; size: number; kind: string; language: string | null }>()
  for (const e of tree) {
    const c = classify(e.path, e.size)
    if (!c) result.skipped++
    else wanted.set(e.path, { sha: e.sha, size: e.size, ...c })
  }

  // The repo's row exists before any of its files, and a dry run only reads.
  const existing = new Map<string, string>()
  let repoId: number | null = null
  if (!dryRun) {
    const { rows } = await db.query<{ id: number }>(
      `insert into kb_repo (name, branch) values ($1, $2)
         on conflict (name) do update set branch = excluded.branch returning id`,
      [spec.name, spec.branch],
    )
    repoId = rows[0].id
    const files = await db.query<{ path: string; blob_sha: string }>('select path, blob_sha from kb_file where repo_id = $1', [repoId])
    for (const f of files.rows) existing.set(f.path, f.blob_sha)
  }

  const removed = [...existing.keys()].filter((p) => !wanted.has(p))
  const todo = [...wanted.entries()].filter(([p, w]) => existing.get(p) !== w.sha)
  result.unchanged = wanted.size - todo.length
  result.removed = removed.length

  // A repo is written in one transaction: if any part fails the previous index of this repo stays as it was.
  const client = dryRun ? null : await db.connect()
  try {
    await client?.query('begin')
    for (let i = 0; i < todo.length; i += BATCH) {
      const slice = todo.slice(i, i + BATCH)
      const blobs = await readBlobs(dir, [...new Set(slice.map(([, w]) => w.sha))])
      const rows: { path: string; w: (typeof slice)[number][1]; content: string }[] = []
      for (const [path, w] of slice) {
        const buf = blobs.get(w.sha)
        if (!buf || buf.includes(0)) {
          result.skipped++ // binary, or not found
          continue
        }
        const s = scan(buf.toString('utf8'))
        if (s.blocked) {
          // Only the rule is logged: never the match, and not the content.
          console.warn(`  blocked ${spec.name}:${path} (${s.blocked})`)
          result.blocked++
          if (existing.has(path)) removed.push(path) // its older, indexed version must go too
          continue
        }
        result.redacted += s.redacted
        rows.push({ path, w, content: s.content })
        if (existing.has(path)) result.changed++
        else result.added++
      }
      if (!client || !rows.length) continue // a dry run only counts
      await client.query(
        `insert into kb_file (repo_id, path, blob_sha, kind, language, size, content)
           select $1, * from unnest($2::text[], $3::text[], $4::text[], $5::text[], $6::int[], $7::text[])
         on conflict (repo_id, path) do update
           set blob_sha = excluded.blob_sha, kind = excluded.kind, language = excluded.language, size = excluded.size, content = excluded.content`,
        [repoId, rows.map((r) => r.path), rows.map((r) => r.w.sha), rows.map((r) => r.w.kind), rows.map((r) => r.w.language), rows.map((r) => r.w.size), rows.map((r) => r.content)],
      )
    }
    if (client) {
      if (removed.length) await client.query('delete from kb_file where repo_id = $1 and path = any($2::text[])', [repoId, removed])
      await client.query('update kb_repo set last_sha = $2, indexed_at = now() where id = $1', [repoId, result.sha])
      await client.query('commit')
    }
  } catch (e) {
    await client?.query('rollback').catch(() => {})
    throw e
  } finally {
    client?.release()
  }
  result.removed = removed.length
  if (repoId !== null) result.repoId = repoId
  return result
}

const specs = REPOS.filter((r) => !only || only.includes(r.name))
if (only) {
  const unknown = only.filter((n) => !REPOS.some((r) => r.name === n))
  if (unknown.length) throw new Error(`Unknown repo ${unknown.join(', ')}. Known: ${REPOS.map((r) => r.name).join(', ')}.`)
}

const db = new pg.Pool({ ...databaseConfig(), max: 2 })
let runId: string | null = null
const results: RepoResult[] = []
try {
  if (!dryRun) {
    // The same migrations the API applies when it starts (advisory-locked, so the two never collide). A scheduled run
    // therefore works on a database the new release has not been deployed to yet.
    await migrate(db, (line) => console.log(`migrate: ${line}`))
    runId = (await db.query<{ id: string }>('insert into kb_index_run default values returning id')).rows[0].id
  }
  const meaning = !dryRun && (await prepareMeaning(db, (line) => console.log(line)))
  for (const spec of specs) {
    console.log(`${spec.name} @ ${refMode === 'head' ? 'HEAD' : `origin/${spec.branch}`}`)
    try {
      const r = await indexRepo(db, spec)
      results.push(r)
      console.log(`  ${r.sha?.slice(0, 7)}  +${r.added} ~${r.changed} -${r.removed} =${r.unchanged}  skipped ${r.skipped}, blocked ${r.blocked}, redacted ${r.redacted}`)
      // Sections for search, from the files just stored (only new and changed ones).
      if (r.repoId !== undefined) {
        r.sections = await refreshSections(db, r.repoId, spec.name, meaning, (line) => console.log(line))
        console.log(`  sections: ${r.sections.files} files cut into ${r.sections.sections}, ${r.sections.embedded} embedded (meaning search ${r.sections.meaning})`)
      }
    } catch (e) {
      const message = (e as Error).message
      results.push({ name: spec.name, branch: spec.branch, sha: null, added: 0, changed: 0, removed: 0, unchanged: 0, skipped: 0, blocked: 0, redacted: 0, error: message })
      console.error(`  FAILED: ${message}`)
    }
  }
  // How the systems call each other, from every indexed code file (all repos, not only this run's). A parallel refresh
  // (one job per repo) turns this off with KB_CONTRACTS=off and builds the links once at the end (contracts-cli.ts).
  if (!dryRun && process.env.KB_CONTRACTS?.trim() !== 'off') {
    const c = await refreshContracts(db)
    console.log(`links between systems: ${c.contracts} from ${c.routes} routes in ${c.files} code files`)
  }
} finally {
  const failed = results.filter((r) => r.error)
  if (runId) {
    await db.query(`update kb_index_run set finished_at = now(), status = $2, repos = $3, error = $4 where id = $1`, [
      runId,
      failed.length ? 'failed' : 'ok',
      JSON.stringify(results),
      failed.length ? failed.map((r) => `${r.name}: ${r.error}`).join('; ') : null,
    ])
  }
  await db.end()
  // A failed repo keeps its previous index (its transaction rolled back). The run still fails loudly.
  if (failed.length) process.exitCode = 1
}
```

Read the log line `+added ~changed -removed =unchanged  skipped, blocked, redacted`: a second run on the same
commit must print `+0 ~0 -0`.

## 6. Chunker (E5)

```ts
// file: kb-chunks.ts
import { systemName } from './systems.ts'

// Sections of indexed files, for search. A whole file is a poor unit to rank: a 2,000-line file that mentions
// "battery" once outranks the 40 lines that decide what happens at low battery. So each file is cut into sections of
// about 60 lines, cut where a class, function or heading starts when one is near, with the nearest declaration above
// as the section's name. Each section is searched two ways: by its words (with code names split, so "low battery"
// finds lowBatteryThreshold), and by meaning (an embedding, kb-embed.ts).

export type Chunk = { n: number; start: number; end: number; symbol: string | null; text: string }

const TARGET = 60 // lines per section (proven at: 60)
const MAX = 90 // never longer (proven at: 90)
const MIN = 40 // a cut before this isn't worth it (proven at: 40)
const OVERLAP = 6 // a few lines of the previous section, so a statement split across the cut is found in both
const MAX_CHUNKS = 120 // a generated 10,000-line file isn't worth more
const PASSAGE_CHARS = 1_800 // embedding input cap: bounds CPU time per section. Not tuned; the model accepts more.

// E5: a line that starts a declaration or a heading, in the languages indexed: C#, TypeScript/JavaScript/Vue, Python,
// Rust, Markdown headings, and settings files with [sections]. Extend for Go (`func`), Java/Kotlin (`fun`), etc.
const DECLARATION =
  /^\s*(?:#{1,4}\s+\S|\[[\w.-]+\]\s*$|(?:export\s+)?(?:default\s+)?(?:(?:public|private|protected|internal|static|async|abstract|sealed|partial|override|virtual|readonly|pub|unsafe)\s+)*(?:class|interface|record|enum|struct|function|def|namespace|module|type|trait|impl|fn)\s+[\w$]|(?:public|private|protected|internal)\s+[\w<>[\],.?\s]+\s+\w+\s*\()/

export function chunkFile(content: string): Chunk[] {
  const lines = content.split('\n')
  if (lines.length <= MAX) return [{ n: 0, start: 1, end: lines.length, symbol: lastDeclaration(lines, lines.length - 1, true), text: content }]
  const out: Chunk[] = []
  let start = 0
  while (start < lines.length && out.length < MAX_CHUNKS) {
    let end = Math.min(lines.length, start + TARGET)
    if (end < lines.length) {
      // Prefer to cut just before a declaration between MIN and MAX lines in, else at a blank line, else at TARGET.
      let cut = -1
      for (let i = start + MIN; i < Math.min(lines.length, start + MAX); i++) if (DECLARATION.test(lines[i])) cut = cut < 0 || Math.abs(i - start - TARGET) < Math.abs(cut - start - TARGET) ? i : cut
      if (cut < 0) for (let i = start + TARGET; i < Math.min(lines.length, start + MAX); i++) if (!lines[i].trim()) { cut = i; break }
      end = cut > 0 ? cut : end
    }
    if (lines.length - end < MIN / 2) end = lines.length // don't leave a stub
    out.push({ n: out.length, start: start + 1, end, symbol: lastDeclaration(lines, start), text: lines.slice(start, end).join('\n') })
    if (end >= lines.length) break
    start = Math.max(end - OVERLAP, start + 1)
  }
  return out
}

// The nearest declaration at or above `at` (or, for a whole small file, its first one).
function lastDeclaration(lines: string[], at: number, first = false): string | null {
  if (first) {
    for (const l of lines) if (DECLARATION.test(l)) return tidy(l)
    return null
  }
  for (let i = Math.min(at + 3, lines.length - 1); i >= 0; i--) if (DECLARATION.test(lines[i])) return tidy(lines[i])
  return null
}
const tidy = (l: string) => l.trim().replace(/\s*[{:]\s*$/, '').slice(0, 120)

/** Code names as words too: lowBatteryThreshold, LOW_BATTERY, low-battery → low battery threshold. Lower case. */
export function splitIdentifiers(text: string): string {
  return text
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .replace(/[_\-./\\:]+/g, ' ')
    .toLowerCase()
}

/** What a section is searched by, word for word: its path and name (weighted up) and its text, with code names split. */
export function chunkWords(path: string, c: Chunk) {
  return { head: splitIdentifiers(`${path} ${c.symbol ?? ''}`), body: `${c.text.toLowerCase()} ${splitIdentifiers(c.text)}` }
}

/** What a section's meaning is taken from: the system, the file, its name, then the code itself (cut short). */
export function chunkPassage(repo: string, path: string, c: Chunk) {
  return `${systemName(repo)} · ${path}${c.symbol ? `\n${c.symbol}` : ''}\n${c.text}`.slice(0, PASSAGE_CHARS)
}
```

```ts
// file: kb-chunks.test.ts
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { chunkFile, chunkWords, splitIdentifiers } from './kb-chunks.ts'

test('code names become words too', () => {
  assert.equal(splitIdentifiers('lowBatteryThreshold'), 'low battery threshold')
  assert.equal(splitIdentifiers('LOW_BATTERY_LEVEL'), 'low battery level')
  assert.equal(splitIdentifiers('HTTPServerError'), 'http server error')
  assert.equal(splitIdentifiers('mod_billing/invoice_retry.py'), 'mod billing invoice retry py')
})

test('a small file is one section, named after its first declaration', () => {
  const c = chunkFile('import x\n\nclass Charger:\n    pass\n')
  assert.equal(c.length, 1)
  assert.deepEqual([c[0].start, c[0].end, c[0].symbol], [1, 5, 'class Charger'])
})

test('a long file is cut near declarations, sections overlap a little and cover every line', () => {
  const lines: string[] = []
  for (let f = 0; f < 6; f++) {
    lines.push(`def handler_${f}(job):`)
    for (let i = 0; i < 44; i++) lines.push(`    step_${f}_${i} = job.next()`)
  }
  const c = chunkFile(lines.join('\n'))
  assert.ok(c.length >= 3 && c.length <= 6, `${c.length} sections`)
  assert.equal(c[0].start, 1)
  assert.equal(c.at(-1)!.end, lines.length)
  for (let i = 1; i < c.length; i++) {
    assert.ok(c[i].start <= c[i - 1].end + 1, 'no gap between sections')
    assert.ok(c[i].end - c[i].start < 90, 'no section longer than 90 lines')
    assert.match(c[i].symbol ?? '', /^def handler_\d\(job\)$/)
  }
})

test('section words carry the path and the split names', () => {
  const [c] = chunkFile('const lowBatteryThreshold = 20\n')
  const w = chunkWords('app/settings/retryPolicy.py', c)
  assert.match(w.head, /retry policy/)
  assert.match(w.body, /lowbatterythreshold/)
  assert.match(w.body, /low battery threshold/)
})
```

## 7. Embedder (E13)

Runs on your own machines: the refresh embeds sections, the API embeds each search. No embedding service, no key.

```ts
// file: kb-embed.ts
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Meaning search: an open embedding model turns a passage into EMBED_DIMS numbers, so text that means the same thing
// ends up close even when the words differ ("charge" and "LOW_BATTERY_THRESHOLD"). It runs here: the refresh embeds
// every section (kb_chunk.embedding), the API embeds each search. Nothing leaves the server.
//
// jina-embeddings-v2-base-code, Apache 2.0, trained for code and the questions people ask about it; the 8-bit build
// is about 160 MB, takes about 0.5 GB of memory and embeds a short query in tens of milliseconds on a CPU.
// A container image carries it (refresh-workflow.md section 6), so a server never downloads it; elsewhere it is
// fetched once from Hugging Face into KB_MODEL_DIR.

export const EMBED_MODEL = 'jinaai/jina-embeddings-v2-base-code'
export const EMBED_DIMS = 768 // P7: also in the migration and in prepareMeaning's alter table
const DEFAULT_DIR = fileURLToPath(new URL('../.models/', import.meta.url)) // git-ignore `.models/`

type Extractor = (texts: string[], opts: { pooling: 'mean'; normalize: boolean }) => Promise<{ tolist(): number[][]; dispose?(): void }>
let loading: Promise<Extractor> | null = null

function load(): Promise<Extractor> {
  loading ??= (async () => {
    const { pipeline, env } = await import('@huggingface/transformers')
    const dir = process.env.KB_MODEL_DIR?.trim() || DEFAULT_DIR
    env.cacheDir = dir
    // A built image has the model already: never reach out to the internet from a server.
    if (existsSync(`${dir}/${EMBED_MODEL}`)) env.allowRemoteModels = false
    return (await pipeline('feature-extraction', EMBED_MODEL, { dtype: 'q8' })) as unknown as Extractor
  })()
  loading.catch(() => (loading = null)) // a failed load is tried again next time
  return loading
}

/** Embeddings of `texts`, unit length (so cosine distance is 1 - dot product). */
export async function embed(texts: string[]): Promise<number[][]> {
  if (!texts.length) return []
  const run = await load()
  const out = await run(texts, { pooling: 'mean', normalize: true })
  try {
    return out.tolist()
  } finally {
    out.dispose?.() // free the model's output now: a refresh embeds tens of thousands of sections
  }
}

/** pgvector's text form of a vector: '[0.1,0.2,…]'. */
export const toVector = (v: number[]) => `[${v.map((x) => x.toFixed(6)).join(',')}]`

/** Load the model now (the API does this in the background at start, so the first search isn't slow). */
export const warmEmbeddings = () => load().then(() => true)
```

In the API, call `warmEmbeddings().catch(() => {})` in the background at start, only when answering is enabled
(P62b). Another model: change `EMBED_MODEL`, `EMBED_DIMS`, `dtype`, the migration and the cache key in the workflow
together, and re-embed (P7, schema.md section 7).

## 8. Section refresh

```ts
// file: sections.ts
import type pg from 'pg'
import { chunkFile, chunkPassage, chunkWords } from './kb-chunks.ts'
import { EMBED_DIMS, embed, toVector } from './kb-embed.ts'

// After a repo's files are stored: cut each new or changed file into sections (kb_chunk) and embed them for meaning
// search. Incremental: a file whose sections were cut from its current version is skipped, so a scheduled run only
// does the files that changed. Committed every few files, so a long first run (every section of every repo) keeps
// what it has done if it is stopped, and the next run carries on.
//
// KB_EMBED=off   cut and word-index sections, but don't embed (meaning search stays off)

const FILES_PER_COMMIT = 40 // proven at: 40
const EMBED_BATCH = 16 // passages per model call (proven at: 16)

export type SectionResult = { files: number; sections: number; embedded: number; meaning: 'on' | 'off' | 'unavailable' }

/** Whether this database can hold embeddings: pgvector and the column. Adds the column if pgvector arrived later. */
export async function prepareMeaning(db: pg.Pool, log: (s: string) => void): Promise<boolean> {
  if (process.env.KB_EMBED?.trim() === 'off') return false
  const has = async () => (await db.query<{ ok: boolean }>(`select exists (select 1 from information_schema.columns where table_name = 'kb_chunk' and column_name = 'embedding') as ok`)).rows[0].ok
  if (await has()) return true
  const ext = (await db.query<{ ok: boolean }>(`select exists (select 1 from pg_extension where extname = 'vector') as ok`)).rows[0].ok
  if (!ext) {
    try {
      await db.query('create extension if not exists vector')
    } catch {
      log('meaning search: pgvector is not installed and this user may not create it (as a privileged user: create extension if not exists vector). Sections are word-indexed only.')
      return false
    }
  }
  await db.query(`alter table kb_chunk add column if not exists embedding vector(${EMBED_DIMS})`)
  await db.query('create index if not exists kb_chunk_embedding on kb_chunk using hnsw (embedding vector_cosine_ops)')
  log('meaning search: added the embedding column')
  return true
}

export async function refreshSections(db: pg.Pool, repoId: number, repo: string, meaning: boolean, log: (s: string) => void): Promise<SectionResult> {
  const result: SectionResult = { files: 0, sections: 0, embedded: 0, meaning: meaning ? 'on' : 'off' }
  // Files whose sections are missing or were cut from an older version, plus (with meaning on) sections still waiting
  // for an embedding from an earlier run that had none.
  const todo = (
    await db.query<{ path: string; blob_sha: string; content: string }>(
      `select f.path, f.blob_sha, f.content from kb_file f
        where f.repo_id = $1
          and not exists (select 1 from kb_chunk c where c.repo_id = f.repo_id and c.path = f.path and c.blob_sha = f.blob_sha)
        order by f.path`,
      [repoId],
    )
  ).rows
  const started = Date.now()
  for (let i = 0; i < todo.length; i += FILES_PER_COMMIT) {
    const slice = todo.slice(i, i + FILES_PER_COMMIT)
    const rows = slice.flatMap((f) => chunkFile(f.content).map((c) => ({ f, c, words: chunkWords(f.path, c) })))
    let vectors: (number[] | null)[] = rows.map(() => null)
    if (meaning) {
      try {
        vectors = []
        for (let j = 0; j < rows.length; j += EMBED_BATCH) vectors.push(...(await embed(rows.slice(j, j + EMBED_BATCH).map((r) => chunkPassage(repo, r.f.path, r.c)))))
      } catch (e) {
        // The model couldn't run: keep going with word search, and say so once.
        log(`  meaning search unavailable this run: ${(e as Error).message}`)
        meaning = false
        result.meaning = 'unavailable'
        vectors = rows.map(() => null)
      }
    }
    const client = await db.connect()
    try {
      await client.query('begin')
      await client.query('delete from kb_chunk where repo_id = $1 and path = any($2::text[])', [repoId, slice.map((f) => f.path)])
      if (rows.length) {
        const cols = ['repo_id', 'path', 'n', 'blob_sha', 'start_line', 'end_line', 'symbol', 'head', 'body']
        const args: unknown[] = [
          repoId,
          rows.map((r) => r.f.path),
          rows.map((r) => r.c.n),
          rows.map((r) => r.f.blob_sha),
          rows.map((r) => r.c.start),
          rows.map((r) => r.c.end),
          rows.map((r) => r.c.symbol),
          rows.map((r) => r.words.head),
          rows.map((r) => r.words.body),
        ]
        // $10::vector[] only when there are vectors: a database without pgvector has no vector type to cast to.
        const withVectors = vectors.some(Boolean)
        if (withVectors) args.push(vectors.map((v) => (v ? toVector(v) : null)))
        await client.query(
          `insert into kb_chunk (${cols.join(', ')}${withVectors ? ', embedding' : ''})
             select $1, * from unnest($2::text[], $3::int[], $4::text[], $5::int[], $6::int[], $7::text[], $8::text[], $9::text[]${withVectors ? ', $10::vector[]' : ''})`,
          args,
        )
      }
      await client.query('commit')
    } catch (e) {
      await client.query('rollback').catch(() => {})
      throw e
    } finally {
      client.release()
    }
    result.files += slice.length
    result.sections += rows.length
    result.embedded += vectors.filter(Boolean).length
    if (todo.length > FILES_PER_COMMIT && (i / FILES_PER_COMMIT) % 10 === 9) {
      const s = (Date.now() - started) / 1000
      log(`    sections: ${result.files}/${todo.length} files, ${result.sections} sections, ${Math.round(result.sections / s)}/s`)
    }
  }
  if (meaning) result.embedded += await backfill(db, repoId, repo, log)
  return result
}

// Sections cut by an earlier run without meaning search (pgvector arrived later, or the model failed then): embed them.
async function backfill(db: pg.Pool, repoId: number, repo: string, log: (s: string) => void): Promise<number> {
  let done = 0
  for (;;) {
    const rows = (
      await db.query<{ path: string; n: number; start_line: number; end_line: number; symbol: string | null; content: string }>(
        `select c.path, c.n, c.start_line, c.end_line, c.symbol, f.content
           from kb_chunk c join kb_file f using (repo_id, path)
          where c.repo_id = $1 and c.embedding is null
          order by c.path, c.n limit 200`,
        [repoId],
      )
    ).rows
    if (!rows.length) return done
    const passages = rows.map((r) => chunkPassage(repo, r.path, { n: r.n, start: r.start_line, end: r.end_line, symbol: r.symbol, text: r.content.split('\n').slice(r.start_line - 1, r.end_line).join('\n') }))
    const vectors: number[][] = []
    for (let j = 0; j < passages.length; j += EMBED_BATCH) vectors.push(...(await embed(passages.slice(j, j + EMBED_BATCH))))
    await db.query(
      `update kb_chunk c set embedding = v.e::vector
         from unnest($2::text[], $3::int[], $4::text[]) as v(path, n, e)
        where c.repo_id = $1 and c.path = v.path and c.n = v.n`,
      [repoId, rows.map((r) => r.path), rows.map((r) => r.n), vectors.map(toVector)],
    )
    done += rows.length
    if (done % 2000 < rows.length) log(`    embedded ${done} earlier sections`)
  }
}
```

Checks after a run: `select count(*) from kb_chunk where embedding is null` is 0, and a run killed half-way
resumes from the next un-cut file (the `not exists ... c.blob_sha = f.blob_sha` query is the resume point).

## 9. Commands

Every script and dependency the skill's blocks use, as one package (in a monorepo, split them between the indexer
and the API package; the refresh workflow calls `index`, `contracts` and `eval`).

```json
{
  "type": "module",
  "scripts": {
    "index": "node --env-file-if-exists=.env --disable-warning=ExperimentalWarning src/index.ts",
    "dry-run": "node --env-file-if-exists=.env --disable-warning=ExperimentalWarning src/index.ts --dry-run",
    "contracts": "node --env-file-if-exists=.env --disable-warning=ExperimentalWarning src/contracts-cli.ts",
    "eval": "node --env-file-if-exists=.env --disable-warning=ExperimentalWarning src/ask-eval.ts",
    "eval:search": "node --env-file-if-exists=.env --disable-warning=ExperimentalWarning src/search-eval.ts",
    "golden:pull": "node --env-file-if-exists=.env --disable-warning=ExperimentalWarning src/golden-pull.ts",
    "test": "node --disable-warning=ExperimentalWarning --test src/*.test.ts"
  },
  "dependencies": {
    "pg": "^8.23.1",
    "@huggingface/transformers": "^4.3.2",
    "@anthropic-ai/sdk": "^1.8.0",
    "zod": "^4.6.7",
    "fastify": "^5.12.7"
  },
  "devDependencies": { "@types/pg": "^8.23.1" }
}
```

zod 4 is required (`z.uuid()`, and `zodOutputFormat` from `@anthropic-ai/sdk/helpers/zod`).

`npm run index -- --only a,b` indexes some repos. Node 22 runs the `.ts` files directly (type stripping): keep the
code to erasable TypeScript (no enums, no parameter properties) and import with the `.ts` extension. Set
`ONNXRUNTIME_NODE_INSTALL=skip` wherever `npm ci` runs (P53).

## Pitfalls

- **P9. Read `git ls-tree` / `git cat-file --batch` at a ref; never check out.** A developer's working tree and
  open branch stay untouched; CI can use depth-1 checkouts.
- **P10. Two ref modes: `origin/<branch>` locally, `HEAD` in CI.** Locally it reads the fetched remote branch from
  any checkout (run `git fetch` first or you index stale code); CI has only the checked-out commit.
- **P11. Skip symlinks (mode 120000) and non-blob entries; parse `ls-tree -z --long` on the TAB.** Paths may
  contain spaces; submodules are type `commit`.
- **P12. Raise `maxBuffer` for `ls-tree` (256 MB) and read blobs through ONE `cat-file --batch` process per batch
  of 150.** The default exec buffer overflows on large repos; one process per file is slow.
- **P13. Treat a buffer containing a NUL byte as binary and skip it.** Extension lists miss some binaries.
- **P14. One transaction per repo for files; exit non-zero when any repo failed.** A failed repo keeps its previous
  index; a bad week is a red run, never a half-updated base.
- **P15. A file that becomes blocked by the secret scan must also be REMOVED if it was indexed before.**
  Otherwise its old, pre-secret version stays searchable forever.
- **P16. Log only the rule name of a secret hit, never the match or the content.** Logs are less protected than the
  database.
- **P17. Block the whole file on a real credential shape; redact likely passwords in place.** A private key or JWT
  makes the file untrustworthy; a `password = "..."` line sits in an otherwise useful file. Review what the first
  run blocks: in the source project it found real committed credentials.
- **P18. The filter is an allowlist: unrecognised files are left out.** The base holds what explains the software,
  not whatever a repo tracks: env files, per-customer settings, lockfiles, seeds and dumps, CSV and spreadsheets,
  anything over 300 KB and empty files never enter.
- **P19. Test "allowed env sample" BEFORE the secret-path rules.** `.env.example` matches the `.env*` deny rule.
- **P20. Keep SQL only under migration/schema folders, and never files named seed/dump/backup/data/fixture.** SQL
  carries customer data as easily as schema.
- **P21. Create the repo row before its files, outside the file transaction; a dry run only reads.**
- **P22. Validate `--only` names against the config and fail loudly on an unknown one.** A typo otherwise indexes
  nothing and reports success.
- **P23. Never point a laptop's `DATABASE_URL` at production "for a trial": the indexer writes.**
- **P24. Commit sections every N files (proven: 40) and select work by "no section with this file's blob SHA".**
  The first full run takes hours; a killed job is continued by the next run instead of restarting.
- **P25. Backfill `embedding is null` at the end of each repo.** Sections cut while pgvector or the model was
  unavailable would otherwise never get embeddings (their blob SHA is current, so they are never re-cut).
- **P26. A model failure mid-run downgrades that run to word-only and says so once; it never fails the repo.**
- **P26a. Embed in small batches (16) and `dispose()` the output tensor every call.** A run embeds tens of
  thousands of passages; undisposed tensors grow memory.
- **P26b. Embed a passage with context, capped: `<system> · <path>\n<symbol>\n<code>`, cut at 1,800 chars.** The
  header puts the system and file name into the vector; the cap bounds CPU time per section. Why 1,800 exactly is
  not recorded: treat it as an untuned bound, not a measured optimum.
- **P26c. Query and passage go through the same model, pooling and normalisation; store unit vectors.** Cosine
  distance is then `1 - dot`.
- **P26d. Lazy-load the model once, retry after a failed load, and forbid remote downloads when the model directory
  exists.** A server must never reach out to a model hub at request time.
- **P26e. Cut at a declaration between MIN and MAX lines, else at a blank line, else at TARGET; overlap 6 lines;
  fold a short tail into the last section; cap sections per file at 120.** A statement split by a cut is found in
  both; no stub sections; a generated 10,000-line file does not flood the index.
- **P26f. Store split identifiers alongside the raw lower-cased text.** "low battery" must find
  `lowBatteryThreshold` and `LOW_BATTERY`, and the exact identifier must still match.

## Proven at

8 repo entries, ~6,100 files, ~19,000 sections. Embedding throughput about 1 section/second on a 2-core hosted
runner (so ~5 hours for the first full run there); a scheduled run after that touches only changed files and takes
minutes. Memory: an index job peaks at ~1.3 GB with the model loaded.
