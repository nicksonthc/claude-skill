# Answering: prompt assembly and the capped tool loop

Load this when wiring the model that answers questions: the system prompt skeleton, the style block, the tool
definitions, the capped tool loop with its pre-search, citation parsing, the HTTP layer with the NDJSON progress
stream, and the scripted-model tests. TypeScript with `@anthropic-ai/sdk` (proven on 1.8.0); the HTTP example uses
Fastify 5 but only `prepare` / `execute` / the stream need porting to another framework.

API surface used, checked against the `claude-api` skill on 2026-11-17: `client.beta.messages.create` with
`betas: ['server-side-fallback-2026-07-01']` and `fallbacks: 'default'` (refusal fallback; Claude API only, not on
Bedrock, Vertex AI, Foundry or the Batches API, where the SDK's client-side refusal-fallback middleware replaces
it), `output_config: { effort }`, `cache_control: { type: 'ephemeral' }` on a system block, `tool_choice` `auto` /
`none`, `usage.cache_read_input_tokens` / `usage.cache_creation_input_tokens`, `stop_reason: 'refusal'`. On
`claude-opus-5-5` the effort default is `medium`, so set it explicitly; thinking is adaptive and always on (send no
`thinking` field); forced `tool_choice` (`any` / `tool`) returns a 400, which this loop never uses.

## 1. Configuration (E14)

```ts
// file: ask-config.ts
// Answering is off until the key is set: the rest of the API runs without it (P74).
export function askConfig() {
  const int = (name: string, fallback: number) => {
    const raw = process.env[name]?.trim()
    const n = raw ? Number(raw) : fallback
    if (!Number.isInteger(n) || n < 0) throw new Error(`${name} must be a whole number, got "${raw}".`)
    return n
  }
  return {
    anthropicKey: process.env.ANTHROPIC_API_KEY?.trim() || null,
    askModel: process.env.ASK_MODEL?.trim() || 'claude-opus-5-5', // proven on: claude-opus-5-5
    askEffort: process.env.ASK_EFFORT?.trim() || 'high', // proven at: high (the model's own default is medium)
    askMaxToolCalls: int('ASK_MAX_TOOL_CALLS', 14), // proven at: 14 lookups per question
    askPerHour: int('ASK_PER_HOUR', 30), // proven at: 30 questions per person per hour
  }
}
export type AskConfig = ReturnType<typeof askConfig>
```

## 2. System prompt skeleton (E8) and the style block

The rules are one cached block. Everything that varies per question goes in later system blocks: the answer style
second, an optional runtime-settings block third (E11). Switching style or context then keeps the cache (P64).

Fill the `<...>` placeholders; drop the optional rules (diagram, follow-ups) you do not want. Rules 1, 5, 6, 7 and
the confidence rule are the load-bearing ones: evidence first, code over docs, strict citations, "I couldn't find
this" over a guess.

```ts
// file: ask.ts
import type Anthropic from '@anthropic-ai/sdk'
import * as kb from './kb.ts'
import { systemLinks } from './kb-contracts.ts'
import { systemName } from './systems.ts'
import type { AskConfig } from './ask-config.ts'

export type AnswerDetail = 'plain' | 'technical'
export type AskCitation = { repo: string; sha: string; path: string; line: number | null }

// E8: what the assistant is called, who asks, and how the systems fit together. Example of a filled architecture
// block (generic; the source project's had one line per system in the same shape):
//   - The order service (repo orders-api, NestJS) takes orders and calls the dispatcher.
//   - The dispatcher (repos dispatch and dispatch-worker, Flask) plans jobs and reports back to the order service.
//   - Calls go order service -> dispatcher -> devices. Events flow back dispatcher -> order service.
const NAME = '<assistant name>'
const SOFTWARE = '<the software, e.g. our order and dispatch platform>'
const AUDIENCE = '<audience, e.g. colleagues in operations, support, sales, management and engineering>'
const ARCHITECTURE = `<one line per system: its name as people know it, its repo(s) and stack, what it does, whom it calls>
<then the call direction, and the direction events flow back>`
const SYSTEM_NAMES_AS_PEOPLE_SAY = '<the systems as people know them, e.g. the order service, the dispatcher>'
const DIAGRAMS = true // optional rule
const FOLLOW_UPS = true // optional rule (the page shows them as buttons; splitFollowUps takes them out)

// The source is one literal string with ten numbered rules; this array (optional rules dropped, numbers assigned at
// build time) is a refactor, not yet proven in production. The rule texts are the source's, genericized.
const RULES = [
  'Find the evidence before answering: search for the topic, then read the code that decides the behaviour. Follow a flow across repos when the question spans them: system_links shows how two systems call each other, and search results say which other system a file calls or is called by. Prefer the code, tests and settings over prose docs: docs can be out of date. If a doc and the code disagree, say so and go with the code.',
  `Write in the answer style given after these rules. In either style, name the systems as people know them: ${SYSTEM_NAMES_AS_PEOPLE_SAY}.`,
  'Open with the answer in one or two sentences: yes, no, or "it depends on X". Then explain in a few short bullets, with the conditions and numbers (thresholds, delays, limits) that change the outcome, in plain units.',
  DIAGRAMS &&
    'When the answer is a flow (one system asking another, step by step) or a decision with branches, add one diagram after the opening: a fenced block marked mermaid. Use "sequenceDiagram" for messages between systems (participants named as people know them) and "flowchart TD" for decisions. Words on every arrow and box as the answer style allows, at most 12 steps, no styling or colours. Draw only what you read, and don\'t repeat the diagram in prose. No diagram for a simple yes/no or a single number.',
  'Back every factual claim with a source marker [repo@sha:path:line] at the end of its sentence, using the sha shown in the tool results and a line number you actually read, for example [orders-api@1a2b3c4:src/orders/confirm.ts:61]. The page turns these into small numbered links, so they never interrupt the reading.' + (DIAGRAMS ? ' Never put them inside the diagram.' : ''),
  'Settings can be changed at runtime or per deployment. When behaviour depends on one, give the default you saw and say a deployment may have changed it.',
  'If the indexed files don\'t answer the question, say "I couldn\'t find this in the code I can read" and say in plain words what you looked at. Never guess, and never describe behaviour you didn\'t read. Files holding secrets and customer configuration are deliberately not indexed.',
  'Keep answers short and concrete. Ask one clarifying question only if the question is truly ambiguous.',
  FOLLOW_UPS &&
    'Just before the confidence line, add one line exactly: "Follow-ups: <question> | <question> | <question>", two or three short questions the asker could ask next, in their words and the answer style, each one the code can answer (the next step of the flow, the setting that changes it, what happens when it fails, the other system involved). Leave the line out only when you found nothing.',
  'End every answer with one last line, exactly: "Confidence: High — <why>", "Confidence: Medium — <why>" or "Confidence: Low — <why>", the why in a few plain words. High: you read the code that decides this and it is unambiguous. Medium: you read related code, but part of the answer depends on a setting, on a system you could not read, or on your inference. Low: you found little direct evidence, or none (then say what is missing). The page shows this line as a label above the answer.',
].filter((r): r is string => typeof r === 'string')

// Built once at module load: the same bytes on every request, so the cache prefix holds.
const SYSTEM = `You are ${NAME}. You answer questions about ${SOFTWARE} for ${AUDIENCE}. Each question comes with an answer style (Plain or Technical), given after these rules. You can only see an indexed, read-only copy of each repository's source code, docs, settings, schema and tests, through your tools.

