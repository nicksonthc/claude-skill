# Evals: golden questions, search eval, answer eval, review queue

Load this when measuring the knowledge base: the golden-question file, the free checks that run after every
refresh, the free search eval with its fusion grid, the paid answer eval, the review queue that turns real
questions into golden ones, and the second-opinion judge. Golden questions TEST; they never feed answers.

## 1. The golden file (E15)

`eval/golden.json`, versioned with the code. Seed it with 8-12 questions whose answers you have verified in the
code, at least one the code cannot answer, then grow it from real questions (section 5).

```json
{
  "note": "expect: path fragments the answer must cite or have read (matched on a folder boundary). mention: regular expressions (case-insensitive) the answer must match. notFound: the base holds nothing on this, so the answer must say so instead of inventing. pending (a reason): skipped, reported but not counted, until the reason is resolved.",
  "questions": [
    {
      "id": "retry-limit",
      "question": "How many times does the dispatcher retry a job before giving up?",
      "expect": ["dispatch/retry_policy.py"],
      "mention": ["\\b5\\b|five"]
    },
    {
      "id": "order-confirmed-across-systems",
      "question": "How does the dispatcher tell the order service that a job is finished?",
      "expect": ["orders_client.py", "order.controller.ts"],
      "mention": ["confirm"]
    },
    {
      "id": "callback-from-config",
      "question": "Where does the billing service send its payment events?",
      "expect": ["CallbackService.cs"],
      "pending": "the callback URL comes from configuration; no contract links it yet"
    },
    {
      "id": "not-in-the-code",
      "question": "Can customers pay with a gift card through the software?",
      "notFound": true
    }
  ]
}
```

Shared helpers. **The folder-boundary match is a correction**: in the source only the search eval used it, while
the answer eval and `--check` used a plain suffix (`find-destination.ts` also matched `replay-find-destination.ts`).
Use one matcher everywhere (not yet proven in production in the two places that change).

```ts
// file: golden.ts
import { readFileSync } from 'node:fs'
import type pg from 'pg'

export type Golden = { id: string; question: string; expect?: string[]; mention?: string[]; notFound?: boolean; pending?: string; note?: string }
export const GOLDEN_FILE = new URL('../eval/golden.json', import.meta.url)
export const loadGolden = () => JSON.parse(readFileSync(GOLDEN_FILE, 'utf8')) as { note?: string; questions: Golden[] }

// An expected file is a path fragment that ends on a folder boundary: "find-destination.ts" is not
// "replay-find-destination.ts".
export const matches = (path: string, fragment: string) => path === fragment || path.endsWith(`/${fragment}`)
/** "repo:path" -> "path" (repo names may contain '/', never ':'). */
export const pathOf = (repoPath: string) => repoPath.slice(repoPath.indexOf(':') + 1)

/** How many indexed files an expected fragment matches, with the same boundary rule. */
export async function present(db: pg.Pool, fragment: string): Promise<number> {
  const r = await db.query<{ n: number }>(`select count(*)::int as n from kb_file where path = $1 or path like $2`, [fragment, `%/${fragment.replace(/[\\%_]/g, '\\$&')}`])
  return r.rows[0].n
}
```

## 2. The free check (`eval --check`)

Every file a golden question expects is still indexed. Exit 1 on a miss. It runs in the refresh's links job, so a
moved or deleted file shows up as a red step, not later as a wrong answer (P76). It is the `--check` branch of
`ask-eval.ts` (section 4).

## 3. Search eval (free)

Measures retrieval without asking the model: for each golden question, where the expected files land in the top 12,
per mode. `--lists` shows each expected file's place in each list BEFORE fusion (which list lost it); `--grid`
tries fusion variants. Every ranking change is a row in this table, including the ones that did not help.

