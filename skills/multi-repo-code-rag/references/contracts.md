# Contracts: which file of one system calls which route of another

Load this when the knowledge base spans two or more systems that talk over HTTP and questions follow a call across
them. With one system, skip this file: the connector lift and the `system_links` tool switch off on their own.

The code that connects two systems (an HTTP client, a callback sender) rarely shares words with a question like
"How does the dispatcher tell the order service a job is done?", so search alone misses it. After every refresh the
contracts are rebuilt whole from all indexed code files, in a few hundred milliseconds.

## 1. The model

```ts
// file: kb-contracts.ts
import type pg from 'pg'
import { systemName } from './systems.ts'

// How the systems call each other, found in the indexed code: after the repos are indexed, every code file is read,
// the HTTP routes each system serves and the URL paths each system uses are found, and the matches are kept in
// kb_contract. Search lifts the files on a link between two systems a question names (search.md section 6), and each
// search result says which other system it calls or is called by.
//
// Two kinds of link:
//   route   a URL path in one system's code matches a route another system serves (a registered extractor found it)
//   shared  the same URL path appears in HTTP code of exactly two systems (covers servers whose routes come from
//           conventions, with no declarations to find)

export type CodeFile = { repo: string; path: string; content: string }
export type Route = { repo: string; path: string; line: number; method: string; url: string; segs: string[] }
export type UrlUse = { repo: string; path: string; line: number; url: string; segs: string[]; http: boolean }
export type Contract = { kind: 'route' | 'shared'; fromRepo: string; fromPath: string; fromLine: number; toRepo: string; toPath: string; toLine: number; key: string }
```

## 2. URL normalisation and matching

```ts
// file: kb-contracts.ts (continued)
const PREFIX = new Set(['api', 'v1', 'v2', 'v3', 'v4', '1', '2', '3'])
const MIME = new Set(['application', 'text', 'image', 'multipart', 'audio', 'video', 'font'])
const NOT_A_PATH = /\s|\\|^\.|^@|\.(py|ts|js|vue|json|md|png|jpe?g|svg|css|html|cs|ya?ml|txt|csv|xlsx?|pdf|zip)$/i
const PARAM = /^(\{.*\}|\$\{.*\}|:\w+|<.*>|\d+|\*)$/
// Paths of services every system calls (sign-in, API docs, health): they don't say one system calls another.
const THIRD_PARTY = /(^|\/)(realms|protocol|openid-connect|\.well-known|oauth2?|connect|swagger|health|healthz|metrics)(\/|$)/

/** A URL path as segments without the host, query, "api" and version prefixes; parameters become '*'. Null when it
 *  isn't a URL path or has fewer than `min` fixed segments. */
export function urlSegments(raw: string, min = 2): string[] | null {
  const s = raw.replace(/^https?:\/\/[^/]+/, '').replace(/[?#].*$/, '')
  if (NOT_A_PATH.test(s)) return null
  const segs = s
    .split('/')
    .filter(Boolean)
    .map((x) => x.toLowerCase())
    .map((x) => (PARAM.test(x) || /[{}$<>]/.test(x) ? '*' : x))
  if (!segs.length || MIME.has(segs[0]) || segs.some((x) => x !== '*' && !/^[a-z][a-z0-9_.-]+$/.test(x))) return null // "n/a" is not a path
  if (THIRD_PARTY.test(segs.join('/'))) return null
  while (segs.length && PREFIX.has(segs[0])) segs.shift()
  return segs.filter((x) => x !== '*').length >= min ? segs : null
}

/** One path is the end of the other ('*' matches any segment), and both have at least two fixed segments where they
 *  overlap: a client often leaves out a prefix the server adds (a namespace, a global prefix), and the reverse, but
 *  "api/[controller]/{id}/activate" must not match every "x/{id}/activate". */
export function sameRoute(a: string[], b: string[]): boolean {
  const [short, long] = a.length <= b.length ? [a, b] : [b, a]
  const off = long.length - short.length
  const fixed = (segs: string[]) => segs.filter((x) => x !== '*').length
  if (fixed(short) < 2 || fixed(long.slice(off)) < 2) return false
  return short.every((x, i) => x === long[off + i] || x === '*' || long[off + i] === '*')
}

const lineAt = (text: string, index: number) => text.slice(0, index).split('\n').length
const join = (...parts: string[]) => `/${parts.map((p) => p.replace(/^\/+|\/+$/g, '')).filter(Boolean).join('/')}`
```