How the system fits together:
${ARCHITECTURE}
Call repo_map first if you are unsure which repos and branches are indexed, and when they were indexed.

How to answer:
${RULES.map((r, i) => `${i + 1}. ${r}`).join('\n')}`
// Fail at start, not in front of a user, when a placeholder was left unfilled.
const unfilled = [NAME, SOFTWARE, AUDIENCE, ARCHITECTURE, SYSTEM_NAMES_AS_PEOPLE_SAY].find((v) => v.startsWith('<'))
if (unfilled && process.env.NODE_ENV === 'production') throw new Error(`Fill the placeholder ${unfilled.split('\n')[0]} in ask.ts (E8).`)

// The answer style, chosen by the asker. A second system block after the cached rules, so switching style keeps the
// cache. Optional: one style is fine; then send a single fixed second block, or none.
const STYLE: Record<AnswerDetail, string> = {
  plain: `Answer style: Plain. Write for someone who doesn't read code. Say what the software does, in its own words. Never show code, and never name files, folders, functions, classes, variables, database tables or columns, endpoints or setting keys in your sentences or the diagram. Describe them instead: "the retry limit a deployment sets", not the setting's name.`,
  technical: `Answer style: Technical. The reader is an engineer who will open the code. Still open with the answer in plain words, then name exactly what decides it: the files, classes and functions, the database tables and columns, the setting keys with their defaults, the endpoints and the messages between systems. A short code excerpt (a few lines) is fine when it shows the deciding condition. The diagram may use class, endpoint and table names.`,
}
```

## 3. Tool definitions

The descriptions tell the model what it may cite as read (the first three search results show numbered code) and
when to use which tool. Tools stay declared on every call, including the last (P65).

```ts
// file: ask.ts (continued)
const TOOLS: Anthropic.Beta.BetaTool[] = [
  {
    name: 'repo_map',
    description: 'List the indexed repositories with their branch, the commit they were read at, when they were indexed, and file counts.',
    input_schema: { type: 'object', properties: {}, additionalProperties: false },
  },
  {
    name: 'search',
    description:
      'Find the code about a topic, by words and by meaning: describe what you are looking for in a few words ("order cancelled after payment fails"), or give names you know. Each result is a file with the section that matched (its lines and the function or class it is in). The first three show the code of that section with line numbers, which you can cite as read; the rest show their best lines, so read the section before relying on it. Use grep for an exact string.',
    input_schema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'A short description or a few names, e.g. "order cancelled after payment fails"' },
        repo: { type: 'string', description: 'Limit to one repo name from repo_map' },
        kind: { type: 'string', enum: ['code', 'test', 'doc', 'setting', 'schema'] },
      },
      required: ['query'],
      additionalProperties: false,
    },
  },
  {
    name: 'grep',
    description: 'Find an exact piece of text (case-insensitive) such as a function name, setting key or error message, with the matching lines.',
    input_schema: {
      type: 'object',
      properties: {
        text: { type: 'string', description: 'Exact text, 3 to 120 characters' },
        repo: { type: 'string' },
        path_prefix: { type: 'string', description: 'Only files whose path starts with this, e.g. "src/orders/"' },
        kind: { type: 'string', enum: ['code', 'test', 'doc', 'setting', 'schema'] },
      },
      required: ['text'],
      additionalProperties: false,
    },
  },
  {
    name: 'read_file',
    description: 'Read a file with line numbers. Up to 400 lines per call; pass from and to for a range.',
    input_schema: {
      type: 'object',
      properties: { repo: { type: 'string' }, path: { type: 'string' }, from: { type: 'integer', minimum: 1 }, to: { type: 'integer', minimum: 1 } },
      required: ['repo', 'path'],
      additionalProperties: false,
    },
  },
  {
    name: 'list_dir',
    description: 'List the folders and files directly under a path of a repo.',
    input_schema: {
      type: 'object',
      properties: { repo: { type: 'string' }, path: { type: 'string', description: 'Folder path; omit for the repo root' } },
      required: ['repo'],
      additionalProperties: false,
    },
  },
  {
    name: 'system_links', // only with 2+ systems (contracts.md)
    description:
      'How one system calls another: the HTTP calls found in the code between two repos (or between one repo and every other), each with the route or path, the calling line and the handling line. Use it to follow a flow across systems, then read both ends. A URL that comes from configuration (callbacks, per-site base URLs) is not found here.',
    input_schema: {
      type: 'object',
      properties: {
        repo: { type: 'string', description: 'A repo name from repo_map' },
        other: { type: 'string', description: 'The other repo; omit for every other repo' },
      },
      required: ['repo'],
      additionalProperties: false,
    },
  },
]
```

