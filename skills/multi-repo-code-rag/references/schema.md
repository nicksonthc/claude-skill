# Schema: tables, extensions, migration runner

Load this when creating the database side of the knowledge base: the extension guards, the DDL, the migration
runner every entry point calls, and the connection settings. The table prefix `kb_` is renamable; keep it consistent
across every block in this skill.

## 1. Extension guards (asymmetric on purpose)

`pg_trgm` is **required**: the `grep` tool's `ilike` runs on a trigram index. `vector` is **optional**: without it
word search still answers and meaning search waits. So the first fails loudly with the exact command to run, the
second only raises a notice.

```sql
-- file: migrations/001_kb.sql
-- Trigram search makes `grep`-style substring lookups of identifiers use an index. On managed Postgres (RDS, Cloud
-- SQL, Azure) the app's database user usually may not create extensions, so a privileged user creates it once,
-- BEFORE this release is deployed:
--     create extension if not exists pg_trgm;
-- If that was missed, say so plainly rather than with a bare "permission denied".
do $$
begin
  if not exists (select 1 from pg_extension where extname = 'pg_trgm') then
    begin
      create extension pg_trgm;
    exception when insufficient_privilege then
      raise exception 'The pg_trgm extension is not installed and this database user may not create it. As a privileged database user, run: create extension if not exists pg_trgm;';
    end;
  end if;
end
$$;

-- pgvector: created here when this user may. If it can't be, nothing fails: sections and word search still work,
-- and meaning search waits until a privileged user runs, once,
--     create extension if not exists vector;
-- after which the next refresh adds the embedding column (indexer prepareMeaning) and fills it.
do $$
begin
  if not exists (select 1 from pg_extension where extname = 'vector') then
    begin
      create extension vector;
    exception when others then
      raise notice 'pgvector is not available to this user (%). Word search works; meaning search waits for: create extension if not exists vector;', sqlerrm;
    end;
  end if;
end
$$;
```

## 2. Core DDL: repos, files, sections, contracts, runs

```sql
-- file: migrations/001_kb.sql (continued)
-- One row per indexed repo and branch. last_sha is the commit the files below were read at.
create table kb_repo (
  id          integer generated always as identity primary key,
  name        text not null unique, -- what citations show, e.g. orders-api, platform/worker
  branch      text not null,
  last_sha    text,
  indexed_at  timestamptz
);

-- One row per file at that commit. blob_sha is git's id of the content, so a refresh rewrites only what changed.
create table kb_file (
  repo_id   integer not null references kb_repo (id) on delete cascade,
  path      text not null,
  blob_sha  text not null,
  kind      text not null check (kind in ('code', 'test', 'doc', 'setting', 'schema')),
  language  text,
  size      integer not null,
  content   text not null,
  -- 'simple', not 'english': identifiers must not be stemmed. A word in the file's name outranks one in its text.
  tsv       tsvector generated always as (setweight(to_tsvector('simple', path), 'A') || setweight(to_tsvector('simple', content), 'D')) stored,
  primary key (repo_id, path)
);
create index kb_file_tsv on kb_file using gin (tsv);
create index kb_file_trgm on kb_file using gin (content gin_trgm_ops);
create index kb_file_kind on kb_file (repo_id, kind);

-- Sections of the indexed files, for search (indexer.md section 6): ~60 lines each, found by words (code names
-- split) and by meaning (an embedding stored with pgvector).
create table kb_chunk (
  repo_id     integer not null,
  path        text not null,
  n           integer not null, -- the section's place in its file
  blob_sha    text not null,    -- the file version the section was cut from: a changed file is cut again
  start_line  integer not null,
  end_line    integer not null,
  symbol      text,             -- the nearest class, function or heading above it
  head        text not null,    -- path and symbol, code names split: weighted up
  body        text not null,    -- the lines, lower case, with code names split
  tsv         tsvector generated always as (setweight(to_tsvector('english', head), 'A') || setweight(to_tsvector('english', body), 'D')) stored,
  primary key (repo_id, path, n),
  foreign key (repo_id, path) references kb_file (repo_id, path) on delete cascade
);
create index kb_chunk_tsv on kb_chunk using gin (tsv);

-- EMBED_DIMS numbers per section, compared by cosine distance through an HNSW index. Only when pgvector exists;
-- otherwise the indexer adds both later (prepareMeaning). 768 = EMBED_DIMS in kb-embed.ts: see P7.
do $$
begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    execute 'alter table kb_chunk add column embedding vector(768)';
    execute 'create index kb_chunk_embedding on kb_chunk using hnsw (embedding vector_cosine_ops)';
  end if;
end
$$;

-- How the systems call each other, found in the indexed code (contracts.md). Rebuilt whole after every refresh.
-- kind 'route': a URL path in from_* matches a route to_* serves; 'shared': the same URL path is in HTTP code of both.
-- key: the route ("POST /v3/orders/confirm") or the shared path ("stations/call-next").
create table kb_contract (
  id            bigint generated always as identity primary key,
  kind          text not null check (kind in ('route', 'shared')),
  from_repo_id  integer not null,
  from_path     text not null,
  from_line     integer not null,
  to_repo_id    integer not null,
  to_path       text not null,
  to_line       integer not null,
  key           text not null,
  foreign key (from_repo_id, from_path) references kb_file (repo_id, path) on delete cascade,
  foreign key (to_repo_id, to_path) references kb_file (repo_id, path) on delete cascade
);
create index kb_contract_from on kb_contract (from_repo_id, from_path);
create index kb_contract_to on kb_contract (to_repo_id, to_path);

-- One row per refresh, so the page can say when the knowledge was last updated and what changed.
-- (Parallel per-repo jobs each write their own row: see refresh-workflow.md section 9.)
create table kb_index_run (
  id           bigint generated always as identity primary key,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  status       text not null default 'running' check (status in ('running', 'ok', 'failed')),
  repos        jsonb not null default '[]', -- [{name, branch, sha, added, changed, removed, skipped, ...}]
  error        text
);
```

