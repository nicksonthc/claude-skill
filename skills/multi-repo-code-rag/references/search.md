# Search: hybrid retrieval and the lookup tools

Load this when building or tuning retrieval: query shaping, rare-word weights, the two candidate SQL statements,
rank fusion, the connector lift, the fallbacks, and the text format of every lookup tool the answering model calls.
All of it lives in one file, `kb.ts`, shared by the API and the evals.

## 1. Read-only query helper

Every lookup runs in a read-only transaction with a short statement timeout (P34).

```ts
// file: kb.ts
import type pg from 'pg'
import { splitIdentifiers } from './kb-chunks.ts'
import { connectorFiles, linksOf } from './kb-contracts.ts'
import { embed, toVector } from './kb-embed.ts'
import { SYSTEM_REPOS, SYSTEM_WORDS, systemName } from './systems.ts'

// The read-only tools the model uses to look at the knowledge base. Each takes plain arguments, returns text, and
// never throws on a bad argument: the text says what was wrong so the model can correct itself.

export type Db = pg.Pool

const MAX_LINES_PER_READ = 400
const MAX_READ_BYTES = 40_000
const LINE_WIDTH = 220

// One query inside a transaction with a short timeout, so a slow search can't hold a connection.
async function q<T extends pg.QueryResultRow>(db: Db, sql: string, params: unknown[]) {
  const client = await db.connect()
  try {
    await client.query('begin read only')
    await client.query("set local statement_timeout = '5s'")
    const r = await client.query<T>(sql, params)
    await client.query('commit')
    return r.rows
  } catch (e) {
    await client.query('rollback').catch(() => {})
    throw e
  } finally {
    client.release()
  }
}

const clip = (s: string) => (s.length > LINE_WIDTH ? `${s.slice(0, LINE_WIDTH)}…` : s)
const KINDS = ['code', 'test', 'doc', 'setting', 'schema']
const short = (sha: string | null) => (sha ? sha.slice(0, 7) : 'unknown')
```

## 2. Query shaping

```ts
// file: kb.ts (continued)
// A question as keywords, the way the model types its own searches: common words dropped. Searching a question this
// way finds more than searching it as written (the meaning search isn't pulled by "how", "does", "the").
const COMMON = new Set('a an and are as at be by can could do does did for from has have how if in into is it its of on or should so than that the then there these this to under was what when where which while who why will with would you your'.split(' '))
export const keywords = (q: string) => (q.toLowerCase().match(/[a-z0-9_]+/g) ?? []).filter((w) => w.length > 2 && !COMMON.has(w)).join(' ')

// Words worth searching for in a question: identifiers and plain words, 3+ characters, no duplicates.
export function terms(query: string): string[] {
  const out = new Set<string>()
  for (const t of query.toLowerCase().match(/[a-z0-9_]{3,}/g) ?? []) out.add(t)
  return [...out].slice(0, 12)
}

type Hit = { line: number; text: string }

// The lines of `content` that mention the most of `words`, best first.
export function bestLines(content: string, words: string[], limit: number): Hit[] {
  const lines = content.split('\n')
  const scored: (Hit & { score: number })[] = []
  for (let i = 0; i < lines.length; i++) {
    const lower = lines[i].toLowerCase()
    let score = 0
    for (const w of words) if (lower.includes(w)) score++
    if (score) scored.push({ line: i + 1, text: clip(lines[i].trim()), score })
  }
  return scored.sort((a, b) => b.score - a.score || a.line - b.line).slice(0, limit).sort((a, b) => a.line - b.line)
}

const fmtHits = (hits: Hit[]) => hits.map((h) => `    L${h.line}: ${h.text}`).join('\n')

/** The query with the systems' short names spelled out (both for words and for meaning). */
export function expandSystems(query: string): string {
  const extra = new Set<string>()
  for (const t of query.toLowerCase().match(/[a-z]+/g) ?? []) if (SYSTEM_WORDS[t]) extra.add(SYSTEM_WORDS[t])
  return extra.size ? `${query} (${[...extra].join(', ')})` : query
}

// Words for the section search: as typed, and with code names split, letters and digits only (tsquery-safe).
function chunkTerms(query: string): string[] {
  const out = new Set<string>()
  const q = expandSystems(query)
  for (const t of `${q.toLowerCase()} ${splitIdentifiers(q)}`.match(/[a-z0-9]{3,}/g) ?? []) out.add(t)
  return [...out].slice(0, 24)
}

// Which systems a question names, as their repos. Their files get a lift in the ranking (a question about system X
// is answered by X's code, not by code that mentions X).
export function systemsIn(query: string): string[] {
  const q = query.toLowerCase()
  return [...new Set(SYSTEM_REPOS.flatMap(([re, repos]) => (re.test(q) ? repos : [])))]
}
```

