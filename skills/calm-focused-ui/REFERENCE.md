# calm-focused-ui — REFERENCE

Copy-paste building blocks. Every file below is the exact source of a demo (Vite 6, React 19, Tailwind 4.3, lucide-react) that was built and passed `check-floors.mjs` on its list, dark, sheet-with-error, empty and loading screens. Section 13 covers Tailwind v3 and Vue.

## 1. Tokens — `src/theme.css` (Tailwind v4)

Type, control sizes, radii, semantic light/dark colours, focus outline, reduced motion. Components use only these names (`bg-surface`, `text-muted`, `h-control`, `text-body`…), never raw palette colours or arbitrary px.

```css
/* calm-focused-ui tokens (Tailwind v4). One file: type, control sizes, radii, semantic colours, focus, motion floor. */
@import "tailwindcss";
@custom-variant dark (&:where(.dark, .dark *));

/* Semantic colours: components use these names only, never raw palette colours. */
:root {
  --c-bg: #f5f6f8;  --c-surface: #ffffff; --c-sunken: #eef0f3;
  --c-fg: #111827;  --c-muted: #4b5563;   --c-line: #d9dde3; --c-line-strong: #8a94a3; /* line: dividers only (1.4:1); line-strong: control edges (3.1:1, WCAG 1.4.11) */
  --c-primary: #1f5fd6; --c-primary-fg: #ffffff; --c-primary-hover: #1a50b5;
  --c-good: #15803d; --c-warn: #b45309; --c-bad: #b91c1c; --c-info: #1d4ed8;
  --c-focus: #2563eb;
}
.dark {
  --c-bg: #0f1115;  --c-surface: #171a21; --c-sunken: #12151b;
  --c-fg: #e8eaee;  --c-muted: #a3aab6;   --c-line: #2c323d; --c-line-strong: #6b7484;
  --c-primary: #5b93ff; --c-primary-fg: #0b1220; --c-primary-hover: #7aa8ff;
  --c-good: #4ade80; --c-warn: #fbbf24; --c-bad: #f87171; --c-info: #93c5fd;
  --c-focus: #93c5fd;
}

@theme inline {
  --color-bg: var(--c-bg); --color-surface: var(--c-surface); --color-sunken: var(--c-sunken);
  --color-fg: var(--c-fg); --color-muted: var(--c-muted); --color-line: var(--c-line); --color-line-strong: var(--c-line-strong);
  --color-primary: var(--c-primary); --color-primary-fg: var(--c-primary-fg); --color-primary-hover: var(--c-primary-hover);
  --color-good: var(--c-good); --color-warn: var(--c-warn); --color-bad: var(--c-bad); --color-info: var(--c-info);
}

@theme {
  /* Type: 16 px body; 14 px is the floor and only for metadata. */
  --text-meta: 0.875rem;  --text-meta--line-height: 1.25rem;
  --text-body: 1rem;      --text-body--line-height: 1.5rem;
  --text-lead: 1.125rem;  --text-lead--line-height: 1.75rem;
  --text-title: 1.375rem; --text-title--line-height: 1.875rem;
  --text-page: 1.75rem;   --text-page--line-height: 2.25rem;
  /* Control sizes (h-control, min-w-control ...): 44 default, 36 only inside dense rows, 52 for the one primary of a sheet. */
  --spacing-control-sm: 2.25rem;
  --spacing-control: 2.75rem;
  --spacing-control-lg: 3.25rem;
  --radius-control: 0.625rem;
  --radius-card: 0.875rem;
  --shadow-sheet: 0 20px 50px -12px rgb(0 0 0 / 0.35);
}

@layer base {
  html { font-size: 100%; }       /* respect the browser setting; never shrink the root */
  body { @apply bg-bg text-fg text-body antialiased; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  button, [role="button"], summary { cursor: pointer; } /* Tailwind v4 preflight removed it */
  /* Focus as an outline (not ring/box-shadow) so hover shadows can never erase it. */
  :focus-visible { outline: 3px solid var(--c-focus); outline-offset: 2px; }
  [aria-disabled="true"] { cursor: not-allowed; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 1ms !important; animation-iteration-count: 1 !important; transition-duration: 1ms !important; scroll-behavior: auto !important; }
}
```

## 2. `cn` helper

```ts
export const cn = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');
```

## 3. Button — one primary, answer on press, busy without losing focus