## 3. Ask DDL: conversations, messages, golden questions

In the source these columns arrived over five migrations; folded into one here.

```sql
-- file: migrations/001_kb.sql (continued)
-- Questions and answers, for review and for the thumbs up/down.
create table kb_conversation (
  id          uuid primary key default gen_random_uuid(),
  user_sub    text not null,
  created_at  timestamptz not null default now()
);

create table kb_message (
  id               bigint generated always as identity primary key,
  conversation_id  uuid not null references kb_conversation (id) on delete cascade,
  created_at       timestamptz not null default now(),
  question         text not null,
  answer           text,                        -- null when the question failed
  citations        jsonb not null default '[]', -- [{repo, sha, path, line}] parsed from the answer
  tool_calls       integer not null default 0,
  model            text,                        -- the model that answered (a fallback may differ from the one asked)
  input_tokens     integer,                     -- including cache reads and cache writes (P73)
  output_tokens    integer,
  error            text,                        -- what went wrong; 'cancelled by the asker' for a closed tab
  feedback         smallint check (feedback in (-1, 1)),
  -- duration_ms: question reaching the model to the answer (or the failure); search_ms: the part spent in the search
  -- tool, so the time a meaning search adds is measured, not guessed.
  duration_ms      integer,
  search_ms        integer,
  -- the answer style the asker chose (answering.md section 2)
  detail           text not null default 'plain' check (detail in ('plain', 'technical')),
  -- the files the model OPENED besides the ones it cited: "never found it" vs "found it, didn't cite it" (P70)
  reads            jsonb not null default '[]',
  -- an owner's decision (null: not reviewed yet) and their reading of what went wrong (evals.md section 5)
  review           text check (review in ('golden', 'skipped')),
  review_cause     text check (review_cause in ('search_missed', 'cannot_read', 'wrong_answer', 'not_in_code', 'fine')),
  -- a deeper re-run and a judge's comparison (evals.md section 6): {status, verdict, score, summary, ...}
  second_opinion   jsonb
  -- optional (E11): site text, the runtime-settings context the question was asked for
);
create index kb_message_conversation on kb_message (conversation_id, created_at);
-- the review queue holds failed questions too (they have an error and no answer)
create index kb_message_unreviewed on kb_message (created_at desc) where review is null;

-- Approved golden questions, with the files a right answer must use. `golden:pull` copies them into
-- eval/golden.json, which the evals read.
create table kb_golden (
  id           bigint generated always as identity primary key,
  question     text not null,
  expect       text[] not null default '{}', -- file paths (repo:path) a right answer reads or cites
  mention      text[] not null default '{}', -- regular expressions the answer must match
  not_found    boolean not null default false, -- the code holds nothing on this: the answer must say so
  status       text not null default 'approved' check (status in ('approved', 'retired')),
  message_id   bigint references kb_message (id) on delete set null,
  note         text,
  reviewed_by  text,
  reviewed_at  timestamptz not null default now(),
  check (not_found or cardinality(expect) > 0)
);
```