## 3. Rare-word weights (IDF)

```ts
// file: kb.ts (continued)
// How much each word of a search is worth: rare words (in few sections) count more than words in thousands
// ("409", "callback" over the domain nouns every file uses). Inverse document frequency, per stemmed word, kept
// for five minutes.
type Weighted = { lex: string; idf: number }
let rarity: { at: number; total: number; df: Map<string, { lex: string; df: number }> } | null = null
async function weigh(client: pg.PoolClient, words: string[]): Promise<Weighted[]> {
  if (!rarity || Date.now() - rarity.at > 5 * 60_000) {
    const n = await client.query<{ n: number }>('select count(*)::int as n from kb_chunk')
    rarity = { at: Date.now(), total: n.rows[0].n, df: new Map() }
  }
  const missing = words.filter((w) => !rarity!.df.has(w))
  if (missing.length) {
    const r = await client.query<{ w: string; lex: string; df: number }>(
      `select w, plainto_tsquery('english', w)::text as lex,
              (select count(*) from kb_chunk where tsv @@ plainto_tsquery('english', w))::int as df
         from unnest($1::text[]) w`,
      [missing],
    )
    for (const x of r.rows) rarity.df.set(x.w, { lex: x.lex, df: x.df })
  }
  const out = new Map<string, Weighted>() // "charging" and "charge" are one word once stemmed
  for (const w of words) {
    const d = rarity.df.get(w)
    if (!d || !d.lex || d.lex.includes(' ') || out.has(d.lex)) continue // a stop word, or two words
    out.set(d.lex, { lex: d.lex, idf: Math.log((rarity.total + 1) / (d.df + 1)) })
  }
  return [...out.values()]
}
```

## 4. The two candidate lists

Two SQL statements, one per list, each returning SECTIONS best-first. The word list orders by the summed rarity of
the query words a section holds (a word in its path or symbol counting more when `head > 0`), then `ts_rank`. The
meaning list orders by cosine distance over the HNSW index, with `ef_search` raised to at least the LIMIT inside the
transaction (P27; `rag-layer-audit` probe Q3).

```ts
// file: kb.ts (continued)
/** How the two lists are merged; `search-eval -- --grid` tries others. Measured on the golden questions:
 *  k 10 rather than the usual 60, so a file near the top of one list isn't beaten by files middling in both, and the
 *  named systems' own files lifted by half. Lower weights for tests or docs, extra weight for a word in the path or
 *  name, or weighting one list over the other did not help. */
export type Fusion = { k: number; words: number; meaning: number; test: number; doc: number; system: number; head: number }
export const FUSION: Fusion = { k: 10, words: 1, meaning: 1, test: 1, doc: 1, system: 1.5, head: 0 }

type Cand = { repo_id: number; repo: string; path: string; n: number; kind: string }
export type Lists = { byWords: Cand[]; byMeaning: Cand[]; systems: string[] }

export type Ranked = { repo: string; sha: string | null; path: string; kind: string; start: number | null; end: number | null; symbol: string | null; content: string }
type Opts = { query: string; repo?: string; kind?: string; limit?: number }

/** The two candidate lists for a search, best section first: by (rare) words, and by meaning. */
export async function searchLists(client: pg.PoolClient, a: Opts & { vector?: number[] | null }, pool: number, f: Fusion = FUSION): Promise<Lists> {
  const weights = await weigh(client, chunkTerms(a.query))
  const byWords = weights.length
    ? (
        await client.query<Cand>(
          // A section scores the rarity of each search word it holds, a word in its path or name counting more;
          // the plain text rank breaks ties.
          `select c.repo_id, c.path, c.n, f.kind, r.name as repo
             from kb_chunk c join kb_file f using (repo_id, path) join kb_repo r on r.id = c.repo_id,
                  to_tsquery('english', $1) any_q
            where c.tsv @@ any_q
              and ($2::text is null or r.name = $2)
              and ($3::text is null or f.kind = $3)
            order by (select coalesce(sum(w.idf * (case when c.tsv @@ (w.lex || ':A')::tsquery then 1 + $6::float8 else 1 end)), 0)
                        from unnest($4::text[], $5::float8[]) as w(lex, idf)
                       where c.tsv @@ w.lex::tsquery) desc,
                     ts_rank(c.tsv, any_q, 1) desc
            limit $7`,
          [weights.map((w) => w.lex).join(' | '), a.repo ?? null, a.kind ?? null, weights.map((w) => w.lex), weights.map((w) => w.idf), f.head, pool],
        )
      ).rows
    : []
  let byMeaning: Cand[] = []
  if (a.vector) {
    // pgvector returns at most ef_search rows (default 40): a LIMIT 60 or 200 would silently come back short.
    await client.query(`set local hnsw.ef_search = ${Math.max(120, pool)}`)
    byMeaning = (
      await client.query<Cand>(
        `select c.repo_id, c.path, c.n, f.kind, r.name as repo
           from kb_chunk c join kb_file f using (repo_id, path) join kb_repo r on r.id = c.repo_id
          where c.embedding is not null
            and ($2::text is null or r.name = $2)
            and ($3::text is null or f.kind = $3)
          order by c.embedding <=> $1::vector
          limit $4`,
        [toVector(a.vector), a.repo ?? null, a.kind ?? null, pool],
      )
    ).rows
  }
  return { byWords, byMeaning, systems: a.repo ? [] : systemsIn(a.query) }
}
```