## 4. Running a tool: text on every path

```ts
// file: ask.ts (continued)
const str = (v: unknown) => (typeof v === 'string' ? v : undefined)
const int = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)

async function runTool(db: kb.Db, name: string, input: Record<string, unknown>): Promise<string> {
  try {
    switch (name) {
      case 'repo_map':
        return await kb.repoMap(db)
      case 'search':
        return await kb.search(db, { query: str(input.query) ?? '', repo: str(input.repo), kind: str(input.kind) })
      case 'grep':
        return await kb.grep(db, { text: str(input.text) ?? '', repo: str(input.repo), path_prefix: str(input.path_prefix), kind: str(input.kind) })
      case 'read_file':
        return await kb.readFile(db, { repo: str(input.repo) ?? '', path: str(input.path) ?? '', from: int(input.from), to: int(input.to) })
      case 'list_dir':
        return await kb.listDir(db, { repo: str(input.repo) ?? '', path: str(input.path) })
      case 'system_links':
        return await systemLinks(db, { repo: str(input.repo) ?? '', other: str(input.other) })
      default:
        return `Unknown tool ${name}.`
    }
  } catch (e) {
    // A timeout or a bad argument is information for the model, not a failed request.
    return `The ${name} lookup failed: ${(e as Error).message}`
  }
}

// One line of progress for the page while the model works: what it is looking at, in plain words (systems, not files).
export function describeLookup(name: string, input: Record<string, unknown>): string {
  const repo = str(input.repo)
  const sys = repo ? systemName(repo) : null
  switch (name) {
    case 'repo_map':
      return 'Checking what it can read'
    case 'search':
      return str(input.query) ? `Searching ${sys ?? 'every system'} for “${str(input.query)}”` : `Searching ${sys ?? 'every system'} for the question`
    case 'grep':
      return `Looking for “${str(input.text) ?? ''}”${sys ? ` in ${sys}` : ''}`
    case 'read_file':
      return `Reading how ${sys ?? 'the software'} does it`
    case 'list_dir':
      return `Looking around ${sys ?? 'the code'}`
    case 'system_links': {
      const other = str(input.other)
      return `Checking how ${sys ?? 'one system'} talks to ${other ? systemName(other) : 'the others'}`
    }
    default:
      return 'Looking things up'
  }
}
```

## 5. `answer()`: pre-search, capped loop, empty-reply guard

```ts
// file: ask.ts (continued)
// [repo@sha:path:line], as the prompt asks the model to write them. Repo names may contain '/'; a range keeps its
// first line.
const CITATION = /\[([A-Za-z0-9_./-]+)@([0-9a-f]{7,40}):([^\]\s]+?)(?::(\d+)(?:-\d+)?)?\]/g
export function citationsOf(text: string): AskCitation[] {
  const seen = new Set<string>()
  const out: AskCitation[] = []
  for (const m of text.matchAll(CITATION)) {
    const c = { repo: m[1], sha: m[2], path: m[3], line: m[4] ? Number(m[4]) : null }
    const key = `${c.repo}@${c.sha}:${c.path}:${c.line}`
    if (!seen.has(key)) {
      seen.add(key)
      out.push(c)
    }
  }
  return out
}

const textOf = (blocks: Anthropic.Beta.BetaContentBlock[]) =>
  blocks.flatMap((b) => (b.type === 'text' ? [b.text] : [])).join('\n').trim()

export type AskResult = {
  answer: string
  toolCalls: number
  model: string
  inputTokens: number
  outputTokens: number
  // "repo:path" of every file the model opened, so an eval can tell "never found it" from "found it, didn't cite it".
  reads: string[]
  searchMs: number // time spent in the search tool
}

// One question, answered by a capped tool loop. `history` is earlier question/answer text of the same conversation.
// `onProgress` hears each lookup as it starts; `signal` stops the work when the person has gone away.
// `contextBlock` (E11, optional): a third system block, e.g. the deployed settings that choose a code path.
export async function answer(
  client: Anthropic,
  db: kb.Db,
  cfg: Pick<AskConfig, 'askModel' | 'askEffort' | 'askMaxToolCalls'>,
  question: string,
  history: { question: string; answer: string }[],
  opts: { onProgress?: (text: string) => void; onTool?: (name: string) => void; signal?: AbortSignal; detail?: AnswerDetail; contextBlock?: string } = {},
): Promise<AskResult> {
  let toolCalls = 0
  let inputTokens = 0
  let outputTokens = 0
  let model = cfg.askModel
  let searchMs = 0
  const reads = new Set<string>()

  // The question is searched before the model is first asked, so its first turn can already read or answer instead of
  // only deciding what to search for (one round fewer; each round is a full model call).
  opts.onProgress?.(describeLookup('search', {}))
  opts.onTool?.('search')
  const t0 = Date.now()
  const found = await kb.search(db, { query: kb.keywords(question) || question }).catch(() => null)
  searchMs += Date.now() - t0
  const messages: Anthropic.Beta.BetaMessageParam[] = [
    ...history.flatMap((h): Anthropic.Beta.BetaMessageParam[] => [
      { role: 'user', content: h.question },
      { role: 'assistant', content: h.answer },
    ]),
    {
      role: 'user',
      content: found
        ? [
            { type: 'text', text: question },
            { type: 'text', text: `<search query="the question's keywords">\n${found}\n</search>\nThe question above was searched for you already. Use these results as a start: read further, search with other words or names, or grep, until you have the code that decides the answer.` },
          ]
        : question,
    },
  ]

  // betas and fallbacks: if the model declines for a policy reason, the API retries on its default substitute.
  const call = async (withTools: boolean) => {
    const r = await client.beta.messages.create(
      {
        model: cfg.askModel,
        max_tokens: 16000,
        betas: ['server-side-fallback-2026-07-01'],
        fallbacks: 'default',
        system: [
          { type: 'text', text: SYSTEM, cache_control: { type: 'ephemeral' } },
          { type: 'text', text: STYLE[opts.detail ?? 'plain'] },
          ...(opts.contextBlock ? [{ type: 'text' as const, text: opts.contextBlock }] : []),
        ],
        tools: TOOLS,
        // Tools stay declared on the last call so the cached prefix is the same; 'none' stops further use.
        tool_choice: withTools ? { type: 'auto' } : { type: 'none' },
        output_config: { effort: cfg.askEffort as 'low' | 'medium' | 'high' | 'xhigh' | 'max' },
        messages,
      },
      { signal: opts.signal },
    )
    model = r.model // a fallback may have answered
    // input_tokens alone under-reports once caching works
    inputTokens += r.usage.input_tokens + (r.usage.cache_read_input_tokens ?? 0) + (r.usage.cache_creation_input_tokens ?? 0)
    outputTokens += r.usage.output_tokens
    return r
  }

  let response = await call(true)
  while (response.stop_reason === 'tool_use') {
    messages.push({ role: 'assistant', content: response.content })
    const results: Anthropic.Beta.BetaToolResultBlockParam[] = []
    for (const block of response.content) {
      if (block.type !== 'tool_use') continue
      // Every tool_use needs a tool_result: past the cap, answer it with an error that says "answer now".
      if (toolCalls >= cfg.askMaxToolCalls) {
        results.push({ type: 'tool_result', tool_use_id: block.id, content: 'Lookup budget used up. Answer now from what you have read.', is_error: true })
        continue
      }
      toolCalls++
      opts.onTool?.(block.name)
      const input = block.input && typeof block.input === 'object' ? (block.input as Record<string, unknown>) : {}
      opts.onProgress?.(describeLookup(block.name, input))
      if (block.name === 'read_file' && str(input.repo) && str(input.path)) reads.add(`${str(input.repo)}:${str(input.path)}`)
      const t0 = Date.now()
      results.push({ type: 'tool_result', tool_use_id: block.id, content: await runTool(db, block.name, input) })
      if (block.name === 'search') searchMs += Date.now() - t0
    }
    messages.push({ role: 'user', content: results })
    response = await call(toolCalls < cfg.askMaxToolCalls) // over budget: the next call has tools off
  }

  // An empty reply that ends the turn (the model took the turn as finished, typically right after reading): ask once
  // for the answer instead of giving up. Seen in production.
  if (!textOf(response.content) && response.stop_reason === 'end_turn') {
    console.warn(`ask: empty reply after ${toolCalls} lookups (blocks: ${response.content.map((b) => b.type).join(',') || 'none'}); asking once more`)
    if (response.content.length) messages.push({ role: 'assistant', content: response.content })
    messages.push({ role: 'user', content: 'Please continue: write the answer now, from what you have read.' })
    response = await call(false)
  }

  let text = textOf(response.content)
  if (response.stop_reason === 'refusal') text = 'I could not answer that question.'
  else if (response.stop_reason === 'max_tokens') text += '\n\n(The answer was cut off. Ask a narrower question for the rest.)'
  if (!text) text = 'I could not produce an answer. Try rephrasing the question.'
  return { answer: text, toolCalls, model, inputTokens, outputTokens, reads: [...reads], searchMs }
}
```