```tsx
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from './cn';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';
export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; busy?: boolean };

const V: Record<Variant, string> = {
  primary: 'bg-primary text-primary-fg hover:bg-primary-hover font-semibold',
  secondary: 'bg-surface text-fg border border-line-strong hover:bg-sunken font-medium',
  ghost: 'text-fg hover:bg-sunken font-medium',
  danger: 'bg-surface text-bad border border-bad/40 hover:bg-bad/10 font-medium',
};
// sm (36 px) only inside dense table rows; md (44 px) everywhere else; lg (52 px) for the single primary of a sheet.
const S: Record<Size, string> = { sm: 'h-control-sm px-3 text-meta', md: 'h-control px-4 text-body', lg: 'h-control-lg px-6 text-lead' };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', busy = false, disabled, className, children, onClick, ...rest }, ref) {
  // aria-disabled instead of disabled: a disabled button drops keyboard focus to <body>
  const off = disabled || busy;
  return (
    <button ref={ref} {...rest} data-variant={variant} aria-disabled={off || undefined} aria-busy={busy || undefined}
      onClick={(e) => { if (off) { e.preventDefault(); return; } onClick?.(e); }}
      className={cn('inline-flex items-center justify-center gap-2 rounded-control whitespace-nowrap select-none',
        'transition-[transform,background-color] duration-100 ease-out active:scale-[0.97]', // answer on press, not on release
        V[variant], S[size], off && 'opacity-55 active:scale-100', className)}>
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});
```

## 4. Page — the screen states its job and holds one primary

```tsx
import type { ReactNode } from 'react';
import { cn } from './cn';

// One screen = one job. The header states the job and holds exactly ONE primary action;
// up to two quiet secondaries sit beside it; everything else lives one level deeper.
export function Page({ title, description, primary, secondary, width = 'wide', children }: {
  title: string; description?: string; primary?: ReactNode; secondary?: ReactNode;
  width?: 'form' | 'wide'; children: ReactNode;
}) {
  return (
    <main className={cn('mx-auto px-8 py-8', width === 'form' ? 'max-w-2xl' : 'max-w-6xl')}>
      <header className="mb-6 flex items-start justify-between gap-6">
        <div className="min-w-0">
          <h1 className="text-page font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-1 text-lead text-muted">{description}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">{secondary}{primary}</div>
      </header>
      {children}
    </main>
  );
}
```

## 5. Field, TextInput, TextArea, Select

Label above, hint below, error = what is wrong + how to fix, wired with `aria-describedby` / `aria-invalid`.

```tsx
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { cn } from './cn';

// Shared look only — width and height are set per control, or a later utility silently loses the fight.
export const controlClass = 'rounded-control border border-line-strong bg-surface px-3 text-body placeholder:text-muted/80 aria-[invalid=true]:border-bad';
export const inputClass = controlClass + ' h-control w-full';

// Label above, hint below, error = what is wrong + how to fix, tied to the input for screen readers.
export function Field({ label, hint, error, fix, children }: {
  label: string; hint?: string; error?: string; fix?: string;
  children: (p: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => ReactNode;
}) {
  const id = useId(), hintId = `${id}-hint`, errId = `${id}-err`;
  const describedBy = [hint && hintId, error && errId].filter(Boolean).join(' ') || undefined;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-body font-medium">{label}</label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': !!error || undefined })}
      {hint && !error && <p id={hintId} className="text-meta text-muted">{hint}</p>}
      {error && <p id={errId} role="alert" className="text-meta text-bad"><b className="font-semibold">{error}</b>{fix && <> — {fix}</>}</p>}
    </div>
  );
}
export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(inputClass, props.className)} />;
}
export function TextArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea rows={4} {...props} className={cn(controlClass, 'block min-h-28 w-full py-2', props.className)} />;
}
export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(controlClass, 'h-control', className || 'w-full')} />;
}
```

## 6. More — level 2 of progressive disclosure

```tsx
import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';

// Level 2 of progressive disclosure: native <details>, keyboard + screen-reader ready.
// Never nest a More inside a More (max 2 levels: the screen, then this).
export function More({ label = 'More options', children }: { label?: string; children: ReactNode }) {
  return (
    <details className="group rounded-card border border-line bg-surface">
      <summary className="flex h-control list-none items-center gap-2 px-4 text-body font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-4 transition-transform duration-150 group-open:rotate-90" aria-hidden />{label}
      </summary>
      <div className="space-y-4 border-t border-line p-4">{children}</div>
    </details>
  );
}
```