Known limit, not hit at the proven corpus size: the meaning query filters by repo/kind AFTER the HNSW scan, so a
selective filter can return fewer than `pool` rows even with `ef_search` raised. Remedies (untested here): pgvector
0.8's iterative scan (`set local hnsw.iterative_scan = relaxed_order`) or a larger `ef_search` when a filter is set.

## 5. Fusion

Rank sections, answer with files: each file takes its best place in each list, contributes `weight / (k + place)`
per list, is multiplied by the kind and system priors, and keeps the section that placed it highest (P28, P29;
`rag-layer-audit` probe Q5).

```ts
// file: kb.ts (continued)
/** Files ranked from the two lists: reciprocal rank fusion over each file's best place in each list, with code
 *  above tests and docs and the named systems lifted. Each file keeps the section that placed it highest. */
export function fuse(l: Lists, limit: number, f: Fusion = FUSION): Cand[] {
  const files = new Map<string, { c: Cand; s: number; best: number }>()
  for (const [list, weight] of [
    [l.byWords, f.words],
    [l.byMeaning, f.meaning],
  ] as const) {
    let rank = 0
    const seen = new Set<string>()
    for (const c of list) {
      const key = `${c.repo_id}\n${c.path}`
      if (seen.has(key)) continue
      seen.add(key)
      const part = weight / (f.k + ++rank)
      const e = files.get(key)
      if (!e) files.set(key, { c, s: part, best: part })
      else {
        e.s += part
        if (part > e.best) Object.assign(e, { c, best: part })
      }
    }
  }
  const prior = (c: Cand) => (c.kind === 'test' ? f.test : c.kind === 'doc' ? f.doc : 1) * (l.systems.includes(c.repo) ? f.system : 1)
  return [...files.values()]
    .map((e) => ({ c: e.c, s: e.s * prior(e.c) }))
    .sort((x, y) => y.s - x.s)
    .slice(0, limit)
    .map((e) => e.c)
}
```

## 6. Connector lift

A question that names two systems is usually answered by the code that connects them (an HTTP client, a callback
sender), which rarely shares words with the question. The files on a contract between the named systems
(contracts.md) that the search found at all go in after the fifth result (P46c).

```ts
// file: kb.ts (continued)
// Measured on the golden questions: the expected file in the top 12 went from 42% to 58%.
export const CONNECTORS = 3 // at most this many lifted
const POOL = 60 // each list's depth for the ranking
const DEEP = 200 // how deep a connector may be found

/** `top` with up to CONNECTORS of `connectors` (repo:path) placed after its fifth result, in their order in `deep`. */
export function liftConnectors<T extends { repo: string; path: string }>(top: T[], deep: T[], connectors: Set<string>, limit: number): T[] {
  if (!connectors.size) return top.slice(0, limit)
  const key = (c: T) => `${c.repo}:${c.path}`
  const head = top.slice(0, 5)
  const lifted = deep.filter((c) => connectors.has(key(c)) && !head.some((h) => key(h) === key(c))).slice(0, CONNECTORS)
  const out: T[] = []
  for (const c of [...head, ...lifted, ...top.slice(5)]) if (!out.some((o) => key(o) === key(c))) out.push(c)
  return out.slice(0, limit)
}

/** The files ranked for a search: the two lists merged, and the connecting files of the systems it names. */
export async function rankCandidates(client: pg.PoolClient, a: Opts & { vector?: number[] | null }, limit: number, f: Fusion = FUSION) {
  const repos = a.repo ? [] : systemsIn(a.query)
  const named = new Set(repos.map(systemName)).size >= 2 // two SYSTEMS, not two repos of one system
  const lists = await searchLists(client, a, named ? DEEP : POOL, f)
  const cut = { ...lists, byWords: lists.byWords.slice(0, POOL), byMeaning: lists.byMeaning.slice(0, POOL) }
  const top = fuse(cut, limit, f)
  if (!named) return top
  const connectors = new Set((await connectorFiles(client, repos).catch(() => [])).map((c) => `${c.repo}:${c.path}`))
  return liftConnectors(top, fuse(lists, DEEP, f), connectors, limit)
}
```