```ts
// file: search-eval.ts
import pg from 'pg'
import { databaseConfig } from './config.ts'
import { expandSystems, FUSION, fuse, keywords, rankFiles, rankHybrid, searchLists, type Fusion, type Lists } from './kb.ts'
import { embed } from './kb-embed.ts'
import { loadGolden, matches, present } from './golden.ts'

// How well search finds the right code, without asking the model anything (free): for each golden question the
// question is searched as typed and as keywords, and we see where the files it should find come.
//
//   npm run eval:search              the search as it ships, and the old whole-file search
//   npm run eval:search -- --lists   also each expected file's place in the two lists before merging
//   npm run eval:search -- --grid    also other ways of merging the lists (to tune FUSION in kb.ts)
//
// "found@5" and "found@12": share of expected files in the top 5 / top 12 results (the model sees 12 per search).
// "first": the average rank of the first expected file found (lower is better; a miss counts as 13).

const questions = loadGolden().questions.filter((q) => !q.pending && !q.notFound && q.expect?.length)
const showLists = process.argv.includes('--lists')
const grid = process.argv.includes('--grid')

const db = new pg.Pool({ ...databaseConfig(), max: 2 })
const vectors = (await db.query<{ ok: boolean }>(`select exists (select 1 from kb_chunk where embedding is not null) as ok`).catch(() => ({ rows: [{ ok: false }] }))).rows[0].ok
const chunks = (await db.query<{ ok: boolean }>(`select exists (select 1 from kb_chunk) as ok`).catch(() => ({ rows: [{ ok: false }] }))).rows[0].ok
if (!chunks) {
  console.log('No sections yet: run the indexer first.')
  process.exit(0)
}

// The two lists for each search, fetched once (deep, so the --lists view sees past the 60 the search keeps).
const POOL = 60
const DEEP = 200
const cache = new Map<string, Lists>()
async function lists(q: string, depth: number): Promise<Lists> {
  const key = `${depth}\n${q}`
  if (!cache.has(key)) {
    const client = await db.connect()
    try {
      await client.query('begin read only')
      const vector = vectors ? (await embed([expandSystems(q)]))[0] : null
      cache.set(key, await searchLists(client, { query: q, vector }, depth))
      await client.query('commit')
    } finally {
      client.release()
    }
  }
  return cache.get(key)!
}

type Mode = { name: string; run: (q: string) => Promise<string[]> }
const hybrid = (name: string, f: Fusion): Mode[] => [
  { name: `${name}, as asked`, run: async (q) => fuse(await lists(q, POOL), 12, f).map((c) => c.path) },
  { name: `${name}, keywords`, run: async (q) => fuse(await lists(keywords(q), POOL), 12, f).map((c) => c.path) },
]
// As it ships: the merged lists, then the files connecting the systems a question names (contracts).
const vectorOf = new Map<string, number[] | null>()
const shipped = async (q: string) => {
  if (!vectorOf.has(q)) vectorOf.set(q, vectors ? (await embed([expandSystems(q)]))[0] : null)
  return (await rankHybrid(db, { query: q, limit: 12, vector: vectorOf.get(q) })).map((r) => r.path)
}
const modes: Mode[] = [
  { name: 'old: whole files, words, keywords', run: async (q) => (await rankFiles(db, { query: keywords(q), limit: 12 })).map((r) => r.path) },
  ...hybrid('without links between systems', FUSION),
  { name: 'now, as asked', run: shipped },
  { name: 'now, keywords', run: (q) => shipped(keywords(q)) },
]
if (grid) {
  // Keep the variants that did not help: the next person should not retry them blind.
  const variants: [string, Partial<Fusion>][] = [
    ['usual rrf (k 60, no lift)', { k: 60, system: 1 }],
    ['k 60', { k: 60 }],
    ['no system lift', { system: 1 }],
    ['system x2', { system: 2 }],
    ['tests x0.5', { test: 0.5 }],
    ['docs x0.7', { doc: 0.7 }],
    ['name/path word x2', { head: 1 }],
    ['meaning x1.3', { meaning: 1.3 }],
    ['words x1.3', { words: 1.3 }],
  ]
  for (const [name, v] of variants) modes.push(...hybrid(name, { ...FUSION, ...v }))
}

const totals = modes.map(() => ({ at5: 0, at12: 0, first: 0 }))
let expected = 0
let counted = 0
const rows: string[] = []
const listRows: string[] = []
const placeIn = (list: Lists['byWords'], f: string) => {
  const files: string[] = []
  for (const c of list) if (!files.includes(c.path)) files.push(c.path)
  const i = files.findIndex((p) => matches(p, f))
  return i < 0 ? '-' : String(i + 1)
}
for (const q of questions) {
  const want = []
  for (const f of q.expect!) if ((await present(db, f)) > 0) want.push(f)
  if (!want.length) {
    rows.push(`  skip  ${q.id}: its files aren't in this database`)
    continue
  }
  counted++
  expected += want.length
  const cells: string[] = []
  for (const [i, m] of modes.entries()) {
    const paths = await m.run(q.question)
    const ranks = want.map((f) => paths.findIndex((p) => matches(p, f)) + 1 || 13)
    totals[i].at5 += ranks.filter((r) => r <= 5).length
    totals[i].at12 += ranks.filter((r) => r <= 12).length
    totals[i].first += Math.min(...ranks)
    cells.push(ranks.map((r) => (r > 12 ? '-' : String(r))).join(','))
  }
  rows.push(`  ${q.id.padEnd(34)} ${cells.map((c) => c.padEnd(7)).join(' ')}`)
  if (showLists)
    for (const f of want) {
      const asked = await lists(q.question, DEEP)
      const kw = await lists(keywords(q.question), DEEP)
      listRows.push(`  ${`${q.id} ${f}`.padEnd(58)} words ${placeIn(asked.byWords, f).padStart(3)} / ${placeIn(kw.byWords, f).padStart(3)}   meaning ${placeIn(asked.byMeaning, f).padStart(3)} / ${placeIn(kw.byMeaning, f).padStart(3)}`)
    }
}
const pct = (n: number) => `${Math.round((100 * n) / Math.max(1, expected))}%`.padStart(4)
console.log(`${counted} questions, ${expected} expected files. Rank of each expected file per mode ("-" = not in the top 12):`)
console.log(`  ${''.padEnd(34)} ${modes.map((_, i) => `(${i + 1})`.padEnd(7)).join(' ')}`)
for (const r of rows) console.log(r)
console.log('')
for (const [i, m] of modes.entries()) {
  const t = totals[i]
  console.log(`(${i + 1}) ${m.name.padEnd(44)} found@5 ${pct(t.at5)}  found@12 ${pct(t.at12)}  first ${(t.first / Math.max(1, counted)).toFixed(1)}`)
}
if (showLists) {
  console.log(`\nEach expected file's place among files in each list, before merging (as asked / keywords; "-" = not in the top ${DEEP} sections):`)
  for (const r of listRows) console.log(r)
}
if (!vectors) console.log('\nSections have no embeddings yet: meaning search is not compared.')
await db.end()
```

## 4. Answer eval (paid) and the free check

```ts
// file: ask-eval.ts
import Anthropic from '@anthropic-ai/sdk'
import { answer, citationsOf } from './ask.ts'
import { askConfig } from './ask-config.ts'
import { createPool } from './db.ts'
import { loadGolden, matches, pathOf, present } from './golden.ts'

// Ask the golden questions and report which ones the knowledge base answers. Two modes:
//
//   npm run eval -- --check   free: every file a question expects is still in the base. Run after each refresh, so a
//                             moved or deleted file shows up here and not as a wrong answer.
//   npm run eval              asks each question (the Anthropic API: about a dollar or two for a dozen questions).
//                             Pass --only <id>[,<id>] for some. Exits 1 when fewer than EVAL_PASS_RATE (default 0.8)
//                             pass.
//
// A question PASSes when its answer cites or read every expected file and matches every `mention`. It is a MISS when
// the file was read but not cited, and a FAIL otherwise. A MISS is usually a wording problem; a FAIL a retrieval one.

const args = process.argv.slice(2)
const check = args.includes('--check')
const only = args.find((a, i) => args[i - 1] === '--only')?.split(',')
const all = loadGolden().questions.filter((q) => !only || only.includes(q.id))
const questions = all.filter((q) => !q.pending)
for (const q of all.filter((q) => q.pending)) console.log(`PENDING  ${q.id}: ${q.pending}`)
const db = createPool()