## 7. Status — icon + word + colour

```tsx
import { CheckCircle2, AlertTriangle, XCircle, Info, Circle } from 'lucide-react';
import { cn } from './cn';

export type Tone = 'good' | 'warn' | 'bad' | 'info' | 'idle';
const T = { good: [CheckCircle2, 'text-good'], warn: [AlertTriangle, 'text-warn'], bad: [XCircle, 'text-bad'], info: [Info, 'text-info'], idle: [Circle, 'text-muted'] } as const;
// Icon + word + colour, always: glare and colour-blindness erase colour alone.
export function Status({ tone, children }: { tone: Tone; children: string }) {
  const [Icon, color] = T[tone];
  return <span className={cn('inline-flex items-center gap-1.5 font-medium', color)}><Icon className="size-4" aria-hidden />{children}</span>;
}
```

## 8. Sheet — one record's detail beside its list

```tsx
import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

// Detail of one record in a side sheet: the list stays visible (context), the sheet is the one focus.
// Dim the rest, Esc closes, focus moves into the sheet and back to the opener on close.
export function Sheet({ open, title, onClose, footer, children }: { open: boolean; title: string; onClose: () => void; footer?: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null), opener = useRef<Element | null>(null);
  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    ref.current?.querySelector<HTMLElement>('h2')?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    addEventListener('keydown', onKey);
    return () => { removeEventListener('keydown', onKey); (opener.current as HTMLElement | null)?.focus?.(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby="sheet-title"
        className="absolute inset-y-0 right-0 flex w-[min(560px,100vw)] flex-col bg-surface shadow-sheet">
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 id="sheet-title" tabIndex={-1} className="text-title font-semibold outline-none">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="grid size-control place-items-center rounded-control hover:bg-sunken"><X className="size-5" /></button>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}
```

## 9. Table — technician density, one visible row action

```tsx
import type { ReactNode } from 'react';
import { MoreHorizontal } from 'lucide-react';

export type Col<T> = { key: string; head: string; cell: (row: T) => ReactNode; className?: string };

// Technician tables may be dense, but every row is still a 44 px target, the header sticks,
// and each row shows ONE visible action; the rest sit in its overflow menu.
export function Table<T>({ rows, cols, rowKey, onOpen, openLabel = 'Open', menu }: {
  rows: T[]; cols: Col<T>[]; rowKey: (r: T) => string; onOpen: (r: T) => void; openLabel?: string;
  menu?: (r: T) => { label: string; onSelect: () => void; danger?: boolean }[];
}) {
  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface">
      <table className="w-full border-collapse text-left">
        <thead className="sticky top-0 bg-sunken text-meta font-semibold uppercase tracking-wide text-muted">
          <tr>{cols.map((c) => <th key={c.key} scope="col" className={'px-4 py-2.5 ' + (c.className || '')}>{c.head}</th>)}<th className="w-px" /></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)} className="h-control border-t border-line hover:bg-sunken/60">
              {cols.map((c) => <td key={c.key} className={'px-4 py-2 ' + (c.className || '')}>{c.cell(r)}</td>)}
              <td className="whitespace-nowrap px-3 py-1.5 text-right">
                <button onClick={() => onOpen(r)} className="h-control-sm rounded-control px-3 text-meta font-semibold text-primary hover:bg-primary/10">{openLabel}</button>
                {menu && (
                  <details className="relative inline-block">
                    <summary aria-label="More actions" className="inline-grid size-control-sm list-none place-items-center rounded-control hover:bg-sunken [&::-webkit-details-marker]:hidden"><MoreHorizontal className="size-4" /></summary>
                    <div className="absolute right-0 z-10 mt-1 w-48 rounded-card border border-line bg-surface p-1 shadow-sheet">
                      {menu(r).map((m) => <button key={m.label} onClick={m.onSelect} className={'flex h-control-sm w-full items-center rounded-control px-3 text-left text-meta hover:bg-sunken ' + (m.danger ? 'text-bad' : '')}>{m.label}</button>)}
                    </div>
                  </details>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

## 10. States — loading, empty, problem

```tsx
import type { ReactNode } from 'react';
import { Inbox, AlertOctagon } from 'lucide-react';