## 7. Orchestration and fallbacks

Word search is the floor: no sections yet -> whole files; no pgvector or a model that fails -> words only, with a
10-minute circuit breaker so every search does not pay the failed load again (P35, P36).

```ts
// file: kb.ts (continued)
/** Whole-file word search: the original ranking, and the fallback. */
export async function rankFiles(db: Db, a: Opts): Promise<Ranked[]> {
  const words = terms(a.query)
  if (!words.length) return []
  // Files with every word rank above files with some; a word in the path ranks above a word in the text.
  const rows = await q<{ repo: string; sha: string | null; path: string; kind: string; content: string }>(
    db,
    `select r.name as repo, r.last_sha as sha, f.path, f.kind, f.content
       from kb_file f join kb_repo r on r.id = f.repo_id,
            to_tsquery('simple', $1) any_q, to_tsquery('simple', $2) all_q
      where f.tsv @@ any_q
        and ($3::text is null or r.name = $3)
        and ($4::text is null or f.kind = $4)
      order by (case when f.tsv @@ all_q then 10 else 0 end) + ts_rank(f.tsv, any_q, 1) desc
      limit $5`,
    [words.join(' | '), words.join(' & '), a.repo ?? null, a.kind ?? null, a.limit ?? 12],
  )
  return rows.map((r) => ({ ...r, start: null, end: null, symbol: null }))
}

let sections: { at: number; chunks: boolean; vectors: boolean } | null = null
async function sectionState(db: Db) {
  if (sections && Date.now() - sections.at < 5 * 60_000) return sections
  const r = await db.query<{ chunks: boolean; vectors: boolean }>(
    `select exists (select 1 from kb_chunk) as chunks,
            exists (select 1 from information_schema.columns where table_name = 'kb_chunk' and column_name = 'embedding') as vectors`,
  )
  sections = { at: Date.now(), ...r.rows[0] }
  return sections
}

/** Sections ranked by words and by meaning, fused, best section per file. `vector` is the query's embedding, if any. */
export async function rankHybrid(db: Db, a: Opts & { vector?: number[] | null }, f: Fusion = FUSION): Promise<Ranked[]> {
  const limit = a.limit ?? 12
  const client = await db.connect()
  try {
    await client.query('begin read only')
    await client.query("set local statement_timeout = '8s'")
    const top = await rankCandidates(client, a, limit, f)
    if (!top.length) {
      await client.query('commit')
      return []
    }
    const details = await client.query<{ repo_id: number; path: string; n: number; repo: string; sha: string | null; kind: string; start_line: number; end_line: number; symbol: string | null; content: string }>(
      `select c.repo_id, c.path, c.n, r.name as repo, r.last_sha as sha, f.kind, c.start_line, c.end_line, c.symbol, f.content
         from unnest($1::int[], $2::text[], $3::int[]) as want(repo_id, path, n)
         join kb_chunk c using (repo_id, path, n) join kb_file f using (repo_id, path) join kb_repo r on r.id = c.repo_id`,
      [top.map((t) => t.repo_id), top.map((t) => t.path), top.map((t) => t.n)],
    )
    await client.query('commit')
    const at = new Map(details.rows.map((d) => [`${d.repo_id}\n${d.path}\n${d.n}`, d]))
    return top.flatMap((t) => {
      const d = at.get(`${t.repo_id}\n${t.path}\n${t.n}`)
      return d ? [{ repo: d.repo, sha: d.sha, path: d.path, kind: d.kind, start: d.start_line, end: d.end_line, symbol: d.symbol, content: d.content }] : []
    })
  } catch (e) {
    await client.query('rollback').catch(() => {})
    throw e
  } finally {
    client.release()
  }
}

let meaningDown = false
/** The query's embedding, or null when meaning search is off or the model can't load (then words alone rank). */
async function queryVector(query: string): Promise<number[] | null> {
  if (meaningDown) return null
  try {
    return (await embed([query]))[0] ?? null
  } catch (e) {
    meaningDown = true
    console.warn(`Meaning search is off: the embedding model did not load (${(e as Error).message}). Word search still works.`)
    setTimeout(() => (meaningDown = false), 10 * 60_000).unref?.()
    return null
  }
}

/** The best search available: sections by words and meaning once they exist, else whole files. */
export async function rank(db: Db, a: Opts): Promise<Ranked[]> {
  const st = await sectionState(db).catch(() => ({ chunks: false, vectors: false }))
  if (!st.chunks) return rankFiles(db, a)
  return rankHybrid(db, { ...a, vector: st.vectors ? await queryVector(expandSystems(a.query)) : null })
}
```