## 6. Confidence and follow-up lines

The model ends with a parseable confidence line (and, optionally, a follow-ups line just before it). Strip both
before displaying the answer as prose and before judging it (P74b).

```ts
// file: answer-text.ts
export type Confidence = { level: 'high' | 'medium' | 'low'; why: string }
const CONFIDENCE = /^\W*confidence\W*(high|medium|low)\b\W*(.*?)\W*$/i

// "Follow-ups: <question> | <question> | <question>", one line just before the confidence line.
const FOLLOW_UPS = /^\W*(?:suggested\s+)?follow[- ]?ups?\W*:\s*(.+)$/i
export function splitFollowUps(text: string): { text: string; followUps: string[] } {
  const lines = text.trimEnd().split('\n')
  for (let i = lines.length - 1; i >= Math.max(0, lines.length - 5); i--) {
    const m = FOLLOW_UPS.exec(lines[i].trim())
    if (!m) continue
    lines.splice(i, 1)
    const followUps = m[1]
      .split('|')
      .map((q) => q.trim().replace(/^["“'\d.)*_\s-]+|["”'*_\s]+$/g, '')) // numbering, quotes, bold
      .filter((q) => q.length >= 3 && q.length <= 160)
      .slice(0, 3)
    return { text: lines.join('\n').trimEnd(), followUps }
  }
  return { text, followUps: [] }
}

export function splitConfidence(text: string): { text: string; confidence: Confidence | null } {
  const lines = text.trimEnd().split('\n')
  for (let i = lines.length - 1; i >= Math.max(0, lines.length - 3); i--) {
    const m = CONFIDENCE.exec(lines[i].trim())
    if (!m) continue
    lines.splice(i, 1)
    return { text: lines.join('\n').trimEnd(), confidence: { level: m[1].toLowerCase() as Confidence['level'], why: m[2].replace(/^[\s—–:.-]+/, '') } }
  }
  return { text, confidence: null }
}
```

## 7. HTTP layer (E12)

Framework-neutral contract, Fastify as the example:

- **`prepare`** refuses everything it can before the model is asked: no key (503, feature off), bad payload
  (422), over the per-person hourly limit counted from stored messages (429 with `retry-after`), a conversation
  that is not the asker's (404). It loads the last 6 exchanges as history (P74a).
- **`execute`** calls `answer()`, parses citations, and stores the exchange; on failure it stores the failure too,
  marking a closed tab as `cancelled by the asker` (P71), then rethrows.
- **`POST /ask?stream=1`** answers as NDJSON: `{"type":"progress","text":…}` per lookup, then one `result` or
  `error` line. Proxy buffering off (`x-accel-buffering: no`), the model call aborted when the client goes away
  (P72).
