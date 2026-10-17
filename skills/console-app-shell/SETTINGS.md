# console-app-shell — settings

SKILL.md moving part 6, disclosed here because only apps that add
runtime-editable settings need it. Same conventions as REFERENCE.md: `@/` is a
Vite alias to `src/`, the UI is shadcn/ui, the backend FastAPI + SQLModel
(async session), and storage keys are namespaced `app.*`.

**First decide the scope of each knob.** Does changing it alter anything for
another terminal, a record, or a printed document? Then it is a **line-wide**
setting (6a): a validated row on the server, gated by role. Does it only
change how *this* browser behaves — how often it polls, how it lays itself
out? Then it is a **terminal preference** (6b): localStorage, no save button.

---

## 6. Settings — two stores, one dialog

### 6a. Line-wide settings (server) — typed key/value table

```python
# models/setting.py
class Setting(SQLModel, table=True):
    """A runtime-editable configuration value, stored as a key/value string so
    new settings need no schema change. Read through settings_service (typed
    accessors + defaults); edited via PUT /api/settings/{key}."""
    key: str = Field(primary_key=True)
    value: str
    description: str | None = Field(default=None)
    updated_at: datetime = Field(default_factory=naive_utcnow)
```

```python
# services/settings_service.py
"""Values are strings on the wire and in the DB; callers use the typed accessors
(get_int, get_bool) which fall back to a hardcoded default when the row is
absent, so the app works even before the seed/migration inserts the row."""

SAMPLING_INTERVAL = "sampling_interval"
LOG_GET_REQUESTS = "log_get_requests"

DEFAULTS: dict[str, tuple[str, str]] = {
    # key: (default value, description shown to whoever edits it)
    SAMPLING_INTERVAL: ("20", "Every Nth item is diverted through inspection; the rest skip it."),
    LOG_GET_REQUESTS: ("false", "Also log successful GETs. Failures are always logged."),
}

_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def coerce_bool(value: str) -> bool | None:
    """Strict read of a bool-ish string; None if it is neither. Used to reject
    a bad value at the API boundary rather than silently defaulting."""
    text = value.strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def parse_bool(value: str | None, default: bool) -> bool:
    """Read a stored string as a bool, falling back on anything unexpected."""
    if value is None:
        return default
    parsed = coerce_bool(value)
    return default if parsed is None else parsed


async def list_all(session: AsyncSession) -> list[Setting]:
    res = await session.exec(select(Setting).order_by(Setting.key))
    return list(res.all())


async def get_int(session: AsyncSession, key: str, default: int) -> int:
    """Read `key` as an int, tolerating a missing row or unparseable value."""
    row = await session.get(Setting, key)
    if row is None:
        return default
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return default


async def get_bool(session: AsyncSession, key: str, default: bool) -> bool:
    row = await session.get(Setting, key)
    return parse_bool(row.value if row else None, default)


async def set_value(session: AsyncSession, key: str, value: str) -> Setting:
    """Upsert a setting. Description is filled from DEFAULTS for known keys."""
    row = await session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value, description=DEFAULTS.get(key, (None, None))[1])
    else:
        row.value = value
        row.updated_at = naive_utcnow()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    _flag_cache.pop(key, None)  # a hot-path reader sees the change at once (this worker)
    return row


# --- hot-path flags --------------------------------------------------------
# Middleware that consults a flag on every request cannot afford a SELECT per
# request. Values are cached in-process and dropped the moment set_value writes
# that key. Each worker holds its own cache, so after a change made on another
# worker the TTL is the worst-case lag.
FLAG_CACHE_TTL_SECONDS = 15.0
_flag_cache: dict[str, tuple[bool, float]] = {}


async def flag(key: str, default: bool) -> bool:
    """Cached boolean read that opens its own session — for callers outside a
    request's dependency scope. Never raises: a DB problem here must not turn
    into a failed request."""
    now = time.monotonic()
    cached = _flag_cache.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]
    try:
        async with async_session_maker() as session:
            value = await get_bool(session, key, default)
    except Exception:
        return default
    _flag_cache[key] = (value, now + FLAG_CACHE_TTL_SECONDS)
    return value


async def sampling_interval(session: AsyncSession) -> int:
    """Typed, clamped accessor per key — callers never parse strings."""
    n = await get_int(session, SAMPLING_INTERVAL, int(DEFAULTS[SAMPLING_INTERVAL][0]))
    return n if n >= 1 else 1
```