**Stale sections between the two phases (not yet proven in production).** Files are upserted and committed per
repo before their sections are re-cut, so for minutes a changed file has sections with old line ranges, and search
shows lines of the new content at old offsets. The source leaves this open. Adding `and c.blob_sha = f.blob_sha`
to both list queries in `searchLists` would close it, at the price of a changed file dropping out of section
search until it is re-cut (untested).

## 8. Tool output formats

The header line `repo@sha7:path  [kind]  lines a-b  in <symbol>` is what the citation format
`[repo@sha:path:line]` is built from (`CITATION` in answering.md section 5): keep the two in step.

```ts
// file: kb.ts (continued)
export async function repoMap(db: Db): Promise<string> {
  const rows = await q<{ name: string; branch: string; last_sha: string | null; indexed_at: Date | null; files: number; code: number; docs: number }>(
    db,
    `select r.name, r.branch, r.last_sha, r.indexed_at,
            count(f.path)::int as files,
            count(f.path) filter (where f.kind in ('code', 'test'))::int as code,
            count(f.path) filter (where f.kind = 'doc')::int as docs
       from kb_repo r left join kb_file f on f.repo_id = r.id group by r.id order by r.name`,
    [],
  )
  if (!rows.length) return 'The knowledge base is empty: nothing has been indexed yet.'
  return rows
    .map((r) => `${r.name}  branch ${r.branch}  @${short(r.last_sha)}  indexed ${r.indexed_at?.toISOString().slice(0, 10) ?? 'never'}  ${r.files} files (${r.code} code/test, ${r.docs} docs)`)
    .join('\n')
}

// The first results show the code of the section that matched (up to 40 lines, numbered), so the model can judge them
// and cite them without a read; the rest show their three best lines.
const SHOWN = 3
const SHOWN_LINES = 40

export async function search(db: Db, a: { query: string; repo?: string; kind?: string }): Promise<string> {
  if (!terms(a.query).length && !chunkTerms(a.query).length) return 'Give at least one word of three or more letters to search for.'
  if (a.kind && !KINDS.includes(a.kind)) return `kind must be one of ${KINDS.join(', ')}.`
  const rows = await rank(db, a)
  if (!rows.length) return `No file matches "${a.query}". Try other words, a function or setting name, or grep for an exact string.`
  const words = chunkTerms(a.query)
  const links = await linksOf(db, rows).catch(() => [])
  const named = new Set(systemsIn(a.query))
  // What a file calls in another system, or is called by: at most two, the systems the search names first.
  const linkLines = (r: Ranked) =>
    links
      .filter((l) => l.repo === r.repo && l.path === r.path)
      .sort((x, y) => Number(named.has(y.otherRepo)) - Number(named.has(x.otherRepo)))
      .filter((l, i, all) => all.findIndex((m) => m.otherRepo === l.otherRepo && m.otherPath === l.otherPath) === i)
      .slice(0, 2)
      .map((l) => `    ${l.calls ? 'calls' : 'called by'} ${systemName(l.otherRepo)}: ${clip(l.key)}  ${l.calls ? 'served in' : 'from'} ${l.otherRepo}:${l.otherPath}:${l.otherLine}`)
  return rows
    .map((r, i) => {
      const where = r.start ? `  lines ${r.start}-${r.end}${r.symbol ? `  in ${clip(r.symbol)}` : ''}` : ''
      const head = [`${r.repo}@${short(r.sha)}:${r.path}  [${r.kind}]${where}`, ...linkLines(r)].join('\n')
      if (i < SHOWN && r.start && r.end) {
        const lines = r.content.split('\n')
        const end = Math.min(r.end, lines.length)
        // A long section shows the 40 lines around its first good match.
        const first = bestLines(r.content, words, 50).find((h) => h.line >= r.start! && h.line <= end)?.line ?? r.start
        const from = end - r.start + 1 <= SHOWN_LINES ? r.start : Math.min(Math.max(r.start, first - 8), end - SHOWN_LINES + 1)
        const to = Math.min(end, from + SHOWN_LINES - 1)
        const code = lines.slice(from - 1, to).map((t, j) => `    ${from + j}\t${clip(t)}`)
        return `${head}  showing ${from}-${to}\n${code.join('\n')}`
      }
      let hits = bestLines(r.content, words, 3)
      // The section that matched, rather than the file's first mention: keep the lines inside it.
      if (r.start && r.end) {
        const inside = bestLines(r.content, words, 50).filter((h) => h.line >= r.start! && h.line <= r.end!)
        hits = inside.length ? inside.slice(0, 3) : r.content.split('\n').slice(r.start - 1, r.start + 2).map((text, i) => ({ line: r.start! + i, text: clip(text.trim()) }))
      }
      return `${head}\n${fmtHits(hits)}`
    })
    .join('\n')
}

// Exact text, case-insensitive. The trigram index makes this fast even for a rare identifier.
export async function grep(db: Db, a: { text: string; repo?: string; path_prefix?: string; kind?: string }): Promise<string> {
  const text = a.text ?? ''
  if (text.length < 3) return 'Give at least three characters to look for.' // a trigram index can't serve less
  if (text.length > 120) return 'Search text is limited to 120 characters.'
  if (a.kind && !KINDS.includes(a.kind)) return `kind must be one of ${KINDS.join(', ')}.`
  const like = `%${text.replace(/[\\%_]/g, '\\$&')}%`
  const rows = await q<{ repo: string; sha: string | null; path: string; kind: string; content: string }>(
    db,
    `select r.name as repo, r.last_sha as sha, f.path, f.kind, f.content
       from kb_file f join kb_repo r on r.id = f.repo_id
      where f.content ilike $1
        and ($2::text is null or r.name = $2)
        and ($3::text is null or f.path like $3 || '%')
        and ($4::text is null or f.kind = $4)
      order by (f.kind in ('code', 'setting')) desc, f.path
      limit 15`,
    [like, a.repo ?? null, a.path_prefix ?? null, a.kind ?? null],
  )
  if (!rows.length) return `"${text}" does not appear in the indexed files.`
  const needle = text.toLowerCase()
  const out = rows.map((r) => {
    const hits = bestLines(r.content, [needle], 5)
    return `${r.repo}@${short(r.sha)}:${r.path}  [${r.kind}]\n${fmtHits(hits)}`
  })
  return out.join('\n') + (rows.length === 15 ? '\n(15 files shown; narrow with repo or path_prefix for more.)' : '')
}

export async function readFile(db: Db, a: { repo: string; path: string; from?: number; to?: number }): Promise<string> {
  const rows = await q<{ sha: string | null; content: string }>(
    db,
    `select r.last_sha as sha, f.content from kb_file f join kb_repo r on r.id = f.repo_id where r.name = $1 and f.path = $2`,
    [a.repo, a.path],
  )
  if (!rows.length) return `No indexed file ${a.repo}:${a.path}. Use search, grep or list_dir to find the exact path (it may have been excluded: secrets, binaries and customer config are not indexed).`
  const lines = rows[0].content.split('\n')
  const from = Math.max(1, Math.floor(a.from ?? 1))
  const to = Math.min(lines.length, Math.floor(a.to ?? from + MAX_LINES_PER_READ - 1), from + MAX_LINES_PER_READ - 1)
  if (from > lines.length) return `${a.path} has ${lines.length} lines.`
  let body = ''
  let last = from - 1
  for (let i = from; i <= to; i++) {
    const row = `${i}\t${lines[i - 1]}\n`
    if (body.length + row.length > MAX_READ_BYTES) break // minified or wide files: cap by bytes too
    body += row
    last = i
  }
  const more = last < lines.length ? `\n(lines ${last + 1}-${lines.length} not shown; call again with from=${last + 1})` : ''
  return `${a.repo}@${short(rows[0].sha)}:${a.path}  lines ${from}-${last} of ${lines.length}\n${body}${more}`
}

export async function listDir(db: Db, a: { repo: string; path?: string }): Promise<string> {
  const prefix = (a.path ?? '').replace(/^\/+|\/+$/g, '')
  const base = prefix ? `${prefix}/` : ''
  const rows = await q<{ path: string; kind: string }>(
    db,
    `select f.path, f.kind from kb_file f join kb_repo r on r.id = f.repo_id
      where r.name = $1 and f.path like $2 || '%' order by f.path limit 5000`,
    [a.repo, base.replace(/[\\%_]/g, '\\$&')],
  )
  if (!rows.length) return `Nothing indexed under ${a.repo}:${base || '/'}. Call repo_map for the repo names.`
  const dirs = new Map<string, number>()
  const files: string[] = []
  for (const r of rows) {
    const rest = r.path.slice(base.length)
    const slash = rest.indexOf('/')
    if (slash < 0) files.push(`${rest}  [${r.kind}]`)
    else dirs.set(rest.slice(0, slash), (dirs.get(rest.slice(0, slash)) ?? 0) + 1)
  }
  const d = [...dirs].map(([name, n]) => `${name}/  (${n} files)`)
  return [`${a.repo}:${base || '/'}`, ...d, ...files.slice(0, 200)].join('\n') + (files.length > 200 ? `\n(${files.length - 200} more files)` : '')
}

// Where each repo's knowledge was read, for the answer's footer.
export async function sources(db: Db) {
  const rows = await q<{ name: string; branch: string; last_sha: string | null; indexed_at: Date | null }>(
    db,
    'select name, branch, last_sha, indexed_at from kb_repo order by name',
    [],
  )
  return rows.map((r) => ({ repo: r.name, branch: r.branch, sha: r.last_sha, indexedAt: r.indexed_at?.toISOString() ?? null }))
}

// The lines around `line` (or the top of the file) with their numbers, for showing a citation's source.
export async function fileExcerpt(db: Db, repo: string, path: string, line: number | null, radius = 25) {
  const rows = await q<{ sha: string | null; kind: string; content: string }>(
    db,
    `select r.last_sha as sha, f.kind, f.content from kb_file f join kb_repo r on r.id = f.repo_id where r.name = $1 and f.path = $2`,
    [repo, path],
  )
  if (!rows.length) return null
  const all = rows[0].content.split('\n')
  const centre = line && line >= 1 && line <= all.length ? line : 1
  const from = Math.max(1, centre - radius)
  const to = Math.min(all.length, centre + radius * (line ? 1 : 2))
  return {
    repo,
    path,
    sha: rows[0].sha,
    kind: rows[0].kind,
    total: all.length,
    from,
    to,
    focus: line && line === centre ? line : null,
    lines: all.slice(from - 1, to).map((text, i) => ({ n: from + i, text: text.length > 400 ? `${text.slice(0, 400)}…` : text })),
  }
}
```