- Feedback (thumbs), the source-excerpt route behind each citation, and a status route for the page footer.
  Listing and reopening the asker's own conversations is a straightforward addition, scoped by `user_sub`.

```ts
// file: ask-http.ts
import Anthropic from '@anthropic-ai/sdk'
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify'
import { z } from 'zod'
import * as kb from './kb.ts'
import { answer, citationsOf, type AskCitation } from './ask.ts'
import type { AskConfig } from './ask-config.ts'

const AskBody = z.object({
  question: z.string().trim().min(3).max(2000),
  conversationId: z.uuid().optional(),
  detail: z.enum(['plain', 'technical']).default('plain'),
})

export class AskError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

// What the person is told when a question fails. The same mapping serves the plain and the streamed response.
function describeError(e: unknown, log: (e: unknown) => void): { status: number; code: string; message: string } {
  if (e instanceof AskError) return { status: e.status, code: e.code, message: e.message }
  if (e instanceof Anthropic.RateLimitError) return { status: 503, code: 'ai_busy', message: 'The AI service is busy. Try again in a minute.' }
  if (e instanceof Anthropic.AuthenticationError) {
    log('Anthropic rejected ANTHROPIC_API_KEY')
    return { status: 503, code: 'ask_not_configured', message: 'The assistant could not reach the AI service. An owner needs to check its key.' }
  }
  if (e instanceof Anthropic.APIError || e instanceof Anthropic.APIConnectionError) {
    log(e)
    return { status: 502, code: 'ai_unavailable', message: 'The AI service did not answer. Try again in a moment.' }
  }
  log(e)
  return { status: 500, code: 'internal', message: 'Something failed on the server. The error is in the API log.' }
}

// E12: requireUser (the app's auth hook) and userSub (the signed-in person's stable id).
// E11 (optional): contextFor builds the runtime-settings block for a request (answering.md section 9).
export function registerAsk(app: FastifyInstance, deps: { db: kb.Db; cfg: AskConfig; requireUser: (req: FastifyRequest) => Promise<void>; userSub: (req: FastifyRequest) => string; contextFor?: (req: FastifyRequest) => Promise<string | undefined> }) {
  const { db, cfg, requireUser, userSub, contextFor } = deps
  const client = cfg.anthropicKey ? new Anthropic({ apiKey: cfg.anthropicKey, maxRetries: 2, timeout: 5 * 60_000 }) : null
  const fail = (reply: FastifyReply, status: number, code: string, message: string) => reply.code(status).send({ error: { code, message } })

  // Everything that can be refused before the model is asked: the key, the question, the rate limit, the conversation.
  async function prepare(req: FastifyRequest) {
    if (!client) throw new AskError(503, 'ask_not_configured', 'Answering is not set up on this server (ANTHROPIC_API_KEY).')
    const body = AskBody.safeParse(req.body)
    if (!body.success) throw new AskError(422, 'invalid_payload', body.error.issues.map((i) => i.message).join('; '))
    const sub = userSub(req)

    // Counted from the stored messages: no extra state, survives restarts, works across instances.
    const recent = await db.query<{ n: number }>(
      `select count(*)::int as n from kb_message m join kb_conversation c on c.id = m.conversation_id
        where c.user_sub = $1 and m.created_at > now() - interval '1 hour'`,
      [sub],
    )
    if (recent.rows[0].n >= cfg.askPerHour) {
      throw new AskError(429, 'too_many_questions', `That is ${cfg.askPerHour} questions in the last hour. Try again in a few minutes.`)
    }

    let conversationId = body.data.conversationId
    let history: { question: string; answer: string }[] = []
    if (conversationId) {
      const own = await db.query('select 1 from kb_conversation where id = $1 and user_sub = $2', [conversationId, sub])
      if (!own.rowCount) throw new AskError(404, 'no_such_conversation', 'That conversation was not found.')
      // The last few exchanges are enough context for a follow-up.
      const prior = await db.query<{ question: string; answer: string }>(
        `select question, answer from kb_message where conversation_id = $1 and answer is not null order by created_at desc limit 6`,
        [conversationId],
      )
      history = prior.rows.reverse()
    } else {
      conversationId = (await db.query<{ id: string }>('insert into kb_conversation (user_sub) values ($1) returning id', [sub])).rows[0].id
    }
    const contextBlock = contextFor ? await contextFor(req) : undefined
    return { question: body.data.question, conversationId: conversationId!, history, detail: body.data.detail, contextBlock }
  }

  // Ask the model, keep the exchange, and build the response. A failure is kept on record for review, then rethrown.
  async function execute(p: Awaited<ReturnType<typeof prepare>>, opts: { onProgress?: (t: string) => void; signal?: AbortSignal }) {
    const started = Date.now()
    try {
      const result = await answer(client!, db, cfg, p.question, p.history, { ...opts, detail: p.detail, contextBlock: p.contextBlock })
      const durationMs = Date.now() - started
      const citations: AskCitation[] = citationsOf(result.answer)
      const saved = await db.query<{ id: string }>(
        `insert into kb_message (conversation_id, question, answer, citations, tool_calls, model, input_tokens, output_tokens, duration_ms, search_ms, detail, reads)
         values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) returning id`,
        [p.conversationId, p.question, result.answer, JSON.stringify(citations), result.toolCalls, result.model, result.inputTokens, result.outputTokens, durationMs, result.searchMs, p.detail, JSON.stringify(result.reads)],
      )
      return {
        conversationId: p.conversationId,
        messageId: Number(saved.rows[0].id),
        answer: result.answer,
        citations,
        toolCalls: result.toolCalls,
        sources: await kb.sources(db), // when each repo was read, so a reader can judge how current the answer is
        durationMs,
        searchMs: result.searchMs,
        detail: p.detail,
      }
    } catch (e) {
      await db
        .query('insert into kb_message (conversation_id, question, error, duration_ms, detail) values ($1, $2, $3, $4, $5)', [
          p.conversationId,
          p.question,
          opts.signal?.aborted ? 'cancelled by the asker' : (e as Error).message,
          Date.now() - started,
          p.detail,
        ])
        .catch(() => {})
      throw e
    }
  }

  // POST /api/v1/ask answers in one JSON response. With ?stream=1 it answers as newline-delimited JSON instead: a
  // {"type":"progress","text":…} line for each lookup, then one {"type":"result",…} or {"type":"error",…}. A question
  // can take a minute, and the page shows what is being looked at meanwhile.
  app.post('/api/v1/ask', { onRequest: requireUser }, async (req, reply) => {
    const stream = (req.query as { stream?: string }).stream === '1'
    let prepared: Awaited<ReturnType<typeof prepare>>
    try {
      prepared = await prepare(req)
    } catch (e) {
      if (!(e instanceof AskError)) throw e
      if (e.status === 429) reply.header('retry-after', '600')
      return fail(reply, e.status, e.code, e.message)
    }

    if (!stream) {
      try {
        const out = await execute(prepared, {})
        reply.header('cache-control', 'no-store')
        return out
      } catch (e) {
        const d = describeError(e, (x) => req.log.error(x))
        return fail(reply, d.status, d.code, d.message)
      }
    }

    // Past this point the status is already sent, so a failure is a line, not an HTTP error.
    reply.hijack()
    const raw = reply.raw
    raw.writeHead(200, { 'content-type': 'application/x-ndjson; charset=utf-8', 'cache-control': 'no-store', 'x-accel-buffering': 'no' })
    const send = (o: unknown) => !raw.writableEnded && raw.write(`${JSON.stringify(o)}\n`)
    // The person closed the tab: stop paying for an answer nobody will read.
    const gone = new AbortController()
    raw.on('close', () => gone.abort())
    try {
      send({ type: 'progress', text: 'Understanding the question' })
      send({ type: 'result', ...(await execute(prepared, { onProgress: (text) => send({ type: 'progress', text }), signal: gone.signal })) })
    } catch (e) {
      if (!gone.signal.aborted) {
        const d = describeError(e, (x) => req.log.error(x))
        send({ type: 'error', code: d.code, message: d.message })
      }
    } finally {
      raw.end()
    }
    return reply
  })

  // Thumbs up or down on an answer, by the person who asked it.
  app.post('/api/v1/ask/:messageId/feedback', { onRequest: requireUser }, async (req, reply) => {
    const { messageId } = req.params as { messageId: string }
    const v = (req.body as { feedback?: unknown } | null)?.feedback
    if (v !== 1 && v !== -1 && v !== null) return fail(reply, 422, 'invalid_payload', 'Send {"feedback": 1}, {"feedback": -1} or {"feedback": null}.')
    if (!/^\d+$/.test(messageId)) return fail(reply, 404, 'not_found', 'No such answer.')
    const r = await db.query(
      `update kb_message m set feedback = $3 from kb_conversation c
        where m.id = $1 and c.id = m.conversation_id and c.user_sub = $2`,
      [messageId, userSub(req), v],
    )
    return r.rowCount ? reply.code(204).send() : fail(reply, 404, 'not_found', 'No such answer.')
  })

  // The lines around a citation, for the page's source panel: every citation opens the lines it cites.
  app.get('/api/v1/knowledge/file', { onRequest: requireUser }, async (req, reply) => {
    const q = req.query as { repo?: string; path?: string; line?: string }
    if (!q.repo || !q.path) return fail(reply, 422, 'invalid_payload', 'Send repo and path.')
    const line = q.line && /^\d+$/.test(q.line) ? Number(q.line) : null
    const out = await kb.fileExcerpt(db, q.repo, q.path, line)
    if (!out) return fail(reply, 404, 'not_found', 'That file is not in the knowledge base. It may be excluded (secrets, customer configuration) or no longer exist.')
    reply.header('cache-control', 'no-store')
    return out
  })

  // When the knowledge was last refreshed, for the page's footer. (With parallel refresh jobs, aggregate the run:
  // refresh-workflow.md section 9.)
  app.get('/api/v1/ask/status', { onRequest: requireUser }, async (_req, reply) => {
    reply.header('cache-control', 'no-store')
    const run = await db.query<{ status: string; finished_at: Date | null }>('select status, finished_at from kb_index_run order by id desc limit 1')
    return { enabled: client !== null, sources: await kb.sources(db), lastRun: run.rows[0] ? { status: run.rows[0].status, finishedAt: run.rows[0].finished_at?.toISOString() ?? null } : null }
  })
}
```

