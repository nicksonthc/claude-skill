import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// base './' = the dist folder works from any sub-path (static host, S3, nginx location, GitHub Pages).
// Need ONE file anyway? npm i -D vite-plugin-singlefile and add singlefile() to plugins.
export default defineConfig({ base: './', plugins: [react()] });