## 3. Route extractors as a registry (E6)

**Not yet proven in production in this shape.** The source has one `routesIn` function with three `if` branches;
the registry below is a refactor of it. The three regex bodies are the proven part, copied unchanged. The tests in
section 7 pass against this version.

```ts
// file: kb-contracts.ts (continued)
export type RouteContext = { constants: Map<string, string>; namespaces: Map<string, string> }
export type RouteExtractor = { name: string; test(f: CodeFile): boolean; routes(f: CodeFile, ctx: RouteContext): Route[] }

function collector(f: CodeFile) {
  const out: Route[] = []
  const add = (method: string, url: string, index: number) => {
    const segs = urlSegments(url, 1)
    if (segs) out.push({ repo: f.repo, path: f.path, line: lineAt(f.content, index), method: method.toUpperCase(), url, segs })
  }
  return { out, add }
}

// NestJS: @Controller('base') then @Post('path') on its methods. The base-prefix state machine: a class decorator
// sets the prefix, each method decorator after it adds one route under it.
export const NEST: RouteExtractor = {
  name: 'nestjs',
  test: (f) => /\.(ts|js)$/.test(f.path) && f.content.includes('@Controller'),
  routes(f) {
    const { out, add } = collector(f)
    const re = /@Controller\(\s*(?:['"`]([^'"`]*)['"`]|\{[^}]*path:\s*['"`]([^'"`]*)['"`][^}]*\})?\s*\)|@(Get|Post|Put|Patch|Delete|All)\(\s*(?:['"`]([^'"`]*)['"`])?\s*\)/g
    let base = ''
    for (const m of f.content.matchAll(re)) {
      if (m[0].startsWith('@Controller')) base = m[1] ?? m[2] ?? ''
      else add(m[3], join(base, m[4] ?? ''), m.index!)
    }
    return out
  },
}

// Flask: @app.route('/x') / @bp.route('/x'); flask-restx: @ns.route(Url_Path.x) under ns = Namespace(...). Routes are
// often built from class constants and namespace prefixes, resolved through ctx (pythonConstants, pythonNamespaces).
export const FLASK: RouteExtractor = {
  name: 'flask',
  test: (f) => f.path.endsWith('.py'),
  routes(f, { constants, namespaces }) {
    const { out, add } = collector(f)
    const value = (expr: string) => {
      const lit = /^\s*f?["']([^"']*)["']\s*$/.exec(expr)
      if (lit) return lit[1].replace(/\{([\w.]+)\}/g, (_, k) => constants.get(`${f.repo}:${k}`) ?? `{${k}}`)
      return constants.get(`${f.repo}:${expr.trim()}`) ?? null
    }
    for (const m of f.content.matchAll(/^@(\w+)\.route\(\s*([^,)]+)/gm)) {
      const path = value(m[2])
      if (path == null) continue
      const ns = namespaces.get(`${f.repo}:${m[1]}`) ?? ''
      add('ANY', join(ns, path), m.index!)
    }
    return out
  },
}