// Three honest states. Loading = skeleton shaped like the content (motion: ui-motion-system),
// empty = what this is + the one action that fills it, error = why + how to fix + retry.
export function Empty({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-card border border-dashed border-line bg-surface px-6 py-14 text-center">
      <Inbox className="mb-3 size-8 text-muted" aria-hidden />
      <p className="text-lead font-semibold">{title}</p>
      <p className="mt-1 max-w-md text-body text-muted">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
export function Problem({ why, how, retry }: { why: string; how: string[]; retry?: ReactNode }) {
  return (
    <div role="alert" className="rounded-card border border-bad/40 bg-bad/5 p-4">
      <p className="flex items-center gap-2 font-semibold text-bad"><AlertOctagon className="size-5" aria-hidden />{why}</p>
      <ol className="mt-2 list-decimal space-y-1 pl-6 text-body">{how.map((h) => <li key={h}>{h}</li>)}</ol>
      {retry && <div className="mt-3">{retry}</div>}
    </div>
  );
}
export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return <div className="space-y-2" aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className="h-control animate-pulse rounded-control bg-sunken" />)}</div>;
}
```

## 11. A whole screen — `App.tsx` (service tickets)

Every rule at once: job in the header, one primary (moved to the empty state when the list is empty), search + one filter visible, the rest under **More filters**, table with one row action, detail in a sheet with one primary in its footer, an inline problem block, **Advanced** as the sheet's level 2. `?theme=dark`, `?sheet=1&fail=1`, `?view=empty|loading` render each state for screenshots.

```tsx
import { useMemo, useState } from 'react';
import { Plus, Moon, Sun, Search } from 'lucide-react';
import { Page } from './ui/Page';
import { Button } from './ui/Button';
import { Field, TextInput, TextArea, Select, inputClass } from './ui/Field';
import { More } from './ui/More';
import { Status, type Tone } from './ui/Status';
import { Sheet } from './ui/Sheet';
import { Table } from './ui/Table';
import { Empty, Problem, SkeletonRows } from './ui/States';

type Ticket = { id: string; machine: string; issue: string; status: [Tone, string]; age: string };
const TICKETS: Ticket[] = [
  { id: 'T-1042', machine: 'Line 3 · Labeller', issue: 'Label skewed on every 3rd box', status: ['bad', 'Down'], age: '12 min' },
  { id: 'T-1041', machine: 'Line 1 · Conveyor B', issue: 'Belt speed alarm, cleared twice', status: ['warn', 'Watch'], age: '48 min' },
  { id: 'T-1039', machine: 'Packing · Scale 2', issue: 'Calibration due', status: ['info', 'Scheduled'], age: '2 h' },
  { id: 'T-1036', machine: 'Line 2 · Robot cell', issue: 'Gripper replaced, verify pick rate', status: ['good', 'Fixed'], age: '5 h' },
];

