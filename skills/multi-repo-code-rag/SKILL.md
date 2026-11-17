---
name: multi-repo-code-rag
description: Build a code knowledge base that answers questions about several git repositories with cited sources - index repos into Postgres + pgvector (files cut into ~60-line sections, each with a word index and a local code embedding), extract cross-system contracts (which file of one system calls which route of another), refresh it on a schedule (self-hosted runner, one job per repo in parallel, then one contracts pass), answer with Claude over hybrid lexical + vector retrieval in a capped tool loop, and measure it with golden questions, a free search eval and an answer review queue. Use when asked to "index our repos", build "ask the codebase" / "chat with our code" / a code RAG or code search over pgvector, add hybrid search or embeddings to a code index, find which service calls which endpoint across repos, schedule a weekly re-index, or add golden questions / retrieval evals to a code Q&A bot. To investigate or review a RAG layer that already exists, use rag-layer-audit instead.
---

# Multi-repo code RAG

Builds a knowledge base over several repositories so people who don't read the code get short, cited answers
(`[repo@sha:path:line]`, each opening the lines it cites), and engineers get a search that follows a call from one
system into another. Proven on Node 22 (type-stripped TypeScript, no build) · pg 8 · PostgreSQL 17 (RDS) +
pgvector 0.8 + pg_trgm · `@huggingface/transformers` 4 on onnxruntime-node 1.30 · `jinaai/jina-embeddings-v2-base-code`
q8, 768 dims · `@anthropic-ai/sdk` 1.8, `claude-opus-5-5` at effort high · GitHub Actions on a self-hosted runner.
Proven at 8 repos, ~6,100 files, ~19,000 sections, ~170 contracts; one search ~150 ms; answers 15-45 s. The blocks
are TypeScript + Postgres; the contract (tables, citation format, blob-SHA incrementality) carries to any stack.

## Moving parts

1. **Tables**: repo, file (full text, keyed by git blob SHA), section (word index + embedding), contract, index run,
   conversation/message, golden. -> `references/schema.md`
2. **Indexer**: reads git objects at a ref (never a checkout), filters to an allowlist, scrubs secrets, upserts
   changed files in one transaction per repo, then cuts and embeds only stale files, committing every 40 files.
   -> `references/indexer.md`
3. **Search**: two candidate lists (rare-word-weighted full text; cosine over HNSW), fused per file with RRF k=10,
   a named-system boost and a connector lift; plus exact `grep` (trigram), `read_file`, `list_dir`, `repo_map`.
   -> `references/search.md`
4. **Contracts**: routes each system serves x URL paths each system uses -> `route` and `shared` links, rebuilt
   whole after every refresh. Only with 2+ systems. -> `references/contracts.md`
5. **Refresh**: scheduled workflow: plan -> one index job per repo (bounded parallelism) -> one links job
   (contracts + free golden check). -> `references/refresh-workflow.md`
6. **Answering**: the question pre-searched as keywords, cached rules + a style block, a capped tool loop,
   citations parsed from the text, an NDJSON progress stream, every exchange stored. -> `references/answering.md`
7. **Evals**: golden questions (expected files + phrases), a free search eval with a fusion grid, a paid answer
   eval (PASS / MISS / FAIL), a review queue that turns real questions into golden ones, a second opinion + judge.
   -> `references/evals.md`

Load only the reference file for the stage in front of you; each ends with its full **Pitfalls** list.

## Workflow

0. **Look first.** Grep the target repo for an existing index or search (`pgvector`, `tsvector`, `embedding`,
   `to_tsquery`). If one exists and the ask is "explain / review it", hand over to `rag-layer-audit`. Done when you
   can name the database, the migration mechanism, the API framework and the CI runner the repo already uses.
1. **Fill the extension points** below with the user: repos with branches, system names and aliases, which server
   frameworks serve routes. Done when `kb-repos.json` exists and every repo has a branch and a human name.
2. **Extensions before code.** A privileged database user creates `pg_trgm` and `vector` BEFORE the migration
   ships. Done when `\dx` lists both (or the user accepts word-only search for now).
3. **Schema + migration runner** (`schema.md`). Done when migrations apply twice in a row with no change and two
   processes started together do not both apply one.
4. **Indexer, files only** (`indexer.md` sections 1-5). `dry-run` on one small repo, then for real. Done when a
   second run prints `+0 ~0 -0` and a human has read the blocked/redacted counts.
5. **Sections + embeddings** (`indexer.md` sections 6-8). Done when a killed run resumes where it stopped and
   `select count(*) from kb_chunk where embedding is null` is 0 (skip that check when running word-only).
6. **Search** (`search.md`). Done when `eval:search` prints found@5 / found@12 for at least 8 seed golden questions
   and the numbers are written down as the baseline.
7. **Contracts** (`contracts.md`), only with 2+ systems. Done when every hop the team can name is listed as found or
   not found, with the reason for each miss.
8. **Answering** (`answering.md`). Done when the scripted-model tests pass (cap reached, failed lookup, empty reply,
   refusal, cut-off) and one real question returns citations that open the cited lines.
9. **Refresh workflow** (`refresh-workflow.md`). Done when a manual run for one repo is green, a full run is green,
   and a deliberately failed repo turns the run red while its previous index stays searchable.