## 9. Tests for the pure parts

Run the `systemsIn` case after filling E7; as written it assumes these example entries in `systems.ts`
(`[/\boms\b|order management/, ['orders-api']]`, `[/\bdispatch\b/, ['dispatch', 'dispatch-worker']]`).

```ts
// file: kb.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bestLines, FUSION, fuse, liftConnectors, systemsIn, terms, type Lists } from './kb.ts'

test('search words and best lines', () => {
  assert.deepEqual(terms('Can the worker retry a failed_job order, with a delay?'), ['can', 'the', 'worker', 'retry', 'failed_job', 'order', 'with', 'delay'])
  const hits = bestLines('one\nlow battery here\nbattery only\nnothing', ['low', 'battery'], 2)
  assert.deepEqual(hits.map((h) => h.line), [2, 3])
})

test('the systems a question names become their repos', () => {
  assert.deepEqual(systemsIn('How does OMS send an order to dispatch?'), ['orders-api', 'dispatch', 'dispatch-worker'])
  assert.deepEqual(systemsIn('How does order management pick a station?'), ['orders-api'])
  assert.deepEqual(systemsIn('atoms and dispatcher'), [], 'only whole words')
})

test('merging: per file, a top hit in one list beats files middling in both, and named systems are lifted', () => {
  const c = (path: string, repo = 'a-repo', n = 0, kind = 'code') => ({ repo_id: repo === 'a-repo' ? 1 : 2, repo, path, n, kind })
  const middling = ['m1', 'm2', 'm3', 'm4', 'm5', 'm6']
  const l: Lists = {
    byWords: [c('top.py'), ...Array.from({ length: 20 }, (_, i) => c(`w${i}.py`)), ...middling.map((p) => c(p))],
    byMeaning: [...Array.from({ length: 20 }, (_, i) => c(`v${i}.py`)), ...middling.map((p) => c(p)), c('top.py', 'a-repo', 3)],
    systems: [],
  }
  const order = fuse(l, 12).map((x) => x.path)
  assert.equal(order[0], 'top.py', 'first in words and last in meaning is still first')
  assert.equal(fuse(l, 12)[0].n, 0, 'a file keeps the section that placed it highest')
  assert.ok(order.indexOf('v0.py') < order.indexOf('m1'), 'a first place in one list beats a 22nd place in both')

  const lifted = fuse({ byWords: [c('a.py'), c('b.ts', 'b-repo')], byMeaning: [], systems: ['b-repo'] }, 2).map((x) => x.path)
  assert.deepEqual(lifted, ['b.ts', 'a.py'])
  assert.equal(FUSION.k, 10)
})

test('a question naming two systems: their connecting files go in after the first five, best placed first', () => {
  const f = (path: string) => ({ repo: 'r', path })
  const top = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map(f)
  const deep = [...top, f('x'), f('y'), f('z'), f('w')]
  const out = liftConnectors(top, deep, new Set(['r:y', 'r:b', 'r:w', 'r:x', 'r:z']), 9).map((c) => c.path)
  assert.deepEqual(out, ['a', 'b', 'c', 'd', 'e', 'x', 'y', 'z', 'f'], 'b is already in the first five; three at most')
  assert.deepEqual(liftConnectors(top, deep, new Set(), 3).map((c) => c.path), ['a', 'b', 'c'])
})
```

