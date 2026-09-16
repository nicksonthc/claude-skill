# Reference: bilingual copy store

Copy-paste building blocks. Genericized from a two-language (English/Chinese)
React + Zustand + Vite app; the pattern doesn't depend on that stack — swap
Zustand for any store, `useEffect` for whatever mount hook the framework
gives.

## 1. The language field, on the app's main store

Put this on whatever store the app already shares across components — do not
create a separate "i18n store." Language is app state like any other.

```ts
// src/store/useAppStore.ts
import { create } from 'zustand';

export type Language = 'en' | 'zh';

export interface AppState {
  language: Language;
  toggleLanguage: () => void;
  // ...the rest of the app's state
}

const LANGUAGE_KEY = 'app-language'; // pick a namespaced key for the real app

const storedLanguage = (): Language => {
  try {
    return localStorage.getItem(LANGUAGE_KEY) === 'zh' ? 'zh' : 'en';
  } catch {
    return 'en'; // private browsing / storage disabled: silently falls back
  }
};

export const useAppStore = create<AppState>()((set) => ({
  language: storedLanguage(),
  toggleLanguage: () =>
    set((s) => {
      const language: Language = s.language === 'en' ? 'zh' : 'en';
      try {
        localStorage.setItem(LANGUAGE_KEY, language);
      } catch {
        /* choice just doesn't persist */
      }
      return { language };
    }),
  // ...
}));
```

## 2. The copy dictionary

One file. Both language objects are written together, key by key, so nothing
is forgotten and both are visually easy to diff against each other.

```ts
// src/lib/i18n.ts
import { useAppStore, type Language } from '../store/useAppStore';

export const copy = {
  en: {
    brandName: 'MY APP',
    save: 'Save',
    // Text that wraps across a <br/> or two <p> lines: an array, not one
    // long string with an embedded newline (JSX doesn't render \n anyway).
    titleLines: ['Line one', 'Line two'],
    // Nested groups read naturally at the call site: t.views.overview
    views: { overview: 'Overview', detail: 'Detail' },
  },
  zh: {
    brandName: '我的应用',
    save: '保存',
    titleLines: ['第一行', '第二行'],
    views: { overview: '概览', detail: '详情' },
  },
} satisfies Record<Language, unknown>;

export type Copy = (typeof copy)['en'];

export const useCopy = (): Copy => copy[useAppStore((s) => s.language)];

export const htmlLang = (language: Language) => (language === 'zh' ? 'zh-CN' : 'en');
```

Usage in any component, on any page of the app:

```tsx
import { useCopy } from '../lib/i18n';

export function Header() {
  const t = useCopy();
  return <button>{t.save}</button>;
}
```

## 3. `<html lang>`, once per page's root component

```tsx
import { useEffect } from 'react';
import { htmlLang } from '../lib/i18n';
import { useAppStore } from '../store/useAppStore';

function Root() {
  const language = useAppStore((s) => s.language);
  useEffect(() => {
    document.documentElement.lang = htmlLang(language);
  }, [language]);
  // ...
}
```

## 4. The toggle control

Match whatever button/control convention the app already uses; the essential
part is the `aria-label` naming the *action* (switch to X), not repeating the
visible label (which is conventionally the *other* language's name for
itself, e.g. the button says "中文" while the UI is in English):

```tsx
const t = useCopy();
const toggleLanguage = useAppStore((s) => s.toggleLanguage);

<button onClick={toggleLanguage} aria-label={t.switchLanguage}>
  {t.toggle /* e.g. en: '中文', zh: 'EN' */}
</button>
```

## 5. Typed keys for dynamic/status text

Any store field that holds transient user-facing text — a loading message, an
error banner, a toast — should hold a **key into `Copy`**, not the rendered
string, or the text freezes in whichever language was active when it was set.

```ts
// src/feature/types.ts
import type { Copy } from '../lib/i18n';

export type StatusKey = Extract<
  keyof Copy,
  'loadingCollection' | 'loadingItem' | 'unavailable' | 'itemError'
>;
```

```ts
// src/feature/useFeatureStore.ts
status: StatusKey | null;
setStatus: (status: StatusKey | null) => void;
// ... status: 'loadingCollection' as the initial value, not a string literal
```

```tsx
// component
const t = useCopy();
const status = useFeatureStore((s) => s.status);
{status && <div role="status">{t[status]}</div>}
```

The `Extract<keyof Copy, ...>` (rather than a bare string-literal union)
means renaming or removing a key in `copy` breaks this type too, so a stale
status key can't silently compile.

## 6. Translating data the app doesn't author

For strings that arrive in JSON/data produced by something outside the copy
file — a build step, a CMS export, a generation pipeline — do **not** add a
translated field to that data file if anything regenerates it; the next run
overwrites hand-added fields. Keep an overlay keyed by the data's own id, in
the copy module, with the data's own field as the fallback:

```ts
// src/lib/i18n.ts (same file as `copy`)
export const itemDescriptionsZh: Record<string, string> = {
  'item-1': '……',
  // add ids as they're translated; untranslated ids fall through to English
};

export const itemDescription = (id: string, description: string, language: Language): string =>
  language === 'zh' ? (itemDescriptionsZh[id] ?? description) : description;
```

```tsx
<p>{itemDescription(item.id, item.description, language)}</p>
```

## 7. Verification checklist

- [ ] `tsc --noEmit` (or the app's typecheck script) passes.
- [ ] Every `data-*` attribute, element `id`, and any string an existing
      test/smoke script matches against is unchanged from before the
      translation pass.
- [ ] Load the page with a clean `localStorage` (the default-language state)
      and confirm existing text-matching assertions still pass.
- [ ] Toggle the language in a real browser (or a quick Playwright script:
      `page.locator('...toggle...').click()`), screenshot both states, and
      **read the screenshots** — look for wrapped or clipped text, since a
      translated string can be a very different length from the English one.
- [ ] Grep the changed files afterward for any quoted string still assigned
      directly into JSX text/`aria-*`/`alt`/`placeholder` — a leftover
      hardcoded string is the most common miss.