## 4. Migration runner

Every entry point calls it: the API at start, the indexer, and the standalone contracts script. A scheduled refresh
therefore works on a database the new release has not been deployed to yet, and parallel index jobs never apply
the same file twice (P5).

```ts
// file: db.ts
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import pg from 'pg'
import { databaseConfig } from './config.ts'

export function createPool() {
  return new pg.Pool(databaseConfig())
}

const MIGRATIONS = fileURLToPath(new URL('../migrations/', import.meta.url))
// Any constant works; it only has to be the same for every instance, so two starting at once don't
// both apply the same migration.
const LOCK = 72_017_431

// Applies migrations/*.sql in name order, each in its own transaction, recording them in schema_migrations.
export async function migrate(pool: pg.Pool, log: (line: string) => void = console.log) {
  const client = await pool.connect()
  try {
    await client.query('select pg_advisory_lock($1)', [LOCK])
    await client.query('create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())')
    const done = new Set((await client.query<{ name: string }>('select name from schema_migrations')).rows.map((r) => r.name))
    const files = readdirSync(MIGRATIONS).filter((f) => f.endsWith('.sql')).sort()
    let applied = 0
    for (const f of files) {
      if (done.has(f)) continue
      await client.query('begin')
      try {
        await client.query(readFileSync(MIGRATIONS + f, 'utf8'))
        await client.query('insert into schema_migrations (name) values ($1)', [f])
        await client.query('commit')
      } catch (e) {
        await client.query('rollback')
        throw new Error(`Migration ${f} failed: ${(e as Error).message}`)
      }
      log(`applied ${f}`)
      applied++
    }
    if (!applied) log(`database is up to date (${files.length} migrations)`)
  } finally {
    await client.query('select pg_advisory_unlock($1)', [LOCK]).catch(() => {})
    client.release()
  }
}
```

If the target repo already has a migration tool (Prisma, Flyway, Alembic, Knex), use it, but keep the two
properties: an advisory lock, and every entry point (including the indexer) runs it.

## 5. Database config

```ts
// file: config.ts
import { readFileSync } from 'node:fs'

export type DbSsl = 'off' | 'require' | 'verify-full'

export function databaseConfig() {
  const url = process.env.DATABASE_URL?.trim()
  if (!url) throw new Error('DATABASE_URL is not set.')
  if (/[?&]sslmode=/.test(url)) {
    // node-postgres lets sslmode in the URL override the ssl options below, which silently drops the CA.
    throw new Error('Remove sslmode from DATABASE_URL and set DATABASE_SSL instead.')
  }
  const ssl = (process.env.DATABASE_SSL?.trim() || 'off') as DbSsl
  if (!['off', 'require', 'verify-full'].includes(ssl)) throw new Error(`DATABASE_SSL must be off, require or verify-full, got "${ssl}".`)
  const caPath = process.env.DATABASE_SSL_CA?.trim()
  if (ssl === 'verify-full' && !caPath) throw new Error('DATABASE_SSL=verify-full needs DATABASE_SSL_CA (the provider CA bundle).')
  return {
    connectionString: url,
    ssl:
      ssl === 'off'
        ? undefined
        : ssl === 'require'
          ? { rejectUnauthorized: false } // encrypted, not name-checked (a tunnel to 127.0.0.1 needs this)
          : { rejectUnauthorized: true, ca: readFileSync(caPath!, 'utf8') },
    max: poolMax(),
  }
}

// Empty means the default; anything else must be a whole number of at least 1 (0 would make every query wait forever).
function poolMax() {
  const raw = process.env.DATABASE_POOL_MAX?.trim()
  const n = raw ? Number(raw) : 10
  if (!Number.isInteger(n) || n < 1) throw new Error(`DATABASE_POOL_MAX must be a whole number of at least 1, got "${raw}".`)
  return n
}
```