// ASP.NET: [Route("base")] on the class, [HttpPost("path")] on actions ([controller] -> '*', "~/" or "/" is absolute);
// minimal APIs: app.MapPost("/path").
export const ASPNET: RouteExtractor = {
  name: 'aspnet',
  test: (f) => f.path.endsWith('.cs'),
  routes(f) {
    const { out, add } = collector(f)
    let base = ''
    for (const m of f.content.matchAll(/\[Route\("([^"]*)"\)\]|\[Http(Get|Post|Put|Patch|Delete)(?:\("([^"]*)"\))?\]|\.Map(Get|Post|Put|Patch|Delete)\(\s*"([^"]*)"/g)) {
      if (m[1] !== undefined) base = m[1].replace(/\[controller\]/gi, '*')
      else if (m[2]) add(m[2], m[3]?.startsWith('/') || m[3]?.startsWith('~') ? m[3].replace(/^~/, '') : join(base, m[3] ?? ''), m.index!)
      else add(m[4], m[5], m.index!)
    }
    return out
  },
}

export const EXTRACTORS: RouteExtractor[] = [NEST, FLASK, ASPNET]

/** The HTTP routes a file serves. */
export function routesIn(f: CodeFile, ctx: RouteContext = { constants: new Map(), namespaces: new Map() }, extractors = EXTRACTORS): Route[] {
  return extractors.filter((e) => e.test(f)).flatMap((e) => e.routes(f, ctx))
}