try {
  if (check) {
    let bad = 0
    for (const q of questions) {
      for (const fragment of q.expect ?? []) {
        const n = await present(db, fragment)
        if (n === 0) {
          bad++
          console.log(`MISSING  ${q.id}: no indexed file ends with ${fragment}`)
        } else if (n > 1) console.log(`note     ${q.id}: ${fragment} matches ${n} files`)
      }
    }
    console.log(bad ? `${bad} expected file(s) are not in the knowledge base.` : `All expected files are in the knowledge base (${questions.length} questions).`)
    process.exitCode = bad ? 1 : 0
  } else {
    const cfg = askConfig()
    if (!cfg.anthropicKey) throw new Error('ANTHROPIC_API_KEY is not set. Use --check for the free check.')
    const client = new Anthropic({ apiKey: cfg.anthropicKey, maxRetries: 2, timeout: 5 * 60_000 })
    let pass = 0
    let tokens = 0
    for (const q of questions) {
      const t0 = Date.now()
      let verdict = 'FAIL'
      let why = ''
      try {
        const r = await answer(client, db, cfg, q.question, [])
        tokens += r.inputTokens + r.outputTokens
        const cited = citationsOf(r.answer).map((c) => c.path)
        const seen = [...cited, ...r.reads.map(pathOf)]
        const missing = (q.expect ?? []).filter((f) => !seen.some((p) => matches(p, f)))
        const uncited = (q.expect ?? []).filter((f) => !cited.some((p) => matches(p, f)))
        const unmatched = (q.mention ?? []).filter((m) => !new RegExp(m, 'i').test(r.answer))
        // An unanswerable question: the answer must say so, and cite nothing.
        const notFound = q.notFound ? /could not find|couldn't find|not find|not in the indexed|no evidence/i.test(r.answer) && cited.length === 0 : true
        if (!missing.length && !unmatched.length && notFound) {
          verdict = uncited.length ? 'MISS' : 'PASS'
          if (verdict === 'MISS') why = `read but did not cite: ${uncited.join(', ')}`
        }
        if (verdict === 'FAIL') why = [missing.length && `never reached ${missing.join(', ')}`, unmatched.length && `answer lacks /${unmatched.join('/, /')}/`, !notFound && 'should have said it is not in the code'].filter(Boolean).join('; ')
        if (verdict === 'PASS') pass++
        console.log(`${verdict.padEnd(5)} ${q.id}  (${r.toolCalls} lookups, ${Math.round((Date.now() - t0) / 1000)} s)${why ? `\n        ${why}` : ''}`)
      } catch (e) {
        console.log(`ERROR ${q.id}: ${(e as Error).message}`)
      }
    }
    const rate = questions.length ? pass / questions.length : 1
    console.log(`\n${pass}/${questions.length} passed (${Math.round(rate * 100)}%), ${tokens.toLocaleString('en-US')} tokens`)
    process.exitCode = rate >= Number(process.env.EVAL_PASS_RATE ?? 0.8) ? 0 : 1
  }
} finally {
  await db.end()
}
```

## 5. Review queue: real questions become golden ones

Every stored question waits for an owner, failed and thumbs-down first. The owner ticks the files a right answer
uses (the cited ones pre-ticked, the opened ones offered unticked, a file picker for the ones the model never
found: those failures are the ones worth keeping), optionally adds phrases or marks "not in the code", records a
cause, and approves or skips. The UI is not covered; the routes are an interface any front end can call.

| Route (admin scope) | Does |
|---|---|
| `GET /admin/ask/review` | Up to 60 waiting items in review order, counts (waiting, golden), causes in the last 30 days |
| `POST /admin/ask/review/:messageId` | `{action: 'approve', golden, cause?}` or `{action: 'skip', cause?}`; 409 if someone was first |
| `POST /admin/ask/review/:messageId/check` | Queue a second opinion (202) |
| `GET/POST /admin/ask/golden`, `PATCH /admin/ask/golden/:id` | List, write by hand, retire or restore |
| `GET /admin/ask/golden.json` | Approved questions in the eval file's format: questions and paths only |
| `GET /admin/ask/files?q=` | File picker: by name or path first, then by topic through `kb.rank` |

```ts
// file: ask-review.ts
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify'
import Anthropic from '@anthropic-ai/sdk'
import { z } from 'zod'
import * as kb from './kb.ts'
import { splitConfidence } from './answer-text.ts'
import type { AnswerDetail, AskCitation } from './ask.ts'
import { CheckQueue, secondOpinion, settled, type ContextFor, type SecondOpinion } from './ask-check.ts'
import type { AskConfig } from './ask-config.ts'

/** Why an answer went wrong (or didn't), as an owner reads it: each points at a different fix. */
export const REVIEW_CAUSES = ['search_missed', 'cannot_read', 'wrong_answer', 'not_in_code', 'fine'] as const
export type ReviewCause = (typeof REVIEW_CAUSES)[number]

const isPattern = (p: string) => {
  try {
    new RegExp(p, 'i')
    return true
  } catch {
    return false
  }
}
export const GoldenBody = z
  .object({
    question: z.string().trim().min(3).max(2000),
    expect: z.array(z.string().trim().regex(/^[^:\s]+:\S+$/, 'A file is repo:path.')).max(10).default([]),
    mention: z.array(z.string().trim().min(1).max(200).refine(isPattern, 'Not a valid pattern.')).max(10).default([]),
    notFound: z.boolean().default(false),
    note: z.string().trim().max(500).optional(),
  })
  .refine((b) => b.notFound || b.expect.length > 0, 'Tick at least one file a right answer uses, or mark it as not in the code.')
export type GoldenBody = z.infer<typeof GoldenBody>
export const ReviewBody = z.discriminatedUnion('action', [
  z.object({ action: z.literal('approve'), golden: GoldenBody, cause: z.enum(REVIEW_CAUSES).optional() }),
  z.object({ action: z.literal('skip'), cause: z.enum(REVIEW_CAUSES).optional() }),
])

export type ReviewItem = {
  messageId: number
  askedAt: string
  question: string
  answer: string | null
  error: string | null // it failed: no answer
  secondOpinion: SecondOpinion | null
  feedback: 1 | -1 | null
  confidence: 'high' | 'medium' | 'low' | null
  cited: string[] // repo:path
  read: string[] // repo:path
  durationMs: number | null
  detail: AnswerDetail
}
export type GoldenQuestion = { id: number; question: string; expect: string[]; mention: string[]; notFound: boolean; status: 'approved' | 'retired'; messageId: number | null; note: string | null; reviewedBy: string | null; reviewedAt: string }

