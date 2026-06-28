import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

// Read directly by svelte-check (and by the Svelte language server / IDE).
// vite.config.js still owns build-time plugin wiring; this file is the
// canonical source of preprocess + compile options that svelte-check needs.
export default {
  preprocess: vitePreprocess(),
};