The indexer and the contracts script use the same function with `max: 2`, so one `.env` serves all three.

## 6. Why two text-search configs

- `kb_file.tsv` uses `simple`: it serves the whole-file fallback search and must match identifiers exactly
  (`charging_station` is not stemmed to `charg`).
- `kb_chunk.tsv` uses `english`: `head` and `body` already carry split, lower-cased identifiers
  (`lowBatteryThreshold` -> `low battery threshold`), so stemming helps ("charging" finds "charge") and the raw
  identifier is still present for exact matches.
- Keep the file size cap (`MAX_BYTES` 300 KB in `filter.ts`). Postgres caps one `tsvector` at 1 MB; the cap keeps
  whole files under it in practice. (Inferred relationship; the source does not state it.)

## 7. Embedding model identity (not yet proven in production)

The source stores no model identity with the vectors. Changing the model or its quantisation leaves old vectors
that look valid (same dimension) and silently degrade meaning search. This is exactly what `rag-layer-audit` probe
I4 checks. Proposed addition:

```sql
-- file: migrations/002_kb_embed_model.sql   (proposed, not yet proven in production)
alter table kb_chunk add column if not exists embed_model text; -- e.g. 'jinaai/jina-embeddings-v2-base-code:q8'
-- Vectors written before this column existed came from the current model: stamp them, so the clearing query below
-- does not wipe (and force hours of re-embedding for) every section on its first run. Guarded: without pgvector
-- there is no embedding column yet.
do $$
begin
  if exists (select 1 from information_schema.columns where table_name = 'kb_chunk' and column_name = 'embedding') then
    execute $q$update kb_chunk set embed_model = 'jinaai/jina-embeddings-v2-base-code:q8' where embedding is not null and embed_model is null$q$;
  end if;
end
$$;
```

Write `embed_model = EMBED_ID` (model id + dtype) wherever `embedding` is written (`refreshSections`, `backfill`),
and at the start of each run, only when `prepareMeaning` returned true (the column exists), clear what a different
model produced, so `backfill` re-embeds it:

```sql
update kb_chunk set embedding = null where embedding is not null and embed_model is distinct from $1;
```

Query embeddings must come from the same model (P26c); if the API and the indexer can run different releases,
have the API compare its `EMBED_ID` with `select distinct embed_model from kb_chunk` at start and turn meaning
search off on a mismatch.

## Pitfalls

- **P1. Have a privileged user create `pg_trgm` and `vector` before the first deploy.** A managed-Postgres app
  user may not create extensions; the new container refuses to start after the old one is already replaced.
  The source's setup guide makes this step 0.
- **P2. Make the required extension fail with the command to run; make the optional one a notice.** A bare
  "permission denied" costs an outage of guessing; pgvector missing must not block word search.
- **P3. Create the embedding column and HNSW index conditionally, and let the indexer add them later.** The
  extension may arrive after the migration ran (`prepareMeaning` in indexer.md adds both).
- **P4. Index whole-file text with the `simple` config, sections with `english`.** Identifiers must not be stemmed
  in the file index; sections already store split identifiers, so stemming helps there (section 6).
- **P5. Run migrations under an advisory lock from every entry point (API start, indexer, contracts script).**
  Parallel index jobs and the API all migrate; the scheduled run must work before the new release is deployed.
- **P6. Reject `sslmode=` in the connection URL; take the TLS mode from a separate setting.** node-postgres lets
  the URL's sslmode override the `ssl` object and silently drops the CA.
- **P7. The vector dimension lives in three places (the migration, the indexer's `alter table`, the embedder's
  `EMBED_DIMS`): change them together and re-embed everything.** A different dimension fails inserts; a different
  model with the same dimension fails silently (section 7).
- **P8. Sections and contracts reference files with `on delete cascade`; files are UPSERTED, never
  delete-and-insert.** A deleted file takes its sections and contracts with it; an upsert keeps them until the
  re-cut, and their stale `blob_sha` marks them for it.