type MessageRow = { id: string; created_at: Date; question: string; answer: string | null; error: string | null; second_opinion: SecondOpinion | null; feedback: 1 | -1 | null; citations: AskCitation[]; reads: string[]; duration_ms: number | null; detail: AnswerDetail }
type GoldenRow = { id: string; question: string; expect: string[]; mention: string[]; not_found: boolean; status: 'approved' | 'retired'; message_id: string | null; note: string | null; reviewed_by: string | null; reviewed_at: Date }

// Waiting for review: answered, or failed for a reason other than the asker leaving.
const WAITING = `review is null and (answer is not null or (error is not null and error <> 'cancelled by the asker'))`

const files = (c: AskCitation[]) => [...new Set(c.map((x) => `${x.repo}:${x.path}`))]

/** The order a reviewer sees: failed and unhelpful first, then the least sure, then the rest, newest first within each. */
export function reviewOrder(items: ReviewItem[]): ReviewItem[] {
  const weight = (i: ReviewItem) => (i.error || i.feedback === -1 ? 0 : i.confidence === 'low' ? 1 : i.confidence === 'medium' ? 2 : i.feedback === 1 ? 4 : 3)
  return [...items].sort((a, b) => weight(a) - weight(b) || b.askedAt.localeCompare(a.askedAt))
}

export function toReviewItem(m: MessageRow): ReviewItem {
  return {
    messageId: Number(m.id),
    askedAt: m.created_at.toISOString(),
    question: m.question,
    answer: m.answer,
    error: m.answer ? null : m.error,
    secondOpinion: settled(m.second_opinion),
    feedback: m.feedback,
    confidence: m.answer ? (splitConfidence(m.answer).confidence?.level ?? null) : null,
    cited: files(m.citations),
    read: m.reads,
    durationMs: m.duration_ms,
    detail: m.detail,
  }
}

const toGolden = (g: GoldenRow): GoldenQuestion => ({
  id: Number(g.id),
  question: g.question,
  expect: g.expect,
  mention: g.mention,
  notFound: g.not_found,
  status: g.status,
  messageId: g.message_id ? Number(g.message_id) : null,
  note: g.note,
  reviewedBy: g.reviewed_by,
  reviewedAt: g.reviewed_at.toISOString(),
})

/** A golden question as eval/golden.json holds it: files by path (the repo prefix dropped), no reviewer names. */
export const forEval = (g: GoldenQuestion) => ({
  id: `review-${g.id}`,
  question: g.question,
  ...(g.notFound ? { notFound: true } : { expect: g.expect.map((f) => f.slice(f.indexOf(':') + 1)) }),
  ...(g.mention.length ? { mention: g.mention } : {}),
  ...(g.note ? { note: g.note } : {}),
})

type pgLike = Pick<kb.Db, 'query'> // the pool, or a client inside a transaction