```python
# api/routes/settings.py — validate and NORMALISE at the boundary, per key.
# The source wrote this as an if-chain; a registry keeps one place per key.

def _positive_int(v: str) -> str:
    n = int(v)  # ValueError → 400 below
    if n < 1:
        raise ValueError("must be at least 1")
    return str(n)

def _strict_bool(v: str) -> str:
    parsed = settings_service.coerce_bool(v)
    if parsed is None:
        raise ValueError("must be true or false")
    return "true" if parsed else "false"  # stored normalised: readers never guess

VALIDATORS: dict[str, Callable[[str], str]] = {
    settings_service.SAMPLING_INTERVAL: _positive_int,
    settings_service.LOG_GET_REQUESTS: _strict_bool,
    # structured values: run the same parser the reader uses, e.g. a shift calendar
}
# A diagnostics knob is admin-only even though supervisors may edit line settings.
ADMIN_ONLY = {settings_service.LOG_GET_REQUESTS}


@router.get("", response_model=list[SettingOut])
async def list_settings(session: AsyncSession = Depends(get_session)) -> list[SettingOut]:
    return [SettingOut.model_validate(r) for r in await settings_service.list_all(session)]


@router.put("/{key}", response_model=SettingOut)
async def update_setting(
    key: str,
    body: SettingUpdateIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_roles(Role.supervisor, Role.admin)),
) -> SettingOut:
    """Update (or create) a setting. A change applies to what is created after
    it — in-flight records keep what they were created with."""
    value = body.value.strip()
    if key in ADMIN_ONLY and user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{key} can only be changed by an admin")
    if key in VALIDATORS:
        try:
            value = VALIDATORS[key](value)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key}: {exc}")
    row = await settings_service.set_value(session, key, value)
    return SettingOut.model_validate(row)
```

### 6b. Per-terminal preferences (browser) — `lib/prefs.ts`

```ts
import { useSyncExternalStore } from "react"

/**
 * Per-terminal UI preferences — a localStorage-backed store (module-level
 * state + useSyncExternalStore) so it can be read outside React too.
 *
 * Deliberately NOT backend settings: they only describe how hard *this*
 * browser hammers the API. Realtime pushes already deliver live changes, so
 * the intervals are self-healing fallbacks — a terminal on a weak link can
 * slow them down without affecting anybody else.
 */
export interface UiPrefs {
  listPollMs: number
  queuePollMs: number
}

export interface PrefSpec {
  label: string
  help: string
  default: number
  min: number
  max: number
  /** Offered as one-tap chips; the user can still type a custom value. */
  presets: number[]
}

export const PREF_SPECS: Record<keyof UiPrefs, PrefSpec> = {
  listPollMs: { label: "List refresh", help: "The list page and its sidebar badge.", default: 8_000, min: 3_000, max: 120_000, presets: [5_000, 8_000, 15_000, 30_000] },
  queuePollMs: { label: "Queue refresh", help: "Fallback only — arrivals already come over the socket.", default: 30_000, min: 5_000, max: 300_000, presets: [10_000, 30_000, 60_000, 120_000] },
}

const KEYS = Object.keys(PREF_SPECS) as (keyof UiPrefs)[]
export const PREF_DEFAULTS = Object.fromEntries(KEYS.map((k) => [k, PREF_SPECS[k].default])) as unknown as UiPrefs

const KEY = "app.ui.prefs"

/** Keep a stored/typed value inside its spec's range, falling back to default. */
export function clampPref(key: keyof UiPrefs, value: unknown): number {
  const spec = PREF_SPECS[key]
  const n = typeof value === "number" ? value : Number(value)
  if (!Number.isFinite(n)) return spec.default
  return Math.min(spec.max, Math.max(spec.min, Math.round(n)))
}

function load(): UiPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Record<keyof UiPrefs, unknown>>
      // Clamp on load too: an old release or a hand edit can leave a value out of range.
      return Object.fromEntries(
        KEYS.map((k) => [k, parsed[k] === undefined ? PREF_DEFAULTS[k] : clampPref(k, parsed[k])]),
      ) as unknown as UiPrefs
    }
  } catch {
    // malformed / unavailable storage — fall through to defaults
  }
  return { ...PREF_DEFAULTS }
}

let state: UiPrefs = load()
const listeners = new Set<() => void>()

function setState(next: UiPrefs): void {
  state = next
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    // storage full/disabled — the prefs still apply for this session
  }
  listeners.forEach((l) => l())
}

export const uiPrefs = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  snapshot: (): UiPrefs => state,
  set(patch: Partial<UiPrefs>): void {
    const next = { ...state }
    for (const [k, v] of Object.entries(patch) as [keyof UiPrefs, number | undefined][]) {
      if (v !== undefined) next[k] = clampPref(k, v)
    }
    setState(next)
  },
  reset: (): void => setState({ ...PREF_DEFAULTS }),
  isDefault: (): boolean => KEYS.every((k) => state[k] === PREF_DEFAULTS[k]),
}

export function useUiPrefs(): UiPrefs {
  return useSyncExternalStore(uiPrefs.subscribe, uiPrefs.snapshot)
}

/** "8 s" / "2 min" — short enough for a chip. */
export function fmtInterval(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)} s`
  const min = ms / 60_000
  return `${Number.isInteger(min) ? min : min.toFixed(1)} min`
}
```

### 6c. The settings dialog

```tsx
export type SettingsTab = "line" | "terminal"