/** Python class constants ("Url_Path.items" -> "/items"), for Flask routes built from them. */
export function pythonConstants(files: CodeFile[]): Map<string, string> {
  const out = new Map<string, string>()
  for (const f of files) {
    if (!f.path.endsWith('.py')) continue
    let cls: string | null = null
    for (const line of f.content.split('\n')) {
      const c = /^class\s+(\w+)/.exec(line)
      if (c) cls = c[1]
      else if (/^\S/.test(line)) cls = null
      const a = cls && /^\s+(\w+)\s*(?::\s*\w+\s*)?=\s*["']([^"']*)["']\s*(#.*)?$/.exec(line)
      if (a) out.set(`${f.repo}:${cls}.${a[1]}`, a[2])
    }
  }
  return out
}

/** flask-restx namespaces: variable -> URL prefix, from Namespace(...) and api.add_namespace(ns, path=...).
 *  The add_namespace path wins over the Namespace name. */
export function pythonNamespaces(files: CodeFile[], constants: Map<string, string>): Map<string, string> {
  const out = new Map<string, string>()
  const value = (repo: string, expr: string) => {
    const lit = /^\s*f?["']([^"']*)["']\s*$/.exec(expr)
    if (lit) return lit[1].replace(/\{([\w.]+)\}/g, (_, k) => constants.get(`${repo}:${k}`) ?? '')
    return constants.get(`${repo}:${expr.trim()}`) ?? null
  }
  for (const f of files) {
    if (!f.path.endsWith('.py')) continue
    for (const m of f.content.matchAll(/^(\w+)\s*=\s*Namespace\(\s*([^,)]+)(?:[^)]*?path\s*=\s*([^,)]+))?/gm)) {
      const p = m[3] ? value(f.repo, m[3]) : value(f.repo, m[2])
      if (p != null && !out.has(`${f.repo}:${m[1]}`)) out.set(`${f.repo}:${m[1]}`, p.startsWith('/') ? p : `/${p}`)
    }
  }
  for (const f of files) {
    if (!f.path.endsWith('.py')) continue
    for (const m of f.content.matchAll(/add_namespace\(\s*(\w+)\s*,\s*(?:path\s*=\s*)?([^)]+)\)/g)) {
      const p = value(f.repo, m[2])
      if (p != null) out.set(`${f.repo}:${m[1]}`, p)
    }
  }
  return out
}
```

### Writing an extractor for another framework (Express, FastAPI, Spring, Go)

No regex for these was run in the source; write it against the target repo's own code. The shape:

- `test(f)`: the file extension plus a cheap marker string (`express.Router`, `@app.get`, `@RestController`,
  `http.HandleFunc`), so most files are skipped without a regex.
- `routes(f, ctx)`: one global regex with alternatives for "sets a prefix" (router mount, `APIRouter(prefix=)`,
  class-level `@RequestMapping`) and "declares a route" (method + path). Walk the matches in order: a prefix match
  updates `base`, a route match calls `add(method, join(base, path), m.index)`. Prefixes set in another file (an
  Express `app.use('/x', router)`, a FastAPI `include_router(prefix=)`) need a pre-pass like `pythonNamespaces`;
  `sameRoute`'s suffix match tolerates a missing prefix, so start without one.
- Before registering it, add a test in the style of section 7: one file per routing style, asserting
  `METHOD /full/url :line` for each route, and one `findContracts` case where a client in another system links to it.

## 4. URL uses (client side, E6b)

```ts
// file: kb-contracts.ts (continued)
// E6b: signatures of HTTP client code (and of route declarations, which also mark a file as HTTP code) per language.
const HTTP = /HttpClient|PostAsync|GetAsync|PutAsync|PatchAsync|DeleteAsync|SendAsync|fetch\(|axios|requests\.(get|post|put|patch|delete)|httpx|\.(post|get|put|patch|delete)\(|@(Get|Post|Put|Patch|Delete|Controller|Http\w+)\b|\.route\(|HttpRequest|full_route|Namespace\(|Map(Get|Post|Put|Patch|Delete)\(/

/** The URL paths a file uses: string literals with at least two fixed path segments. */
export function urlsIn(f: CodeFile): UrlUse[] {
  const out: UrlUse[] = []
  const http = HTTP.test(f.content)
  f.content.split('\n').forEach((l, i) => {
    if (/^\s*(import|from|using|export \* from|\/\/|#|\*|\/\*)/.test(l)) return // imports and comments
    for (const m of l.matchAll(/["'`]([^"'`\s]{3,200})["'`]/g)) {
      const segs = urlSegments(m[1])
      if (segs) out.push({ repo: f.repo, path: f.path, line: i + 1, url: m[1], segs, http })
    }
  })
  return out
}
```

## 5. Finding the contracts

```ts
// file: kb-contracts.ts (continued)
/** Every link between two systems in these files, and the routes found. */
export function findContracts(files: CodeFile[]): { contracts: Contract[]; routes: Route[] } {
  const constants = pythonConstants(files)
  const namespaces = pythonNamespaces(files, constants)
  const routes = files.flatMap((f) => routesIn(f, { constants, namespaces }))
  // a route's own declaration is not a call to another system
  const declared = new Set(routes.map((r) => `${r.repo}:${r.path}:${r.line}`))
  const uses = files.flatMap(urlsIn).filter((u) => !declared.has(`${u.repo}:${u.path}:${u.line}`))
  const out = new Map<string, Contract>()
  const add = (c: Contract) => out.set(`${c.fromRepo}:${c.fromPath}>${c.toRepo}:${c.toPath}>${c.key}`, c)
  // SYSTEMS, not repos: a service and its worker in two repos are one system and never "call each other".
  for (const u of uses)
    for (const r of routes)
      if (systemName(u.repo) !== systemName(r.repo) && sameRoute(u.segs, r.segs))
        add({ kind: 'route', fromRepo: u.repo, fromPath: u.path, fromLine: u.line, toRepo: r.repo, toPath: r.path, toLine: r.line, key: `${r.method === 'ANY' ? '' : `${r.method} `}${r.url}` })
  const byPath = new Map<string, UrlUse[]>()
  for (const u of uses) if (u.http) byPath.set(u.segs.join('/'), [...(byPath.get(u.segs.join('/')) ?? []), u])
  for (const [key, us] of byPath) {
    // a path every system has (oauth2/token, health/check) says nothing about who talks to whom
    if (new Set(us.map((u) => systemName(u.repo))).size !== 2) continue
    for (const a of us) for (const b of us) if (systemName(a.repo) < systemName(b.repo)) add({ kind: 'shared', fromRepo: a.repo, fromPath: a.path, fromLine: a.line, toRepo: b.repo, toPath: b.path, toLine: b.line, key })
  }
  return { contracts: [...out.values()], routes }
}
```

A `shared` link has no direction: `from` is simply the system whose name sorts first.

## 6. Database side and the standalone script

```ts
// file: kb-contracts.ts (continued)
// E6: the languages whose files are read for routes and URL uses.
const CONTRACT_LANGUAGES = ['typescript', 'javascript', 'vue', 'python', 'csharp']

/** Rebuild kb_contract from every indexed code file (after all repos of a refresh). */
export async function refreshContracts(db: pg.Pool): Promise<{ files: number; routes: number; contracts: number }> {
  const files = (
    await db.query<CodeFile>(
      `select r.name as repo, f.path, f.content from kb_file f join kb_repo r on r.id = f.repo_id
        where f.kind = 'code' and f.language = any($1::text[])`,
      [CONTRACT_LANGUAGES],
    )
  ).rows
  const { contracts, routes } = findContracts(files)
  const client = await db.connect()
  try {
    await client.query('begin')
    await client.query('delete from kb_contract')
    for (let i = 0; i < contracts.length; i += 500) {
      const part = contracts.slice(i, i + 500)
      await client.query(
        `insert into kb_contract (kind, from_repo_id, from_path, from_line, to_repo_id, to_path, to_line, key)
         select c.kind, fr.id, c.from_path, c.from_line, tr.id, c.to_path, c.to_line, c.key
           from unnest($1::text[], $2::text[], $3::text[], $4::int[], $5::text[], $6::text[], $7::int[], $8::text[])
                  as c(kind, from_repo, from_path, from_line, to_repo, to_path, to_line, key)
           join kb_repo fr on fr.name = c.from_repo join kb_repo tr on tr.name = c.to_repo`,
        [part.map((c) => c.kind), part.map((c) => c.fromRepo), part.map((c) => c.fromPath), part.map((c) => c.fromLine), part.map((c) => c.toRepo), part.map((c) => c.toPath), part.map((c) => c.toLine), part.map((c) => c.key)],
      )
    }
    await client.query('commit')
  } catch (e) {
    await client.query('rollback').catch(() => {})
    throw e
  } finally {
    client.release()
  }
  return { files: files.length, routes: routes.length, contracts: contracts.length }
}

export type Link = { repo: string; path: string; otherRepo: string; otherPath: string; otherLine: number; key: string; calls: boolean }

/** The links of these files to other systems: what each calls, and what calls it. */
export async function linksOf(client: pg.PoolClient | pg.Pool, files: { repo: string; path: string }[]): Promise<Link[]> {
  if (!files.length) return []
  const r = await client.query<Link>(
    `with want(repo, path) as (select * from unnest($1::text[], $2::text[]))
     select fr.name as repo, c.from_path as path, tr.name as "otherRepo", c.to_path as "otherPath", c.to_line as "otherLine", c.key, true as calls
       from kb_contract c join kb_repo fr on fr.id = c.from_repo_id join kb_repo tr on tr.id = c.to_repo_id
       join want w on w.repo = fr.name and w.path = c.from_path
     union all
     select tr.name, c.to_path, fr.name, c.from_path, c.from_line, c.key, false
       from kb_contract c join kb_repo fr on fr.id = c.from_repo_id join kb_repo tr on tr.id = c.to_repo_id
       join want w on w.repo = tr.name and w.path = c.to_path`,
    [files.map((f) => f.repo), files.map((f) => f.path)],
  )
  return r.rows
}

/** The files on a link between any two of these systems' repos (either end). */
export async function connectorFiles(client: pg.PoolClient | pg.Pool, repos: string[]): Promise<{ repo: string; path: string }[]> {
  const systems = [...new Set(repos.map(systemName))]
  if (systems.length < 2) return []
  const r = await client.query<{ repo: string; path: string }>(
    `select distinct x.repo, x.path from kb_contract c
       join kb_repo fr on fr.id = c.from_repo_id join kb_repo tr on tr.id = c.to_repo_id,
       lateral (values (fr.name, c.from_path), (tr.name, c.to_path)) as x(repo, path)
      where fr.name = any($1::text[]) and tr.name = any($1::text[])`,
    [repos],
  )
  return r.rows
}

/** The `system_links` tool: how one repo's system calls another's (or every other), both directions, as text. */
export async function systemLinks(db: pg.Pool, a: { repo: string; other?: string }): Promise<string> {
  const r = await db.query<{ from_repo: string; from_path: string; from_line: number; to_repo: string; to_path: string; to_line: number; key: string; kind: string }>(
    `select fr.name as from_repo, c.from_path, c.from_line, tr.name as to_repo, c.to_path, c.to_line, c.key, c.kind
       from kb_contract c join kb_repo fr on fr.id = c.from_repo_id join kb_repo tr on tr.id = c.to_repo_id
      where (fr.name = $1 and ($2::text is null or tr.name = $2)) or (tr.name = $1 and ($2::text is null or fr.name = $2))
      order by fr.name, tr.name, c.key, c.from_path
      limit 200`,
    [a.repo, a.other ?? null],
  )
  // The blind spots, said in the tool's own output, so the model searches for the client instead of concluding "no call".
  if (!r.rows.length)
    return `No links found between ${a.repo} and ${a.other ?? 'the other repos'}. Links are HTTP calls whose URL path is written in the code; a URL that comes from configuration (a callback URL, a base URL per site) is not seen. Search or grep for the client instead.`
  const groups = new Map<string, string[]>()
  for (const x of r.rows) {
    const g = `${x.from_repo} (${systemName(x.from_repo)}) calls ${x.to_repo} (${systemName(x.to_repo)})`
    if (!groups.has(g)) groups.set(g, [])
    groups.get(g)!.push(`  ${x.key}${x.kind === 'shared' ? ' (same path in both)' : ''}\n    ${x.from_repo}:${x.from_path}:${x.from_line} -> ${x.to_repo}:${x.to_path}:${x.to_line}`)
  }
  const out = [...groups].map(([g, lines]) => `${g}: ${lines.length} link${lines.length === 1 ? '' : 's'}\n${lines.slice(0, 25).join('\n')}${lines.length > 25 ? `\n  (${lines.length - 25} more)` : ''}`)
  return `${out.join('\n\n')}\n\nFound from URL paths written in the code: read the client and the handler before relying on a link.`
}
```

The standalone script the refresh workflow runs once, after every per-repo job:

```ts
// file: contracts-cli.ts
import pg from 'pg'
import { databaseConfig } from './config.ts'
import { migrate } from './db.ts'
import { refreshContracts } from './kb-contracts.ts'

// The links between systems, rebuilt from every indexed code file. The parallel refresh indexes each repo in its own
// job with KB_CONTRACTS=off, then runs this once, after all of them: `npm run contracts`.

const db = new pg.Pool({ ...databaseConfig(), max: 2 })
try {
  await migrate(db, (line) => console.log(`migrate: ${line}`))
  const c = await refreshContracts(db)
  console.log(`links between systems: ${c.contracts} from ${c.routes} routes in ${c.files} code files`)
} finally {
  await db.end()
}
```

## 7. Tests

Example repo names only. `systemName` maps an unknown repo to itself, so these run with an empty `SYSTEM_NAMES`.

```ts
// file: kb-contracts.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { findContracts, pythonConstants, pythonNamespaces, routesIn, sameRoute, urlSegments, type CodeFile } from './kb-contracts.ts'

test('URL paths: host, query, api and version prefixes go; parameters become *; non-paths are refused', () => {
  assert.deepEqual(urlSegments('https://orders:3000/v3/orders/{id}/confirm?x=1'), ['orders', '*', 'confirm'])
  assert.deepEqual(urlSegments('api/v1/stations/call-next'), ['stations', 'call-next'])
  assert.deepEqual(urlSegments('/orders/:orderNo/items/:itemCode'), ['orders', '*', 'items', '*'])
  for (const no of ['application/json', 'n/a', './dispatch.ts', '@acme/database', 'src/app.py', 'europe london', 'realms/x/protocol/openid-connect/token', 'v1/status'])
    assert.equal(urlSegments(no), null, no)
})

test('a client path matches a route when one ends the other, with two fixed segments on both sides', () => {
  assert.ok(sameRoute(['orders', 'confirm'], ['orders', 'confirm']))
  assert.ok(sameRoute(['jobs-module', 'job-queue'], ['job-queue']) === false, 'one fixed segment is too little')
  assert.ok(sameRoute(['dispatch', 'orders', '*', 'confirm'], ['orders', '*', 'confirm']), 'a prefix the client adds')
  assert.ok(!sameRoute(['users', '*', 'activate'], ['*', '*', 'activate']), '[controller] routes match nothing')
  assert.ok(!sameRoute(['orders', 'picked'], ['orders', 'confirm']))
})

test('routes: NestJS controllers, flask-restx namespaces built from constants, ASP.NET attributes and minimal APIs', () => {
  const nest: CodeFile = { repo: 'orders-api', path: 'order.controller.ts', content: "@Controller('v3/orders')\nexport class C {\n  @Post('confirm')\n  a() {}\n  @Get()\n  b() {}\n}\n" }
  assert.deepEqual(routesIn(nest).map((r) => `${r.method} ${r.url} :${r.line}`), ['POST /v3/orders/confirm :3', 'GET /v3/orders :5'])

  const files: CodeFile[] = [
    { repo: 'dispatch', path: 'app/api_routing.py', content: 'class Url_Namespace:\n    jobs = "/jobs-module"\n\nclass Url_Path:\n    queue = "/job-queue"\n' },
    { repo: 'dispatch', path: 'app/__init__.py', content: 'api.add_namespace(ns_jobs, path=f"{Url_Namespace.jobs}")\n' },
    { repo: 'dispatch', path: 'ns.py', content: 'ns_jobs = Namespace("Jobs", "about")\n\n@ns_jobs.route(Url_Path.queue)\nclass S(Resource):\n    def post(self): ...\n' },
  ]
  const constants = pythonConstants(files)
  assert.equal(constants.get('dispatch:Url_Path.queue'), '/job-queue')
  const namespaces = pythonNamespaces(files, constants)
  assert.equal(namespaces.get('dispatch:ns_jobs'), '/jobs-module', 'add_namespace path wins over the Namespace name')
  assert.deepEqual(routesIn(files[2], { constants, namespaces }).map((r) => r.url), ['/jobs-module/job-queue'])

  const cs: CodeFile = { repo: 'billing', path: 'E.cs', content: '[Route("api/v1/stations")]\nclass S {\n  [HttpPost("{id}/enable")]\n  void A() {}\n}\napp.MapGet("/api/v1/callbacks/orders/events", H);\n' }
  assert.deepEqual(routesIn(cs).map((r) => `${r.method} ${r.url}`), ['POST /api/v1/stations/{id}/enable', 'GET /api/v1/callbacks/orders/events'])
})

test("links: a call to another system's route, the same path in two systems' HTTP code, never a declaration or a path three systems share", () => {
  const files: CodeFile[] = [
    { repo: 'dispatch', path: 'orders_client.py', content: 'import requests\nrequests.post(f"{HOST}/v3/orders/{oid}/confirm")\nrequests.get("/oauth2/token")\n' },
    { repo: 'orders-api', path: 'order.controller.ts', content: "@Controller('v3/orders')\nclass C {\n  @Post(':id/confirm')\n  a() {}\n}\nfetch('/health/check/now')\n" },
    { repo: 'shop', path: 'StationClient.cs', content: 'HttpClient c;\nPostAsync("api/v1/stations/call-next", x);\n' },
    { repo: 'stations', path: 'StationBroker.cs', content: 'HttpClient c;\nPostAsync("api/v1/stations/call-next", x);\n' },
    { repo: 'stations', path: 'Mine.cs', content: 'app.MapPost("/api/v1/stations/call-next", H);\n' },
  ]
  const { contracts } = findContracts(files)
  const seen = contracts.map((c) => `${c.kind} ${c.fromRepo}:${c.fromPath}:${c.fromLine} -> ${c.toRepo}:${c.toPath} [${c.key}]`).sort()
  assert.deepEqual(seen, [
    'route dispatch:orders_client.py:2 -> orders-api:order.controller.ts [POST /v3/orders/:id/confirm]',
    'route shop:StationClient.cs:2 -> stations:Mine.cs [POST /api/v1/stations/call-next]',
    'shared shop:StationClient.cs:2 -> stations:StationBroker.cs [stations/call-next]', // a shared path has no direction
  ])
})
```

## 8. Known blind spots

| Blind spot | Why | What covers it |
|---|---|---|
| URL from configuration (callback URLs, a base URL per site) | No path literal in the calling code | Nothing; `systemLinks` says so and tells the model to search for the client |
| One-word paths (`POST {BASE}/order`) | Fewer than two fixed segments would match everything | Nothing; search |
| Convention-routed servers (routes generated from class names) | No route declarations to extract | `shared` links, when the client and the server's own HTTP code both carry the path |
| Non-HTTP transports (queues, gRPC, sockets) | Not attempted | Nothing yet; a topic-name extractor would follow the same `route`/`shared` model |

## Pitfalls

- **P41. Build contracts ONCE after all repos, never inside parallel per-repo jobs.** The rebuild deletes and
  rewrites the whole table from every indexed code file; concurrent jobs would race and each would see a partial
  base. Per-repo jobs run with `KB_CONTRACTS=off`; `contracts-cli.ts` runs after them.
- **P42. Require two fixed segments on both sides of a match; map framework placeholders to `*`.** Otherwise
  `api/[controller]/{id}/activate` links to every `x/{id}/activate`.
- **P43. Strip `api` and version prefixes and match by suffix.** Clients and servers disagree about prefixes
  (global prefix, namespace, gateway).
- **P44. Exclude a route's own declaration line, MIME types, file-looking strings, and paths every system calls
  (sign-in, health, metrics, swagger).** They are not calls between your systems.
- **P45. A `shared` link needs HTTP code on both sides and EXACTLY two systems.** A path three systems use says
  nothing about who talks to whom; convention-routed servers have no declared routes, so `shared` is their only
  signal.
- **P46. State the blind spots in the tool's own output.** URLs from configuration and one-word paths are not found:
  4 of 6 known hops were found in the source project. The "no links" message tells the model to search for the
  client instead.
- **P46a. Compare SYSTEMS, not repos, when two repos are one system.** Otherwise a service and its background worker
  "call each other".
- **P46b. Resolve route constants before matching (Python class constants, namespace prefixes); the
  `add_namespace` path wins over the `Namespace(...)` name.** Real routes are often built from constants.
- **P46c. Lift at most 3 connector files, after the fifth result, only ones the search found at all (depth 200),
  and only when the question names two systems.** Lifting blindly pushes better results out; measured top-12
  42% -> 58% (search.md section 6).

## Proven at

~170 links from 8 repo entries (NestJS, Flask/flask-restx and ASP.NET servers; one convention-routed .NET server
covered by `shared` links); rebuild in a few hundred milliseconds; 4 of the 6 hops the team could name were found,
the other two being a config-supplied callback URL and a one-word path.