// E12: `scope` is an admin-only Fastify scope; `who` names the reviewer for kb_golden.reviewed_by.
// E11 (optional): contextFor rebuilds a stored question's runtime-settings block for its second opinion.
export function registerAskReview(scope: FastifyInstance, db: kb.Db, cfg: AskConfig, who: (req: FastifyRequest) => string, contextFor?: ContextFor) {
  const fail = (reply: FastifyReply, status: number, code: string, message: string) => reply.code(status).send({ error: { code, message } })
  // Second opinions run here, in the background (ask-check.ts); they need the AI key.
  const client = cfg.anthropicKey ? new Anthropic({ apiKey: cfg.anthropicKey, maxRetries: 2, timeout: 10 * 60_000 }) : null
  const checks = new CheckQueue(
    (id) => secondOpinion(client!, db, cfg, id, { contextFor }),
    (id) => db.query('update kb_message set second_opinion = $2 where id = $1', [id, JSON.stringify({ status: 'queued', startedAt: new Date().toISOString() } satisfies SecondOpinion)]),
  )
  const insertGolden = (q: pgLike, g: GoldenBody, messageId: number | null, by: string) =>
    q.query<GoldenRow>(
      `insert into kb_golden (question, expect, mention, not_found, message_id, note, reviewed_by)
       values ($1, $2, $3, $4, $5, $6, $7) returning *`,
      [g.question, g.notFound ? [] : g.expect, g.mention, g.notFound, messageId, g.note || null, by],
    )

  // The queue: questions nobody has reviewed yet.
  scope.get('/api/v1/admin/ask/review', async () => {
    const r = await db.query<MessageRow>(
      `select id, created_at, question, answer, error, second_opinion, feedback, citations, reads, duration_ms, detail
         from kb_message where ${WAITING} order by created_at desc limit 300`,
    )
    const counts = await db.query<{ waiting: number; golden: number }>(
      `select (select count(*) from kb_message where ${WAITING})::int as waiting,
              (select count(*) from kb_golden where status = 'approved')::int as golden`,
    )
    // why answers went wrong in the last 30 days, as owners recorded it: the commonest cause is the next fix
    const causes = await db.query<{ cause: ReviewCause; n: number }>(
      `select review_cause as cause, count(*)::int as n from kb_message
        where review_cause is not null and created_at > now() - interval '30 days' group by 1`,
    )
    return {
      items: reviewOrder(r.rows.map(toReviewItem)).slice(0, 60),
      ...counts.rows[0],
      causes: Object.fromEntries(causes.rows.map((c) => [c.cause, c.n])),
      canCheck: !!client,
    }
  })

  // Approve or skip, atomically: two owners reviewing at once can't both win.
  scope.post('/api/v1/admin/ask/review/:messageId', async (req, reply) => {
    const id = Number((req.params as { messageId: string }).messageId)
    const body = ReviewBody.safeParse(req.body)
    if (!Number.isSafeInteger(id)) return fail(reply, 404, 'not_found', 'No such question.')
    if (!body.success) return fail(reply, 422, 'invalid_payload', body.error.issues.map((i) => i.message).join('; '))
    const client = await db.connect()
    try {
      await client.query('begin')
      const m = await client.query('update kb_message set review = $2, review_cause = $3 where id = $1 and review is null returning id', [
        id,
        body.data.action === 'approve' ? 'golden' : 'skipped',
        body.data.cause ?? null,
      ])
      if (!m.rowCount) {
        await client.query('rollback')
        return fail(reply, 409, 'already_reviewed', 'Someone has reviewed this question already. Reload the list.')
      }
      let golden: GoldenQuestion | null = null
      if (body.data.action === 'approve') golden = toGolden((await insertGolden(client, body.data.golden, id, who(req))).rows[0])
      await client.query('commit')
      return { golden }
    } catch (e) {
      await client.query('rollback').catch(() => {})
      throw e
    } finally {
      client.release()
    }
  })

  // Ask for a second opinion on a question: runs in the background; the queue shows its status and result.
  scope.post('/api/v1/admin/ask/review/:messageId/check', async (req, reply) => {
    if (!client) return fail(reply, 503, 'ask_not_configured', 'Second opinions need the AI key (ANTHROPIC_API_KEY).')
    const id = Number((req.params as { messageId: string }).messageId)
    const m = await db.query(`select 1 from kb_message where id = $1 and ${WAITING}`, [id])
    if (!m.rowCount) return fail(reply, 404, 'not_found', 'No such question waiting for review.')
    await checks.add(id)
    return reply.code(202).send({ queued: true })
  })

  scope.get('/api/v1/admin/ask/golden', async () => ({ golden: (await db.query<GoldenRow>(`select * from kb_golden order by status, reviewed_at desc`)).rows.map(toGolden) }))

  // A golden question written by hand, not from the queue.
  scope.post('/api/v1/admin/ask/golden', async (req, reply) => {
    const body = GoldenBody.safeParse(req.body)
    if (!body.success) return fail(reply, 422, 'invalid_payload', body.error.issues.map((i) => i.message).join('; '))
    return reply.code(201).send({ golden: toGolden((await insertGolden(db, body.data, null, who(req))).rows[0]) })
  })

  // Retire a question whose code has changed (or bring it back).
  scope.patch('/api/v1/admin/ask/golden/:id', async (req, reply) => {
    const status = (req.body as { status?: unknown } | null)?.status
    if (status !== 'approved' && status !== 'retired') return fail(reply, 422, 'invalid_payload', 'Send {"status": "approved"} or {"status": "retired"}.')
    const r = await db.query<GoldenRow>(`update kb_golden set status = $2, reviewed_by = $3, reviewed_at = now() where id = $1 returning *`, [Number((req.params as { id: string }).id) || 0, status, who(req)])
    if (!r.rowCount) return fail(reply, 404, 'not_found', 'No such golden question.')
    return { golden: toGolden(r.rows[0]) }
  })

  // The approved questions in the evals' format (golden:pull). No names: only questions and files.
  scope.get('/api/v1/admin/ask/golden.json', async () => {
    const r = await db.query<GoldenRow>(`select * from kb_golden where status = 'approved' order by id`)
    return { questions: r.rows.map((g) => forEval(toGolden(g))) }
  })

  // Files to pick as "a right answer uses this": a path or file name first, then search by topic.
  scope.get('/api/v1/admin/ask/files', async (req) => {
    const q = String((req.query as { q?: string }).q ?? '').trim()
    if (q.length < 3) return { files: [] }
    const byName = await db.query<{ f: string }>(
      `select r.name || ':' || f.path as f from kb_file f join kb_repo r on r.id = f.repo_id
        where f.path ilike $1 order by length(f.path) limit 8`,
      [`%${q.replace(/[\\%_]/g, '\\$&')}%`],
    )
    const byTopic = q.includes('/') || /\.\w{1,5}$/.test(q) ? [] : (await kb.rank(db, { query: q, limit: 8 })).map((r) => `${r.repo}:${r.path}`)
    return { files: [...new Set([...byName.rows.map((r) => r.f), ...byTopic])].slice(0, 12) }
  })
}
```

## 6. Second opinion: a deeper re-run and a judge

The same question is investigated again, more deeply (Technical style, more lookups, more effort, the same history
and runtime context), and a judge compares the facts of the two answers with structured output. Agreement means a
quick approval; a disagreement says where to look. The owner still decides.

`client.messages.parse` with `output_config.format: zodOutputFormat(schema)` and `parsed_output` (null when parsing
failed) was checked against the `claude-api` skill; `zodOutputFormat` comes from `@anthropic-ai/sdk/helpers/zod`.

```ts
// file: ask-check.ts
import type Anthropic from '@anthropic-ai/sdk'
import { zodOutputFormat } from '@anthropic-ai/sdk/helpers/zod'
import { z } from 'zod'
import { answer, citationsOf, type AskCitation, type AnswerDetail } from './ask.ts'
import { splitConfidence, splitFollowUps } from './answer-text.ts'
import type { AskConfig } from './ask-config.ts'
import type * as kb from './kb.ts'

/** A second opinion on an answer: a deeper investigation and a judge's comparison, stored on the message. */
export type SecondOpinion = {
  status: 'queued' | 'running' | 'done' | 'failed'
  startedAt: string
  finishedAt?: string
  error?: string
  verdict?: 'agrees' | 'partly' | 'disagrees'
  score?: number // 0 (contradicts) to 1 (same facts)
  summary?: string
  conflicts?: string[] // "the answer says X; the reference says Y"
  missing?: string[] // what the reference found that the answer left out
  reference?: string // the reference answer
  referenceFiles?: string[] // repo:path it cited or read
  lookups?: number
  tokens?: { input: number; output: number }
}

type Cfg = Pick<AskConfig, 'askModel' | 'askEffort' | 'askMaxToolCalls'>
// A deeper run than a question gets: more lookups and effort, so it reads what a quick answer may skip.
export const REFERENCE = { lookups: 24, effort: 'xhigh' } as const
const RUNNING_TOO_LONG_MS = 20 * 60_000 // a check still "running" after this was cut off (the server restarted)

export const Verdict = z.object({
  verdict: z.enum(['agrees', 'partly', 'disagrees']),
  score: z.number(),
  summary: z.string(),
  conflicts: z.array(z.string()),
  missing: z.array(z.string()),
})
export type Verdict = z.infer<typeof Verdict>