export default function App() {
  const q = new URLSearchParams(location.search);
  const [dark, setDark] = useState(q.get('theme') === 'dark');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<Ticket | null>(q.get('sheet') ? TICKETS[0] : null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(q.get('fail') === '1');
  const view = q.get('view'); // 'empty' | 'loading' for the state screenshots
  const rowsAll = useMemo(() => TICKETS.filter((t) => (t.id + t.machine + t.issue).toLowerCase().includes(query.toLowerCase())), [query]);
  const rows = view === 'empty' ? [] : rowsAll;
  const isEmpty = view !== 'loading' && rows.length === 0;
  document.documentElement.classList.toggle('dark', dark);

  return (
    <Page title="Service tickets" description="Open issues on the floor, newest first."
      secondary={<Button variant="ghost" aria-label={dark ? 'Light theme' : 'Dark theme'} onClick={() => setDark(!dark)}>{dark ? <Sun className="size-5" /> : <Moon className="size-5" />}</Button>}
      // one primary on screen: when the list is empty, the empty state carries it instead
      primary={isEmpty ? undefined : <Button variant="primary"><Plus className="size-5" aria-hidden />New ticket</Button>}>
      <div className="mb-4 flex items-center gap-3">
        <div className="relative w-96">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" aria-hidden />
          <input aria-label="Search tickets" placeholder="Search machine or issue" value={query} onChange={(e) => setQuery(e.target.value)} className={inputClass + ' pl-10'} />
        </div>
        <Select aria-label="Status" className="w-48"><option>All statuses</option><option>Down</option><option>Watch</option></Select>
      </div>
      <div className="mb-5"><More label="More filters"><div className="grid grid-cols-2 gap-4">
        <Field label="Machine area">{(p) => <TextInput {...p} placeholder="e.g. Line 3" />}</Field>
        <Field label="Opened by">{(p) => <TextInput {...p} placeholder="Name or badge" />}</Field>
      </div></More></div>

      {view === 'loading' ? <SkeletonRows /> : isEmpty ? (
        <Empty title="No open tickets" body="Everything on the floor is running. New issues raised by operators appear here."
          action={<Button variant="primary"><Plus className="size-5" aria-hidden />New ticket</Button>} />
      ) : (
        <Table rows={rows} rowKey={(r) => r.id} onOpen={setOpen}
          cols={[
            { key: 'id', head: 'Ticket', cell: (r) => <span className="font-mono text-meta text-muted">{r.id}</span>, className: 'w-28' },
            { key: 'm', head: 'Machine', cell: (r) => <span className="font-medium">{r.machine}</span> },
            { key: 'i', head: 'Issue', cell: (r) => r.issue },
            { key: 's', head: 'Status', cell: (r) => <Status tone={r.status[0]}>{r.status[1]}</Status>, className: 'w-36' },
            { key: 'a', head: 'Age', cell: (r) => <span className="text-muted">{r.age}</span>, className: 'w-24' },
          ]}
          menu={() => [{ label: 'Assign to me', onSelect: () => {} }, { label: 'Close ticket', onSelect: () => {}, danger: true }]} />
      )}

      <Sheet open={!!open} title={open ? `${open.id} · ${open.machine}` : ''} onClose={() => setOpen(null)}
        footer={<><Button variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
          <Button variant="primary" size="lg" busy={busy} onClick={() => { setBusy(true); setTimeout(() => { setBusy(false); setFailed(true); }, 600); }}>Save fix</Button></>}>
        {open && <>
          <div className="flex items-center gap-3"><Status tone={open.status[0]}>{open.status[1]}</Status><span className="text-muted">opened {open.age} ago</span></div>
          <p className="text-lead">{open.issue}</p>
          {failed && <Problem why="Couldn't save — the ticket was updated by someone else." how={['Reload the ticket to see their change.', 'Re-enter your fix note.', 'Press Save fix again.']} />}
          <Field label="What did you do?" hint="Plain words; the operator reads this at the machine.">{(p) => <TextArea {...p} />}</Field>
          <Field label="Parts used" error={failed ? 'Part number not found' : undefined} fix="check the label on the bag (8 digits)">{(p) => <TextInput {...p} defaultValue="LB-77" />}</Field>
          <More label="Advanced"><Field label="Downtime override (min)">{(p) => <TextInput {...p} type="number" />}</Field></More>
        </>}
      </Sheet>
    </Page>
  );
}
```

## 12. Floors check — `scripts/check-floors.mjs`

Run it against every screen you built (`npx vite preview`, then pass each URL and each state's URL). Exit 1 on any miss.

```js
// Numeric floors of calm-focused-ui, measured in a real browser: node tools/check-floors.mjs <url> [more urls...]
//  - every pointer target >= 24x24 CSS px (WCAG 2.2 SC 2.5.8); >= 44 px tall outside dense rows; >= 36 px inside tables
//  - no visible text below 14 px
//  - at most ONE visible primary button per surface (the page, and each open dialog)
// Exit code 1 on any failure. Needs: npm i -D playwright && npx playwright install chromium
import { chromium } from 'playwright';
const urls = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
let failed = false;
for (const url of urls) {
  await page.goto(url); await page.waitForLoadState('networkidle');
  const r = await page.evaluate(() => {
    const vis = (el) => { const s = getComputedStyle(el), b = el.getBoundingClientRect(); return s.visibility !== 'hidden' && s.display !== 'none' && b.width > 0 && b.height > 0 && !el.closest('details:not([open]) > :not(summary)'); };
    const name = (el) => (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || el.tagName).trim().slice(0, 40);
    const targets = [...document.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button]')].filter(vis);
    const small = [];
    for (const el of targets) {
      const b = el.getBoundingClientRect(), dense = !!el.closest('table, [data-dense]'), min = dense ? 36 : 44;
      if (b.width < 24 || b.height < 24) small.push(`FAIL <24px ${Math.round(b.width)}x${Math.round(b.height)} "${name(el)}"`);
      else if (b.height < min - 0.5 && el.tagName !== 'TEXTAREA') small.push(`below ${min}px: ${Math.round(b.height)}px "${name(el)}"`);
    }
    const tiny = [];
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = walk.nextNode());) { const el = n.parentElement; if (!n.textContent.trim() || !vis(el)) continue; const fs = parseFloat(getComputedStyle(el).fontSize); if (fs < 14) tiny.push(`${fs}px "${n.textContent.trim().slice(0, 30)}"`); }
    const surfaces = [document.body, ...document.querySelectorAll('[role=dialog]')];
    const primaries = surfaces.map((s) => [...s.querySelectorAll('[data-variant=primary]')].filter((b) => vis(b) && (s === document.body ? !b.closest('[role=dialog]') : true)).length);
    return { targets: targets.length, small, tiny: [...new Set(tiny)], primaries };
  });
  const bad = r.small.some((s) => s.startsWith('FAIL')) || r.tiny.length > 0 || r.primaries.some((n) => n > 1) || r.small.length > 0;
  failed ||= bad;
  console.log(JSON.stringify({ url, ok: !bad, ...r }));
}
await browser.close();
process.exit(failed ? 1 : 0);
```

## 13. Other stacks

**Tailwind v3** — put the same values in `tailwind.config.js` and keep the CSS variables block as is:

```js
export default {
  darkMode: 'class',
  theme: { extend: {
    colors: { bg: 'var(--c-bg)', surface: 'var(--c-surface)', sunken: 'var(--c-sunken)', fg: 'var(--c-fg)', muted: 'var(--c-muted)',
      line: { DEFAULT: 'var(--c-line)', strong: 'var(--c-line-strong)' }, primary: { DEFAULT: 'var(--c-primary)', fg: 'var(--c-primary-fg)', hover: 'var(--c-primary-hover)' },
      good: 'var(--c-good)', warn: 'var(--c-warn)', bad: 'var(--c-bad)', info: 'var(--c-info)' },
    fontSize: { meta: ['0.875rem', '1.25rem'], body: ['1rem', '1.5rem'], lead: ['1.125rem', '1.75rem'], title: ['1.375rem', '1.875rem'], page: ['1.75rem', '2.25rem'] },
    spacing: { 'control-sm': '2.25rem', control: '2.75rem', 'control-lg': '3.25rem' },
    borderRadius: { control: '0.625rem', card: '0.875rem' },
  } },
};
```

Opacity modifiers on variable colours (`bg-bad/10`) need the colour as channels in v3 (`--c-bad: 185 28 28;` and `rgb(var(--c-bad) / <alpha-value>)`); v4 handles `var()` colours directly.

**Vue 3 + Tailwind** — `theme.css` is identical; the recipes port 1:1 because all the design lives in the class strings. Button as an SFC (a port sketch — the React files above are the ones built and checked; build and run `check-floors.mjs` on the Vue port before relying on it):

```vue
<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next';
const props = withDefaults(defineProps<{ variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; size?: 'sm' | 'md' | 'lg'; busy?: boolean; disabled?: boolean }>(),
  { variant: 'secondary', size: 'md', busy: false, disabled: false });