## 8. Scripted-model tests

No network and no database: a scripted model and a database that answers every lookup with one file. These pin the
behaviours that broke once or were designed on purpose: the cap, a failed lookup, history order, the cached block
identical across styles, the empty reply, the files opened.

```ts
// file: ask.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type Anthropic from '@anthropic-ai/sdk'
import { answer, citationsOf, describeLookup } from './ask.ts'
import { splitConfidence, splitFollowUps } from './answer-text.ts'
import type { Db } from './kb.ts'

type Script = { stop_reason: string; content: unknown[]; usage?: Record<string, number> }

function fakeClient(script: Script[], seen: unknown[] = []) {
  let i = 0
  return {
    seen,
    beta: {
      messages: {
        create: async (params: unknown) => {
          seen.push(structuredClone(params))
          const r = script[Math.min(i++, script.length - 1)]
          return { model: 'claude-opus-5-5', usage: { input_tokens: 10, output_tokens: 5, ...r.usage }, ...r }
        },
      },
    },
  } as unknown as Anthropic & { seen: unknown[] }
}

const fakeDb = {
  connect: async () => ({
    query: async (sql: string) =>
      /^(begin|set local|commit|rollback)/.test(sql)
        ? { rows: [] }
        : { rows: [{ repo: 'dispatch', sha: 'abcdef123456', path: 'a.py', kind: 'code', content: 'x = 1\nretry limit check\n' }] },
    release() {},
  }),
} as unknown as Db

const cfg = { askModel: 'claude-opus-5-5', askEffort: 'high', askMaxToolCalls: 2 }

const toolUse = (id: string, name: string, input: unknown) => ({ stop_reason: 'tool_use', content: [{ type: 'tool_use', id, name, input }] })
const final = (text: string) => ({ stop_reason: 'end_turn', content: [{ type: 'text', text }] })

test('citations are read from the answer, once each', () => {
  const text = 'Yes [orders-api@1a2b3c4:src/orders/confirm.ts:61] and again [orders-api@1a2b3c4:src/orders/confirm.ts:61], also [platform/worker@5d6e7f8:app/x.py] and [billing@9a0b1c2:src/A.cs:10-20]. Not a citation [see above].'
  assert.deepEqual(citationsOf(text), [
    { repo: 'orders-api', sha: '1a2b3c4', path: 'src/orders/confirm.ts', line: 61 },
    { repo: 'platform/worker', sha: '5d6e7f8', path: 'app/x.py', line: null },
    { repo: 'billing', sha: '9a0b1c2', path: 'src/A.cs', line: 10 },
  ])
})

test("runs the model's lookups, then returns its answer", async () => {
  const client = fakeClient([toolUse('t1', 'search', { query: 'retry limit' }), toolUse('t2', 'read_file', { repo: 'dispatch', path: 'a.py' }), final('Short answer [dispatch@abcdef1:a.py:2]')])
  const r = await answer(client, fakeDb, cfg, 'Can it?', [])
  assert.equal(r.answer, 'Short answer [dispatch@abcdef1:a.py:2]')
  assert.equal(r.toolCalls, 2)
  assert.equal(r.inputTokens, 30)
  // The second request carries the first lookup's result back to the model.
  const second = client.seen[1] as { messages: { role: string; content: unknown }[] }
  assert.equal(second.messages.at(-1)?.role, 'user')
  assert.match(JSON.stringify(second.messages.at(-1)), /tool_result/)
  assert.match(JSON.stringify(second.messages.at(-1)), /dispatch@abcdef1:a\.py/)
})

test('stops lookups at the cap and asks for an answer', async () => {
  // The model keeps asking for lookups; the third is refused and the request after it forbids tools.
  const client = fakeClient([toolUse('a', 'repo_map', {}), toolUse('b', 'repo_map', {}), toolUse('c', 'repo_map', {}), final('Best effort answer.')])
  const r = await answer(client, fakeDb, cfg, 'Q', [])
  assert.equal(r.toolCalls, 2)
  assert.equal(r.answer, 'Best effort answer.')
  const last = client.seen.at(-1) as { tool_choice: { type: string } }
  assert.equal(last.tool_choice.type, 'none')
  assert.match(JSON.stringify(client.seen.at(-1)), /Lookup budget used up/)
})

test('a failed lookup is told to the model, not thrown', async () => {
  const brokenDb = { connect: async () => { throw new Error('db down') } } as unknown as Db
  const client = fakeClient([toolUse('a', 'grep', { text: 'retry_limit' }), final('I could not find this in the indexed code.')])
  const r = await answer(client, brokenDb, cfg, 'Q', [])
  assert.match(r.answer, /could not find/)
  assert.match(JSON.stringify(client.seen[1]), /lookup failed: db down/)
})

test('earlier exchanges of the conversation lead the request; refusals and cut-offs are said plainly', async () => {
  const client = fakeClient([{ stop_reason: 'refusal', content: [] }])
  const r = await answer(client, fakeDb, cfg, 'Follow-up?', [{ question: 'First?', answer: 'First answer.' }])
  assert.equal(r.answer, 'I could not answer that question.')
  const sent = client.seen[0] as { messages: { content: string | { text: string }[] }[]; system: { cache_control: unknown }[]; fallbacks: string }
  assert.deepEqual(sent.messages.slice(0, 2).map((m) => m.content), ['First?', 'First answer.'])
  const asked = sent.messages[2].content as { text: string }[]
  assert.equal(asked[0].text, 'Follow-up?')
  assert.match(asked[1].text, /^<search query="the question's keywords">\ndispatch@abcdef1:a\.py/, 'the question was searched before the model was asked')
  assert.deepEqual(sent.system[0].cache_control, { type: 'ephemeral' })
  assert.equal(sent.fallbacks, 'default')

  const cut = fakeClient([{ stop_reason: 'max_tokens', content: [{ type: 'text', text: 'Partial' }] }])
  assert.match((await answer(cut, fakeDb, cfg, 'Q', [])).answer, /^Partial\n\n\(The answer was cut off/)
})

test('progress lines say what is being looked at', () => {
  assert.equal(describeLookup('search', { query: 'retry limit', repo: 'dispatch' }), 'Searching dispatch for “retry limit”')
  assert.equal(describeLookup('grep', { text: 'x_y' }), 'Looking for “x_y”')
  assert.equal(describeLookup('read_file', { repo: 'dispatch', path: 'a.py' }), 'Reading how dispatch does it')
  assert.equal(describeLookup('list_dir', { repo: 'dispatch' }), 'Looking around dispatch')
})

test('an answer reports the files the model opened', async () => {
  const client = fakeClient([toolUse('a', 'read_file', { repo: 'dispatch', path: 'a.py' }), toolUse('b', 'read_file', { repo: 'dispatch', path: 'a.py' }), final('Done.')])
  const heard: string[] = []
  const r = await answer(client, fakeDb, cfg, 'Q', [], { onProgress: (t) => heard.push(t) })
  assert.deepEqual(r.reads, ['dispatch:a.py'])
  assert.deepEqual(heard, ['Searching every system for the question', 'Reading how dispatch does it', 'Reading how dispatch does it'])
})

test('the answer style reaches the model after the cached rules, and search time is counted', async () => {
  const seen: unknown[] = []
  const r = await answer(fakeClient([toolUse('t1', 'search', { query: 'retry limit' }), final('Done')], seen), fakeDb, cfg, 'Can it?', [], { detail: 'technical' })
  const system = (seen[0] as { system: { text: string; cache_control?: unknown }[] }).system
  assert.equal(system.length, 2)
  assert.ok(system[0].cache_control, 'the rules are cached')
  assert.match(system[1].text, /^Answer style: Technical/)
  assert.equal(typeof r.searchMs, 'number')

  const plain: unknown[] = []
  await answer(fakeClient([final('Done')], plain), fakeDb, cfg, 'Can it?', [])
  const plainSystem = (plain[0] as { system: { text: string }[] }).system
  assert.match(plainSystem[1].text, /^Answer style: Plain/)
  assert.equal(plainSystem[0].text, system[0].text, 'the cached rules are the same in both styles')
})

test('an empty reply that ends the turn is asked once to continue, then answered', async () => {
  const seen: unknown[] = []
  const empty = { stop_reason: 'end_turn', content: [] }
  const r = await answer(fakeClient([toolUse('t1', 'read_file', { repo: 'dispatch', path: 'a.py' }), empty, final('The job goes to the queue.')], seen), fakeDb, cfg, 'Show me the job flow', [])
  assert.equal(r.answer, 'The job goes to the queue.')
  assert.equal(seen.length, 3)
  const last = seen[2] as { messages: { role: string; content: unknown }[]; tool_choice: { type: string } }
  assert.deepEqual(last.messages.at(-1), { role: 'user', content: 'Please continue: write the answer now, from what you have read.' })
  assert.equal(last.tool_choice.type, 'none', 'answer from what was read')
})

test('the confidence line is taken out of the answer and read', () => {
  assert.deepEqual(splitConfidence('It waits.\n\nConfidence: High — read the code that decides it.'), { text: 'It waits.', confidence: { level: 'high', why: 'read the code that decides it' } })
  assert.deepEqual(splitConfidence('It waits.\n**Confidence:** medium - depends on a deployment setting\n'), { text: 'It waits.', confidence: { level: 'medium', why: 'depends on a deployment setting' } })
  assert.deepEqual(splitConfidence('Confidence: Low'), { text: '', confidence: { level: 'low', why: '' } })
  assert.equal(splitConfidence('No label here. Confidence matters.').confidence, null)
})

test('suggested follow-ups are taken out of the answer, before the confidence line', () => {
  const text = 'It waits at the gateway.\n\nFollow-ups: What happens if the device declines? | "Which setting sets the timeout?" | 3. How does the order service hear it arrived?\nConfidence: High — read the handler'
  const c = splitConfidence(text)
  assert.equal(c.confidence?.level, 'high')
  assert.deepEqual(splitFollowUps(c.text), {
    text: 'It waits at the gateway.',
    followUps: ['What happens if the device declines?', 'Which setting sets the timeout?', 'How does the order service hear it arrived?'],
  })
  assert.deepEqual(splitFollowUps('No suggestions here.'), { text: 'No suggestions here.', followUps: [] })
  assert.equal(splitFollowUps('**Suggested follow-ups:** a | b | Is it per deployment?').followUps.length, 1, 'too-short ones are dropped')
})
```

