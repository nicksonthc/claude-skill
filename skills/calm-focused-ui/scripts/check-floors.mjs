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