const emit = defineEmits<{ click: [MouseEvent] }>();
const V = { primary: 'bg-primary text-primary-fg hover:bg-primary-hover font-semibold', secondary: 'bg-surface text-fg border border-line-strong hover:bg-sunken font-medium',
  ghost: 'text-fg hover:bg-sunken font-medium', danger: 'bg-surface text-bad border border-bad/40 hover:bg-bad/10 font-medium' };
const S = { sm: 'h-control-sm px-3 text-meta', md: 'h-control px-4 text-body', lg: 'h-control-lg px-6 text-lead' };
const off = () => props.disabled || props.busy;
</script>
<template>
  <button :data-variant="variant" :aria-disabled="off() || undefined" :aria-busy="busy || undefined"
    :class="['inline-flex items-center justify-center gap-2 rounded-control whitespace-nowrap select-none transition-[transform,background-color] duration-100 ease-out active:scale-[0.97]', V[variant], S[size], off() && 'opacity-55 active:scale-100']"
    @click="(e) => (off() ? e.preventDefault() : emit('click', e))">
    <Loader2 v-if="busy" class="size-4 animate-spin" aria-hidden="true" /><slot />
  </button>
</template>
```

Field: a `<slot :id :aria-describedby :aria-invalid>` scoped slot replaces the render prop; Sheet: `<Teleport to="body">` + the same Esc / focus-return logic in `watch(open)`; More: the same `<details>` markup.
