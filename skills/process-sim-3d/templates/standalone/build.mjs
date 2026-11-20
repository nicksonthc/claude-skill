// Bundles src/main.js (three.js included) and inlines it into ONE standalone HTML file:
// double-click to open, email it, works offline. `node build.mjs [out.html] [--dev]`
// Build previews to a different out path while someone has the main file open.
import { build } from 'esbuild';
import { readFileSync, writeFileSync } from 'node:fs';
const out = process.argv.slice(2).find((a) => !a.startsWith('--')) || 'simulation.html';
const r = await build({ entryPoints: ['src/main.js'], bundle: true, format: 'iife', minify: !process.argv.includes('--dev'), write: false, target: 'es2020', legalComments: 'none' });
const js = r.outputFiles[0].text.replace(/<\/script/gi, '<\\/script'); // a literal </script> inside the bundle would end the tag
writeFileSync(out, readFileSync('index.template.html', 'utf8').replace('/*__BUNDLE__*/', () => js)); // function form: $ in the bundle stays literal
console.log(out, (readFileSync(out).length / 1024).toFixed(0) + ' kB');