/** Where a section's values live — the one thing a user must not misread. */
type Scope = "line" | "browser"

function ScopeBadge({ scope }: { scope: Scope }) {
  return scope === "line" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400"><Globe className="size-3" /> Every terminal</span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-700 dark:text-sky-400"><Monitor className="size-3" /> This browser only</span>
  )
}

/** The long explanation, folded away until someone asks for it. */
function HowItWorks({ children }: { children: ReactNode }) {
  return (
    <details className="group rounded-lg border bg-secondary/30 text-xs text-muted-foreground [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 font-medium select-none">
        <Info className="size-3.5" /> How this works
        <ChevronRight className="ml-auto size-3.5 transition-transform group-open:rotate-90" />
      </summary>
      <div className="space-y-2 border-t px-3 py-2.5 leading-relaxed">{children}</div>
    </details>
  )
}

/** Appears only while there is something to save — an untouched section has
 *  no buttons nagging at it. Sticks to the bottom of the scrolling pane. */
function SaveBar({ count, saving, canSave, problem, onDiscard, onSave }: {
  count: number; saving: boolean; canSave: boolean; problem?: string | null; onDiscard: () => void; onSave: () => void
}) {
  if (!count) return null
  return (
    <div className="anim-rise sticky bottom-0 -mx-5 mt-6 flex items-center gap-2 border-t bg-popover/95 px-5 py-3 backdrop-blur sm:-mx-6 sm:px-6">
      <span className={cn("min-w-0 flex-1 truncate text-xs", problem ? "text-rose-600" : "text-muted-foreground")}>
        {problem ?? `${count} unsaved change${count === 1 ? "" : "s"}`}
      </span>
      <Button variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>Discard</Button>
      <Button size="sm" onClick={onSave} disabled={!canSave || saving}>{saving && <Loader2 className="size-4 animate-spin" />} Save</Button>
    </div>
  )
}

type Rows = Record<string, Setting>
type SectionId = "sampling" | "shifts" | "refresh" | "diagnostics"

interface SectionDef {
  id: SectionId
  group: SettingsTab
  label: string
  icon: LucideIcon
  /** The current value, shown under the label so the list doubles as an
   *  overview — most visits are to check a value, not to change it. */
  summary: (rows: Rows, prefs: UiPrefs) => string
}

const SECTIONS: SectionDef[] = [
  { id: "sampling", group: "line", label: "Inspection sampling", icon: Shuffle, summary: (rows) => `1 in ${rows.sampling_interval?.value ?? "20"}` },
  { id: "refresh", group: "terminal", label: "Refresh rates", icon: Timer, summary: (_, p) => `${fmtInterval(p.listPollMs)} · ${fmtInterval(p.queuePollMs)}` },
  // …
]