## 9. Runtime settings (E11, optional)

When behaviour is chosen at runtime by settings each deployment keeps (feature flags, algorithm versions,
thresholds), the code holds every branch and an answer that does not know the values may describe one the
deployment does not run. The source pastes each deployment's settings into a table, passes them as the third
system block (`contextBlock`) with long values summarised ("a table of 38 entries"), adds a tool that reads one
full value, stores which deployment a question was asked for (`kb_message.site`), and redacts secret-looking keys
and values on save. Keep that block after the cached rules and the style, so it never breaks the cache.

Wiring it takes two hooks, both optional: `registerAsk(..., { contextFor })` builds the block for a request, and
`secondOpinion(..., { contextFor })` (evals.md section 6) rebuilds it for a stored message, so the deeper re-run
sees the same settings the original answer had. For the second one, store the key the block was built from with
the message (the source's `kb_message.site text` column) and read it back in the hook.

## Pitfalls

- **P63. Search the question before the first model call and send the results with it.** The first turn can read
  or answer instead of only deciding what to search: one full model round fewer.
- **P64. Cache the rules block; put anything that varies per question (style, runtime settings) in later system
  blocks.** Switching style keeps the cache.
- **P65. Keep tools declared on the final call and stop them with `tool_choice: none`.** Removing tools changes the
  cached prefix.
- **P66. Enforce the lookup budget twice: answer over-budget tool calls with an `is_error` result that says
  "answer now", then make the next call with tools off.** Every `tool_use` needs a `tool_result`.
- **P67. An empty reply with `end_turn` gets ONE "please continue: write the answer now" turn, tools off.** Seen in
  production: the model ended its turn with no text right after a lookup. Log what the empty reply held.
- **P68. Tools return text on every path, including timeouts and bad arguments.** The model corrects itself; the
  request does not fail.
- **P69. Citations are a strict text format parsed afterwards: `[repo@sha:path:line]`, the sha from the tool
  output, a line actually read.** Repo names may contain `/`; ranges keep the first line; duplicates collapse.
- **P70. Record the files the model OPENED, separately from the ones it cited.** Evals and reviewers must tell
  "never found it" from "found it, did not cite it".
- **P71. Store failures too, and mark cancellations distinctly.** Failed questions are review material; a closed
  tab is not.
- **P72. Stream NDJSON progress and abort the model call when the client disconnects; disable proxy buffering.** A
  question takes up to a minute; nobody should pay for an answer nobody reads.
- **P73. Count cache-read and cache-creation tokens into the stored input tokens.** `usage.input_tokens` alone
  under-reports once caching works.
- **P74. Rate-limit per person from the stored messages, and return 503 (feature off) when no key is set while the
  rest of the API runs.**
- **P74a. Send only the last 6 exchanges as history.** Enough for a follow-up; bounded cost.
- **P74b. Make the model end with a parseable confidence line, and strip it (and any follow-up line) before
  judging or displaying.**

## Proven at

14 lookups per question by default; answers usually take 15-45 s, almost all of it model rounds (one search is
~150 ms). Worked example: 43 s, 14 lookups, 29 sources in the answer. `max_tokens` 16,000 per call, effort `high`.