// E8: name the software and its systems in the first sentence, as in the answering prompt.
export const JUDGE = `You compare two answers to the same question about <the software and its systems>. "answer" is the answer people saw; "reference" came from a deeper investigation of the same code. Judge the answer against the reference on facts only:
- the conclusion (yes/no/it depends, and on what);
- the conditions, numbers and thresholds, settings and their values;
- which systems are involved and the order of the steps.
Ignore style, length, the diagram, citation markers and follow-up suggestions. A Plain answer leaves out file, class and setting names on purpose: that is not missing. Where the reference is less sure than the answer, or says it did not read something, do not count it against the answer.
Return: verdict "agrees" (same facts, any differences are detail), "partly" (the main conclusion holds but a condition, number or step differs or is missing) or "disagrees" (the conclusion or a deciding fact contradicts); score from 0 (contradicts) to 1 (same facts); summary in one plain sentence; conflicts, each one line "The answer says …; the reference says …"; missing, each one line naming an important fact the reference has and the answer lacks. Empty lists when there are none.`

/** The judge's input: the question and the two answers, without their confidence and follow-up lines. */
export function judgeInput(question: string, shown: string, reference: string): string {
  const bare = (t: string) => splitFollowUps(splitConfidence(t).text).text
  return `<question>\n${question}\n</question>\n\n<answer>\n${bare(shown)}\n</answer>\n\n<reference>\n${bare(reference)}\n</reference>`
}

const filesOf = (citations: AskCitation[], reads: string[]) => [...new Set([...citations.map((c) => `${c.repo}:${c.path}`), ...reads])]
const clamp = (n: number) => Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0))

type Row = { id: string; conversation_id: string; created_at: Date; question: string; answer: string | null; detail: AnswerDetail; second_opinion: SecondOpinion | null }

const save = (db: kb.Db, id: number, op: SecondOpinion) => db.query('update kb_message set second_opinion = $2 where id = $1', [id, JSON.stringify(op)])

/** Investigate a message's question again and judge its answer against the result; stored on the message. */
/** E11: the runtime-settings block a stored question was asked with (read its key from the message row). */
export type ContextFor = (m: { id: number; conversationId: string }) => Promise<string | undefined>

export async function secondOpinion(client: Anthropic, db: kb.Db, cfg: Cfg, id: number, opts: { contextFor?: ContextFor } = {}): Promise<SecondOpinion> {
  const m = (await db.query<Row>('select id, conversation_id, created_at, question, answer, detail, second_opinion from kb_message where id = $1', [id])).rows[0]
  if (!m) throw new Error(`No question ${id}.`)
  const startedAt = m.second_opinion?.startedAt ?? new Date().toISOString()
  await save(db, id, { status: 'running', startedAt })
  try {
    // the same context the question had: the exchanges before it in its conversation, and its contextBlock (E11)
    const history = (
      await db.query<{ question: string; answer: string }>(
        `select question, answer from kb_message where conversation_id = $1 and created_at < $2 and answer is not null order by created_at desc limit 6`,
        [m.conversation_id, m.created_at],
      )
    ).rows.reverse()
    const ref = await answer(client, db, { ...cfg, askMaxToolCalls: REFERENCE.lookups, askEffort: REFERENCE.effort }, m.question, history, {
      detail: 'technical',
      contextBlock: opts.contextFor ? await opts.contextFor({ id: Number(m.id), conversationId: m.conversation_id }) : undefined,
    })
    const referenceFiles = filesOf(citationsOf(ref.answer), ref.reads)
    let verdict: Verdict
    if (m.answer) {
      const judged = await client.messages.parse({
        model: cfg.askModel,
        max_tokens: 4000,
        system: JUDGE,
        output_config: { effort: 'medium', format: zodOutputFormat(Verdict) },
        messages: [{ role: 'user', content: judgeInput(m.question, m.answer, ref.answer) }],
      })
      if (!judged.parsed_output) throw new Error('The judge gave no verdict.')
      verdict = { ...judged.parsed_output, score: clamp(judged.parsed_output.score) }
    } else {
      // the question failed: nothing to compare, the reference is the answer to review
      verdict = { verdict: 'disagrees', score: 0, summary: 'No answer was given; the reference answer is below.', conflicts: [], missing: [] }
    }
    const done: SecondOpinion = {
      status: 'done',
      startedAt,
      finishedAt: new Date().toISOString(),
      ...verdict,
      reference: ref.answer,
      referenceFiles,
      lookups: ref.toolCalls,
      tokens: { input: ref.inputTokens, output: ref.outputTokens },
    }
    await save(db, id, done)
    return done
  } catch (e) {
    const failed: SecondOpinion = { status: 'failed', startedAt, finishedAt: new Date().toISOString(), error: (e as Error).message.slice(0, 300) }
    await save(db, id, failed).catch(() => {})
    return failed
  }
}

/** A check still marked running long after it started was cut off (the server restarted): show it as failed. */
export function settled(op: SecondOpinion | null): SecondOpinion | null {
  if (!op || (op.status !== 'running' && op.status !== 'queued')) return op
  return Date.now() - Date.parse(op.startedAt) > RUNNING_TOO_LONG_MS ? { ...op, status: 'failed', error: 'The check was cut off (the server restarted). Run it again.' } : op
}

/** Checks run in the background, two at a time, in the order asked. In memory: a restart loses the queue. */
export class CheckQueue {
  private waiting: number[] = []
  private running = new Set<number>()
  private run: (id: number) => Promise<unknown>
  private queued: (id: number) => Promise<unknown>
  private size: number
  constructor(run: (id: number) => Promise<unknown>, queued: (id: number) => Promise<unknown>, size = 2) {
    this.run = run
    this.queued = queued
    this.size = size
  }
  has(id: number) {
    return this.running.has(id) || this.waiting.includes(id)
  }
  async add(id: number) {
    if (this.has(id)) return
    this.waiting.push(id)
    await this.queued(id).catch(() => {})
    this.next()
  }
  private next() {
    while (this.running.size < this.size && this.waiting.length) {
      const id = this.waiting.shift()!
      this.running.add(id)
      void this.run(id)
        .catch(() => {})
        .finally(() => {
          this.running.delete(id)
          this.next()
        })
    }
  }
}
```

## 7. `golden:pull`: from the database into the versioned file

```ts
// file: golden-pull.ts
import { writeFileSync } from 'node:fs'
import { GOLDEN_FILE, loadGolden, type Golden } from './golden.ts'