## 10. Measured, and what did not help

Measured on the source project's golden questions (16 Nov 2026, six repos, searched as keywords). About a dozen
questions: the direction is evidence, the percentages are not a benchmark.

| Search | Expected file in top 5 | In top 12 |
|---|---|---|
| Whole files, words | 0% | 8% |
| Sections, words + meaning, RRF k=60 | 25% | 33% |
| + IDF weights, k=10, named-system boost x1.5 | 42% | 42% |
| + connector lift | 42% | 58% |

Recorded as NOT helping (keep the `--grid` variants so the next person does not retry them blind, P40):
down-weighting tests (x0.5) or docs (x0.7); a bonus for a query word in the path or symbol (`head`); weighting one
list over the other (x1.3 either way). A code-graph experiment (symbols and call edges per repo) reached the missed
files by following call edges from the top results, but among hundreds of neighbours, and lifting them made the
top 5 worse; the cross-system contracts are what helped, and they need no graph database.

Remaining misses in the source: a callback whose URL comes from configuration (no contract found), and files found
only far down the word list. One search (words + meaning + fusion) takes ~150 ms; the query embedding ~15-20 ms on
CPU.

## Pitfalls

- **P27. Set `hnsw.ef_search` to at least the LIMIT, inside the transaction (`set local`).** pgvector returns at
  most `ef_search` rows (default 40): a LIMIT 60 or 200 silently comes back short. (`rag-layer-audit` Q3.)