10. **Evals + review loop** (`evals.md`). Done when the free golden check runs in the workflow and the paid eval
    has one recorded pass rate.
11. Offer `rag-layer-audit` for an independent, source-backed review of what was built.

## Principles

- **Read git objects, write nothing.** `ls-tree` + `cat-file --batch` at a ref: no checkout, no working tree touched,
  a person's open branch is safe.
- **The blob SHA is the change detector, twice.** File rows compare it with the tree; section rows carry the blob
  SHA they were cut from. That one column makes every stage incremental and resumable.
- **A failed repo keeps its previous index and the run goes red.** One transaction per repo for files; small commits
  for sections (they are derived, so partial progress is safe).
- **Rank sections, answer with files.** A 2,000-line file that says "battery" once outranks the 40 lines deciding it.
- **Two lists, fused by rank, never by score.** Rare words outweigh common ones; a top hit in one list beats files
  middling in both (k=10, not 60).
- **Word search is the floor; meaning search degrades to it.** No pgvector, no model, a model that fails to load:
  search still answers, and says so in the log once.
- **The embedding model runs on your own machines.** Code leaves only as the excerpts the answering model reads.
- **Code outranks docs; "I couldn't find this" outranks a guess.** Every claim carries `[repo@sha:path:line]`.
- **A lookup that fails is information for the model, not an exception.** Tools return text, always.
- **Measure search for free before spending tokens.** Every ranking change is a row of found@5 / found@12, the ones
  that did not help included.
- **Golden questions test; they never feed answers.**

## Pitfalls (each already paid for once; the full list lives in the reference files)

- **P1** A privileged user creates `pg_trgm` and `vector` before the deploy: the app user may not. (schema.md)
- **P2** The required extension fails with the command to run; the optional one is a notice. (schema.md)
- **P9** Read `ls-tree` / `cat-file --batch` at a ref, never check out: working trees stay untouched. (indexer.md)
- **P14** One transaction per repo, exit non-zero on any failure: a red run, never a half-updated base. (indexer.md)
- **P17** Skip files holding real credentials, redact likely passwords, log only the rule name. (indexer.md)
- **P18** The file filter is an allowlist: env files, customer settings, seeds, lockfiles never enter. (indexer.md)
- **P24** Commit sections every 40 files and pick work by blob SHA: a killed first run resumes. (indexer.md)
- **P27** `set local hnsw.ef_search` to at least the LIMIT: pgvector silently returns at most 40 rows. (search.md)
- **P29** RRF k=10, not 60: with 60 a top hit in one list loses to files middling in both. (search.md)
- **P33** Expand short system aliases, boost the named systems' repos: two-letter names match everything. (search.md)
- **P41** Build contracts once, after all repos: the rebuild deletes the whole table. (contracts.md)
- **P45** A `shared` link needs HTTP code on both sides and exactly two systems. (contracts.md)
- **P47** Embed on a self-hosted runner with real cores: 2 hosted cores managed ~1 section/s. (refresh-workflow.md)
- **P58** Read-only repo-scoped token; DB secret in an environment with no required reviewers. (refresh-workflow.md)

## Extension points

| ID | Fill in | Lives in |
|---|---|---|
| E1, E2 | Repo list (`name`, `repository`, `branch`, `dir`, `ciDir?`, `subdir?`); the branch production runs from, checked not stale | `kb-repos.json` (indexer.md 1) |
| E3, E4 | File filter lists and size cap; secret BLOCK / REDACT rules (optionally gitleaks in front) | `filter.ts`, `secrets.ts` (indexer.md 3-4) |
| E5 | Declaration regex for the indexed languages; section sizes | `kb-chunks.ts` (indexer.md 6) |
| E6 | One route extractor per server framework; client-call regex; prefix and third-party sets | `kb-contracts.ts` (contracts.md 3-4) |
| E7 | System names (two repos may share one), alias expansion, question-to-repos patterns; empty for one system | `systems.ts` (indexer.md 1) |
| E8 | Assistant name, audience, architecture paragraph, styles, diagrams / follow-ups / confidence | `ask.ts` (answering.md 2) |
| E9, E10 | Database reach from the runner (direct or tunnel); runner label, `max-parallel`, cron, timeout | workflow (refresh-workflow.md 1, 4, 5) |
| E11 | Optional runtime-settings context block | answering.md 9 |
| E12 | Auth hook, per-person rate limit, who may review | `ask-http.ts`, `ask-review.ts` (answering.md 7, evals.md 5) |
| E13, E14 | Embedding model (id, dtype, dims, directory; same for passages and queries); answering model, effort, lookups | `kb-embed.ts`, `ask-config.ts` (indexer.md 7, answering.md 1) |
| E15 | 8-12 seed golden questions, at least one unanswerable | `eval/golden.json` (evals.md 1) |

Blocks marked **not yet proven in production** go beyond the source: the single-checkout workflow matrix, the
route-extractor registry, the embedding-model column, run-status rows, boundary matching in the answer eval, the
stale-section filter. Not covered: chat UI, import graph, settings UI, deploy. Review it with `rag-layer-audit`.
