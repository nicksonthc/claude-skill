# Stacks: scaffold, build, host

Both stacks share `templates/shared/` (core, components, sim, experiment) and `templates/tools/check.mjs`.

| | Standalone HTML | React + three.js (R3F) |
|---|---|---|
| Delivered as | one `.html` (~0.6 MB, three.js inlined) | `dist/` folder (or one file with `vite-plugin-singlefile`) |
| Opened by | double-click, email (zip it — mail filters block `.html`), offline | URL on a web server |
| UI code | vanilla DOM (`ui.js`) | React components (`App.jsx`) |
| Best for | proposals, customer demos, sharing a result | long-lived tools, embedding in a web app, live data later |
| Proven on | three 0.170, esbuild 0.25 | three 0.170, @react-three/fiber 8.17, React 18.3, Vite 5.4 |

## Scaffold
```bash
SK=~/.claude/skills/process-sim-3d/templates
# standalone
mkdir my-sim && cd my-sim && cp -R $SK/standalone/. . && mkdir -p src tools && cp -R $SK/shared/. src/ && cp $SK/tools/check.mjs tools/
npm install && npx playwright install chromium && node build.mjs && node tools/check.mjs run
# React
mkdir my-sim && cd my-sim && cp -R $SK/r3f/. . && mkdir -p tools && cp -R $SK/shared/. src/ && cp $SK/tools/check.mjs tools/
npm install && npx playwright install chromium && npm run build && (npm run preview &) && SIM_URL=http://localhost:4173/ node tools/check.mjs run
```
Then replace the demo: `src/sim/spec.js` (spec), `src/sim/world.js` (geometry placement), `src/sim/sim.js`
(control logic). `core/`, `components/`, `experiment.js`, the shells and `check.mjs` stay as they are.

React specifics: the world + sim live in refs, `useFrame` steps them; the render callback has priority 1 so
it can skip drawing while experiments run; panels poll `sim.status()` ~9×/s. Add drei / postprocessing only
when a feature needs it.

TypeScript: rename files to `.ts/.tsx` and type the module boundaries ([spec-schema.md](spec-schema.md));
esbuild and Vite compile TS without config. Add `"typescript"` and run `tsc --noEmit` as a check.

## Build
- Standalone: `node build.mjs [out.html]` — esbuild bundles `src/main.js`, the result is inlined into
  `index.template.html`. Build previews to a different file name while someone has the main one open.
- React: `npm run build` → `dist/` (relative `base: './'`, works from any sub-path).

## Hosting (React; let the engineer choose)
| Option | How |
|---|---|
| Any static web server (nginx, Apache, IIS) | copy `dist/` to a folder it serves |
| S3 + CloudFront / Azure Static Web Apps / GCS | upload `dist/`; no server code needed |
| GitHub Pages | push `dist/` to a `gh-pages` branch or use the Pages action |
| Netlify / Vercel | point at the repo, build `npm run build`, output `dist` |
| No hosting | `vite-plugin-singlefile` → one HTML, same as standalone |
Opening `dist/index.html` from disk does not work (ES modules over `file://` are blocked) — that is what the
standalone stack or the single-file build is for.
