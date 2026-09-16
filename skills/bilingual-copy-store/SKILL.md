---
name: bilingual-copy-store
description: Add or extend a two-language (or N-language) UI in a React + Zustand app with one shared copy dictionary, a language toggle that persists and works across every page of a multi-entry Vite app, typed keys for dynamic/status text, and a safe way to translate strings that live in generator-owned JSON. Use when asked to "add Chinese/Mandarin/a second language", "translate this page/component", "add an i18n toggle", or when a new page/feature is added to an app that already has one and needs to match it.
---

# Bilingual copy store

A minimal i18n approach for a small-to-medium React app: no i18n library, one
plain object literal per language, one Zustand field for the current
language, one hook to read it. Scales to a multi-page (multi-entry-point)
Vite app because the store — not a React context — is the source of truth,
so every page that imports the same store module stays in sync automatically.

## The shape

```ts
// store: one field + one action, persisted
export type Language = 'en' | 'zh';
interface AppState {
  language: Language;
  toggleLanguage: () => void;
}
const LANGUAGE_KEY = 'app-language';
const storedLanguage = (): Language => {
  try { return localStorage.getItem(LANGUAGE_KEY) === 'zh' ? 'zh' : 'en'; }
  catch { return 'en'; } // private browsing: falls back, doesn't throw
};
// in create(): language: storedLanguage(),
// toggleLanguage: () => set(s => {
//   const language = s.language === 'en' ? 'zh' : 'en';
//   try { localStorage.setItem(LANGUAGE_KEY, language); } catch {}
//   return { language };
// }),
```

```ts
// copy: one object, `satisfies` catches a key present in one language and
// missing in the other
export const copy = {
  en: { brandName: 'JIANGNAN', save: 'Save view', /* ... */ },
  zh: { brandName: '烟雨江南', save: '保存画面', /* ... */ },
} satisfies Record<Language, unknown>;
export type Copy = (typeof copy)['en'];
export const useCopy = (): Copy => copy[useAppStore(s => s.language)];
```

Every component calls `const t = useCopy()` and reads `t.someKey` — never a
raw string literal for user-facing text. See `REFERENCE.md` for the full
template including nested objects (`t.views.village`) and array values
(`t.titleLines[0]`, for text that's broken across a `<br />`).

## Workflow

1. **Find the existing store and copy file** before adding a second one. A
   second page/entry point in the same app (e.g. `inspector.html` next to
   `index.html` in a multi-page Vite build) should `import` the *same*
   `useAppStore`/`copy` module the first page uses, not fork its own — that's
   what makes the language choice carry over when the user navigates between
   pages, and it's one `localStorage` key instead of several going out of
   sync.
2. **Inventory every string** in the target file(s): headings, button/link
   text, `aria-label`/`aria-live` text, `alt` text, placeholder text, and any
   string passed to a status/toast/error state. Grep for quoted text near
   JSX return statements — don't rely on skimming.
3. **Add matching keys to both language blocks in the same pass** — write the
   English key and its Chinese value together so nothing is forgotten, and
   run the typechecker after (`satisfies Record<Language, unknown>` plus
   `Copy = typeof copy['en']` means a shape mismatch between languages is
   usually a real TS error somewhere it's consumed, but only if something
   consumes the mismatched field — don't rely on it alone, review both
   objects side by side).
4. **Dynamic/status text becomes a typed key, not a string.** If a store
   holds transient text (`"Loading…"`, `"Could not load. Retry."`), storing
   the *rendered string* freezes it at whichever language was active when it
   was set — switching languages afterward leaves stale text on screen. Store
   a key instead and render `t[key]` at read time:
   ```ts
   type StatusKey = Extract<keyof Copy, 'loadingCollection' | 'modelError'>;
   // store: status: StatusKey | null
   // component: {status && <div>{t[status]}</div>}
   ```
5. **Generator-owned data needs a side table, not an edited field.** Text
   that ships in JSON/data produced by a build step, a CMS export, or (as in
   the source project) a headless-3D-asset pipeline gets overwritten on the
   next regeneration — a hand-added `descriptionZh` field on that JSON dies
   silently. Keep a `Record<id, string>` translation overlay in the copy
   module instead, keyed by the same id the data uses, and fall back to the
   data's own (source-language) field for any id not yet translated:
   ```ts
   export const assetDescriptionsZh: Record<string, string> = { 'wupeng-boat': '...' };
   export const assetDescription = (id: string, fallback: string, lang: Language) =>
     lang === 'zh' ? (assetDescriptionsZh[id] ?? fallback) : fallback;
   ```
6. **Add the toggle control** to the page if it doesn't have one yet — reuse
   the existing button/style convention from the page that already has it
   rather than inventing a new visual language for it.
7. **Verify in both languages.** Run the typechecker, then load the page,
   flip the toggle, and re-run any existing screenshot/e2e check — capture
   one screenshot per language if the check doesn't already. Read the
   screenshots; a translated string that's twice as long as the English one
   is a common source of wrapped/clipped layout that typechecking can't
   catch.

## Pitfalls

- **Selectors must survive translation.** `data-*` attributes, element `id`s,
  and any value an existing test/smoke script matches on (`page.locator('[data-view="front"]')`,
  a regex against visible text like `/Triangles/`) must keep their original
  value. Translate the *displayed* label; leave the attribute/test string in
  whatever language the tests already assume (usually the store's default
  language, since a fresh page load with empty `localStorage` starts there).
- **Copy-pasting a key onto a second element silently mislabels it.** Two
  different `aria-label`s (e.g. "asset collection" vs. "camera views") are
  two different keys even if translating one first seems to fit both —
  giving the second element the first element's key means it renders wrong
  text in production with no type error to catch it.
- **Some fields are deliberately already bilingual — don't double-translate
  them.** Data that already carries both languages side by side by design
  (e.g. an English title next to its own native-language name, shown
  together regardless of UI language) is not a string to route through the
  copy dictionary; translating it again duplicates or contradicts the
  existing pairing.
- **Set `<html lang>`.** `document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'` in
  a `useEffect` keyed on `language`, on every page — screen readers and
  find-in-page both use it.
- **A toggle button needs an `aria-label` in the *other* language** — its own
  visible text is normally the destination language's name for itself (e.g.
  the button reads "中文" while the UI is in English), so its accessible
  name has to say what clicking it does, not name the button's own label.