- **P28. Fuse per FILE: each file's best rank in each list, and keep the section that placed it highest.**
  Otherwise one long file fills the top with its own sections.
- **P29. RRF with k=10, not the usual 60.** With 60, a file near the top of one list is beaten by files middling
  in both; measured 25% -> 42% found@5 together with IDF and the system lift.
- **P30. Weight each query word by inverse document frequency over sections; cache the counts 5 minutes.** Domain
  nouns present in thousands of sections drown rare, decisive words ("409", "callback").
- **P31. Build `to_tsquery` input only from `[a-z0-9]{3,}` tokens (or lexemes returned by `plainto_tsquery`).** Raw
  user text is a tsquery syntax error waiting to happen; skip lexemes that are empty (stop words) or contain a space.
- **P32. Search the question as keywords, not as written.** Stop words pull the meaning search; measured better on
  the golden set.
- **P33. Expand short system aliases before searching and boost the named systems' own repos (x1.5).** Two- or
  three-letter names are below the token minimum and match everything; a question about system X is answered by
  X's code, not code that mentions X. Whole words only ("smart" must not match "sm").
- **P34. Run every lookup in `begin read only` with a short `statement_timeout` (5 s tools, 8 s hybrid).** A slow
  search must not hold a pool connection, and the lookup path cannot write.
- **P35. Circuit-break the query embedder for 10 minutes after a failure and fall back to words.** Otherwise every
  search pays the failed load.
- **P36. Fall back to whole-file search until sections exist; cache that existence check.** A database the new
  indexer has not run on yet must still answer.
- **P37. Show code for the first three results only (up to 40 numbered lines around the first matching line); give
  the rest three best lines.** The model can cite the first results without a read (one round fewer); showing all
  twelve bloats every turn.
- **P38. `grep`: require 3-120 characters, escape `\ % _`, use `ilike` over the trigram index, cap at 15 files and
  say so.** Trigram indexes cannot serve patterns under three characters.
- **P39. `read_file`: cap by lines (400) AND bytes (40,000) and tell the model the next `from=`.** Minified or wide
  files blow the context otherwise.
- **P40. Recorded negative results: down-weighting tests or docs, a path/name word bonus, and weighting one list
  over the other did not help; following call-graph edges from top results made top-5 worse.** Keep the grid so
  the next person does not retry them blind.