// Copy the golden questions owners approved on the review page into eval/golden.json, so the evals ask them and the
// set is versioned with the code. The questions written by hand in the file stay; the ones from the review page
// ("review-<n>") are replaced by what the server holds now, so a retired one leaves.
//
//   KB_URL=https://<your-api-host> KB_ADMIN_TOKEN=… npm run golden:pull
//
// Commit the changed file. The export holds questions and file paths only, never who asked.

const base = (process.env.KB_URL?.trim() || 'http://localhost:3000').replace(/\/+$/, '')
const token = process.env.KB_ADMIN_TOKEN?.trim()

const r = await fetch(`${base}/api/v1/admin/ask/golden.json`, { headers: token ? { authorization: `Bearer ${token}` } : {} }).catch((e: Error) => {
  console.error(`Can't reach ${base}: ${e.message}`)
  process.exit(1)
})
if (!r.ok) {
  console.error(`${base} answered ${r.status}${r.status === 401 || r.status === 403 ? ': set KB_ADMIN_TOKEN to the server’s admin token' : ''}.`)
  process.exit(1)
}
const fromReview = ((await r.json()) as { questions: Golden[] }).questions
const current = loadGolden()
const before = new Set(current.questions.filter((q) => q.id.startsWith('review-')).map((q) => q.id))
const after = new Set(fromReview.map((q) => q.id))
current.questions = [...current.questions.filter((q) => !q.id.startsWith('review-')), ...fromReview]
writeFileSync(GOLDEN_FILE, `${JSON.stringify(current, null, 2)}\n`)

const added = [...after].filter((id) => !before.has(id)).length
const gone = [...before].filter((id) => !after.has(id)).length
console.log(`${fromReview.length} approved question(s) from ${base}: ${added} new, ${gone} retired. ${current.questions.length} golden questions in eval/golden.json.`)
```

## 8. Tests

```ts
// file: ask-review.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type Anthropic from '@anthropic-ai/sdk'
import { forEval, GoldenBody, ReviewBody, reviewOrder, toReviewItem } from './ask-review.ts'
import { CheckQueue, judgeInput, secondOpinion, settled } from './ask-check.ts'
import { matches } from './golden.ts'
import type { Db } from './kb.ts'

const message = (id: number, over: Record<string, unknown> = {}) => ({
  id: String(id),
  created_at: new Date(Date.UTC(2026, 10, 16, 9, id)),
  question: `Question ${id}?`,
  answer: 'It waits.\n\nConfidence: High — read it',
  feedback: null,
  citations: [
    { repo: 'orders-api', sha: 'abc', path: 'a/dispatch.ts', line: 3 },
    { repo: 'orders-api', sha: 'abc', path: 'a/dispatch.ts', line: 9 },
  ],
  reads: ['orders-api:a/dispatch.ts', 'orders-api:a/other.ts'],
  duration_ms: 30_000,
  detail: 'plain' as const,
  error: null as string | null,
  second_opinion: null,
  ...over,
})

test('expected files match on a folder boundary', () => {
  assert.ok(matches('src/find-destination.ts', 'find-destination.ts'))
  assert.ok(!matches('src/replay-find-destination.ts', 'find-destination.ts'))
  assert.ok(matches('find-destination.ts', 'find-destination.ts'))
})

test('a review item: cited files once each, what was read, and the confidence from the answer', () => {
  const i = toReviewItem(message(1))
  assert.deepEqual(i.cited, ['orders-api:a/dispatch.ts'])
  assert.deepEqual(i.read, ['orders-api:a/dispatch.ts', 'orders-api:a/other.ts'])
  assert.equal(i.confidence, 'high')
  assert.equal(i.messageId, 1)
})

test('the queue shows unhelpful answers first, then unsure ones, helpful ones last', () => {
  const items = [
    toReviewItem(message(1, { feedback: 1 })),
    toReviewItem(message(2)),
    toReviewItem(message(3, { answer: 'Maybe.\nConfidence: Low — little found' })),
    toReviewItem(message(4, { feedback: -1 })),
    toReviewItem(message(5, { answer: 'Maybe.\nConfidence: Medium — a setting' })),
    toReviewItem(message(6)),
  ]
  assert.deepEqual(reviewOrder(items).map((i) => i.messageId), [4, 3, 5, 6, 2, 1])
})

test('an approved question, as the evals read it: files by path, no names', () => {
  const g = { id: 7, question: 'Q?', expect: ['orders-api:a/dispatch.ts', 'platform/worker:b.py'], mention: ['409'], notFound: false, status: 'approved' as const, messageId: 3, note: null, reviewedBy: 'someone', reviewedAt: '' }
  assert.deepEqual(forEval(g), { id: 'review-7', question: 'Q?', expect: ['a/dispatch.ts', 'b.py'], mention: ['409'] })
  assert.deepEqual(forEval({ ...g, expect: [], mention: [], notFound: true }), { id: 'review-7', question: 'Q?', notFound: true })
})

test('approving needs a file a right answer uses, or "not in the code"; patterns must be valid', () => {
  assert.ok(GoldenBody.safeParse({ question: 'How?', expect: ['orders-api:a.ts'] }).success)
  assert.ok(GoldenBody.safeParse({ question: 'How?', notFound: true }).success)
  assert.ok(!GoldenBody.safeParse({ question: 'How?' }).success, 'neither files nor not-found')
  assert.ok(!GoldenBody.safeParse({ question: 'How?', expect: ['a.ts'] }).success, 'a file needs its repo')
  assert.ok(!GoldenBody.safeParse({ question: 'How?', expect: ['orders-api:a.ts'], mention: ['('] }).success, 'a broken pattern')
  assert.ok(ReviewBody.safeParse({ action: 'skip' }).success)
  assert.ok(!ReviewBody.safeParse({ action: 'approve' }).success)
})

test('a failed question waits for review too, first; a cause is checked', () => {
  const failed = toReviewItem(message(9, { answer: null, error: 'The AI service did not answer.' }))
  assert.equal(failed.error, 'The AI service did not answer.')
  assert.equal(failed.confidence, null)
  assert.equal(reviewOrder([toReviewItem(message(1)), failed])[0].messageId, 9)
  assert.ok(ReviewBody.safeParse({ action: 'skip', cause: 'search_missed' }).success)
  assert.ok(!ReviewBody.safeParse({ action: 'skip', cause: 'whatever' }).success)
})