export function SettingsDialog({ tab, onTabChange, onClose, canLine, canTerminal }: {
  tab: SettingsTab | null
  onTabChange: (tab: SettingsTab) => void
  onClose: () => void
  canLine: boolean
  canTerminal: boolean
}) {
  const open = tab !== null
  const prefs = useUiPrefs()
  const sections = SECTIONS.filter((s) => (s.group === "line" ? canLine : canTerminal))
  const [section, setSection] = useState<SectionId | null>(null)
  const [rows, setRows] = useState<Rows | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [dirty, setDirty] = useState<Partial<Record<SectionId, boolean>>>({})
  const [confirmClose, setConfirmClose] = useState(false)

  // Opening from the account menu (Line… / Terminal…) lands on that group's
  // first section; the list then moves freely between groups.
  useEffect(() => {
    if (!tab) return
    setSection((cur) => {
      if (cur && SECTIONS.find((s) => s.id === cur)?.group === tab) return cur
      return sections.find((s) => s.group === tab)?.id ?? sections[0]?.id ?? null
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  // One read for every section. The list, not GET /{key}: a fresh database may
  // not have a row yet (a PUT creates it), and a 404 is not an error here.
  const load = useCallback(async () => {
    setRows(null)
    setLoadError(null)
    try {
      const all = await api.settings()
      setRows(Object.fromEntries(all.map((s) => [s.key, s])))
    } catch (e) {
      setLoadError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    if (open) { setDirty({}); setConfirmClose(false); void load() }
  }, [open, load])

  const onSaved = useCallback((updated: Setting[]) => {
    setRows((cur) => ({ ...(cur ?? {}), ...Object.fromEntries(updated.map((s) => [s.key, s])) }))
  }, [])

  // Stable per-section callbacks, so a section's effect doesn't loop.
  const dirtySetters = useMemo(
    () => Object.fromEntries(
      SECTIONS.map((s) => [s.id, (d: boolean) => setDirty((cur) => (!!cur[s.id] === d ? cur : { ...cur, [s.id]: d }))]),
    ) as Record<SectionId, (d: boolean) => void>,
    [],
  )

  const unsaved = sections.filter((s) => dirty[s.id])
  const requestClose = () => (unsaved.length ? setConfirmClose(true) : onClose())
  const pick = (id: SectionId) => {
    setSection(id)
    setConfirmClose(false)
    const group = SECTIONS.find((s) => s.id === id)!.group
    if (group !== tab) onTabChange(group)
  }
  const current = sections.find((s) => s.id === section) ?? sections[0]

  return (
    <Dialog open={open} onOpenChange={(o) => !o && requestClose()}>
      <DialogContent className="flex h-[min(720px,90vh)] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
        {/* title bar */}
        <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
          {/* Section list — a scrolling strip on phones, a column from sm up.
              Grouped (Line / Terminal); each entry shows its current value and
              an amber dot while it has unsaved edits. */}
          <nav aria-label="Settings sections">{/* …buttons calling pick(s.id)… */}</nav>
          {/* The open section. Every section stays mounted (hidden when not
              shown), so switching away never loses a half-typed edit. */}
          <div className="relative min-h-0 flex-1 overflow-y-auto px-5 pt-5 pb-5 sm:px-6">
            {loadError ? (
              <div>Could not load settings: {loadError} <Button size="sm" variant="outline" onClick={() => void load()}>Try again</Button></div>
            ) : !rows ? (
              <div className="space-y-3"><Skeleton className="h-5 w-48" /><Skeleton className="h-4 w-72" /><Skeleton className="h-28 w-full rounded-xl" /></div>
            ) : (
              sections.map((s) => (
                <div key={s.id} hidden={s.id !== current?.id} className="anim-fade">
                  {renderSection(s.id, { rows, onSaved, onDirty: dirtySetters[s.id] })}
                </div>
              ))
            )}
          </div>
        </div>
        {confirmClose && (
          // Inline, not a second modal: names exactly what would be lost.
          <div className="anim-rise flex flex-wrap items-center gap-2 border-t bg-amber-500/10 px-5 py-3 sm:px-6">
            <TriangleAlert className="size-4 shrink-0 text-amber-600" />
            <span className="min-w-0 flex-1 text-xs">Unsaved changes in <strong>{unsaved.map((s) => s.label).join(", ")}</strong>.</span>
            <Button size="sm" variant="ghost" onClick={() => setConfirmClose(false)}>Keep editing</Button>
            <Button size="sm" variant="destructive" onClick={onClose}>Discard &amp; close</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

A line section owns its draft, reports `dirty` through `onDirty`, saves with
`PUT /api/settings/{key}` and hands the returned rows to `onSaved`; its header
is `title + ScopeBadge + one-line lead`, its foot a "Last changed …" stamp
(or "Using the default" when no row exists yet) and the `SaveBar`. A text
field that differs from its default offers a one-click "back to default". A
terminal section writes `uiPrefs.set()` directly — there is nothing to save.