test('the judge compares the facts, without the confidence and follow-up lines', () => {
  const t = judgeInput('Q?', 'It waits.\nFollow-ups: a? | b?\nConfidence: High — read it', 'It waits 10 s.\nConfidence: Medium — x')
  assert.equal(t, '<question>\nQ?\n</question>\n\n<answer>\nIt waits.\n</answer>\n\n<reference>\nIt waits 10 s.\n</reference>')
})

test('a second opinion: a deeper run of the same question, judged, stored on the message', async () => {
  const saved: unknown[] = []
  const msg = { id: '7', conversation_id: 'c', created_at: new Date(), question: 'When does the dispatcher give up on a job?', answer: 'After 3 tries.\nConfidence: High — read it', detail: 'plain', second_opinion: null }
  const db = {
    query: async (sql: string, params: unknown[]) => {
      if (/^update kb_message set second_opinion/.test(sql)) saved.push(JSON.parse(params[1] as string))
      if (/from kb_message where id = \$1/.test(sql)) return { rows: [msg] }
      return { rows: [] }
    },
    connect: async () => ({ query: async () => ({ rows: [] }), release() {} }),
  } as unknown as Db
  const seen: { model: string; output_config: { effort: string } }[] = []
  const client = {
    beta: { messages: { create: async (p: never) => (seen.push(p), { model: 'm', usage: { input_tokens: 100, output_tokens: 50 }, stop_reason: 'end_turn', content: [{ type: 'text', text: 'After 5 tries [dispatch@abcdef1:retry_policy.py:3].\nConfidence: High — read it' }] }) } },
    messages: { parse: async () => ({ parsed_output: { verdict: 'disagrees', score: 1.7, summary: 'The limit differs.', conflicts: ['The answer says 3; the reference says 5'], missing: [] } }) },
  } as unknown as Anthropic
  const cfg = { askModel: 'claude-opus-5-5', askEffort: 'high', askMaxToolCalls: 14 }
  const op = await secondOpinion(client, db, cfg, 7)
  assert.equal(op.status, 'done')
  assert.equal(op.verdict, 'disagrees')
  assert.equal(op.score, 1, 'the score is kept between 0 and 1')
  assert.deepEqual(op.referenceFiles, ['dispatch:retry_policy.py'])
  assert.deepEqual(op.conflicts, ['The answer says 3; the reference says 5'])
  assert.equal(seen[0].output_config.effort, 'xhigh', 'a deeper run than the question had')
  assert.deepEqual(saved.map((s) => (s as { status: string }).status), ['running', 'done'])
})

test('second opinions run two at a time, in order; a cut-off one shows as failed', async () => {
  const order: number[] = []
  let live = 0
  let most = 0
  const q = new CheckQueue(async (id) => {
    live++
    most = Math.max(most, live)
    await new Promise((r) => setTimeout(r, 5))
    order.push(id)
    live--
  }, async () => {})
  await Promise.all([1, 2, 3, 4].map((id) => q.add(id)))
  await new Promise((r) => setTimeout(r, 40))
  assert.equal(most, 2)
  assert.deepEqual(order.sort(), [1, 2, 3, 4])
  assert.equal(settled({ status: 'running', startedAt: new Date(Date.now() - 3_600_000).toISOString() })?.status, 'failed')
  assert.equal(settled({ status: 'running', startedAt: new Date().toISOString() })?.status, 'running')
})
```

## 9. Reading the numbers

- **FAIL** (never reached the expected file) is retrieval: fix search (`search-eval -- --lists` shows which list
  lost it) or the prompt's search instructions first, and only then think about a different embedding model.
- **MISS** (read but not cited) is wording: the answer used the file without a marker. Tighten the citation rule.
- **notFound failures** (cited something for an unanswerable question) are the most expensive kind: a confident
  invented answer. One unanswerable question in the seed set keeps this visible.
- **Cause counts** from the review queue (last 30 days) point at the next fix: `search_missed` -> search,
  `cannot_read` -> the filter or the index, `wrong_answer` -> the prompt or the model, `not_in_code` -> nothing to
  fix but the expectation.
- The seed set is small (about a dozen questions in the source): treat percentages as direction, not a benchmark.

## Pitfalls

- **P75. Match an expected file on a folder boundary (`path === f || path.endsWith('/' + f)`).**
  `find-destination.ts` is not `replay-find-destination.ts`. The source used it only in the search eval; this
  skill uses it in all three places (a correction, not yet proven in production in the other two).
- **P76. Run the free "expected files still exist" check after every refresh.** A moved file shows as a red step,
  not later as a wrong answer.
- **P77. Include at least one question the code cannot answer, and require "not found" plus zero citations.**
- **P78. PASS = cited or read every expected file and matched every phrase; MISS = read but not cited; FAIL = never
  reached.** MISS is wording, FAIL is retrieval: different fixes.
- **P79. Measure search without the model, with per-list ranks before fusion (`--lists`) and a grid of fusion
  variants (`--grid`).** It is free, and it shows which list lost the file.
- **P80. Fetch the candidate lists deep (200) once per query and reuse them across modes.**
- **P81. Order the review queue: failed and thumbs-down first, then low, then medium confidence, then the rest,
  thumbs-up last.**
- **P82. Approve atomically with `where review is null` and answer 409 on a lost race.**
- **P83. The exported golden file carries questions and file paths only; the pull replaces review-sourced ids and
  keeps hand-written ones.** No names of askers in the repo; retired questions disappear on the next pull.
- **P84. Second opinion: re-run deeper with the same history and context block (`contextFor`), judge facts only
  with structured output, clamp the score, and show a check "running" for over 20 minutes as failed.** The queue
  is in memory and a restart loses it.
- **P84a. Record why an answer went wrong from a fixed list (search missed / cannot read / wrong answer / not in
  the code / fine) and count the last 30 days.** The commonest cause is the next fix.

## Proven at

Second opinion, measured once: 80 s, 23 lookups, 350K input tokens; on a cross-system question it returned
"partly" (72%) because the quick answer had one side of the call right and skipped what the other system did with
it. The full paid eval of a dozen seed questions costs "a dollar or two". Default pass rate 0.8.
