<script lang="ts">
  // The in-app guide viewer (#1271). Renders the bundled first-party guides
  // (generated from docs/ by scripts/gen_guides.py) as a reading surface inside
  // a region. Guides are trusted first-party markdown, so a plain parse is
  // enough — no sanitiser (that is the untrusted-chat path, chatMessageRender).
  //
  // Own Marked instance (defaults: GFM on), not the shared global singleton, so
  // guide rendering is immune to any global marked config elsewhere — the same
  // isolation chatMessageRender uses.
  import { Marked } from "marked";

  import { guides, type Guide } from "@/lib/generated/guides";

  const md = new Marked();

  let selectedId = $state(guides[0]?.id ?? "");
  const selected = $derived<Guide | undefined>(
    guides.find((guide) => guide.id === selectedId) ?? guides[0],
  );
  const html = $derived(selected ? (md.parse(selected.markdown) as string) : "");

  function slugify(text: string): string {
    return text
      .toLowerCase()
      .trim()
      .replace(/[^\w]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  // A rendered guide link must never navigate the whole app away (#1285). This
  // action intercepts clicks on the prose and routes them: `#guide:<id>` switches
  // guide, `#anchor` scrolls to the heading whose text matches, an external URL
  // opens in a new tab, and anything else (a relative doc path) is neutralised.
  function guideLinks(node: HTMLElement) {
    const onClick = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement).closest("a");
      if (!anchor) return;
      event.preventDefault();
      const href = anchor.getAttribute("href") ?? "";
      if (href.startsWith("#guide:")) {
        const id = href.slice("#guide:".length);
        if (guides.some((guide) => guide.id === id)) selectedId = id;
      } else if (href.length > 1 && href.startsWith("#")) {
        const slug = href.slice(1);
        const target = [...node.querySelectorAll("h1, h2, h3, h4")].find(
          (heading) => slugify(heading.textContent ?? "") === slug,
        );
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (/^https?:\/\//.test(href)) {
        window.open(href, "_blank", "noopener,noreferrer");
      }
    };
    node.addEventListener("click", onClick);
    return { destroy: () => node.removeEventListener("click", onClick) };
  }
</script>

<div class="guide-view">
  {#if guides.length === 0}
    <p class="guide-empty">No guides are bundled yet.</p>
  {:else}
    {#if guides.length > 1}
      <nav class="guide-nav" aria-label="Guides">
        {#each guides as guide (guide.id)}
          <button
            type="button"
            class="guide-nav-item"
            class:active={guide.id === selected?.id}
            aria-current={guide.id === selected?.id ? "page" : undefined}
            onclick={() => (selectedId = guide.id)}
          >{guide.title}</button>
        {/each}
      </nav>
    {/if}
    <article class="guide-prose" use:guideLinks>
      <!-- eslint-disable-next-line svelte/no-at-html-tags — trusted first-party guide markdown -->
      {@html html}
    </article>
  {/if}
</div>

<style>
  .guide-view {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }

  .guide-nav {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-1);
    padding: var(--sp-2) var(--sp-3);
    border-bottom: 1px solid var(--border);
  }

  .guide-nav-item {
    font-family: var(--sans);
    font-size: var(--fs-sm);
    color: var(--text-2);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    padding: var(--sp-1) var(--sp-2);
    cursor: pointer;
  }
  .guide-nav-item:hover {
    background: var(--inset);
    color: var(--text);
  }
  .guide-nav-item.active {
    background: var(--inset);
    color: var(--text);
  }

  .guide-empty {
    padding: var(--sp-4);
    font-family: var(--sans);
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  /* The reading surface — serif, the "work" face (design-language §identity). */
  .guide-prose {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    box-sizing: border-box;
    width: 100%;
    max-width: 72ch;
    margin: 0 auto;
    padding: var(--sp-5);
    font-family: var(--serif);
    font-size: var(--fs-prose);
    line-height: 1.6;
    color: var(--text);
  }

  /* Rendered markdown arrives via {@html}, so it is styled through :global()
     descendants of the scoped .guide-prose parent. */
  .guide-prose :global(h1) {
    margin: 0 0 var(--sp-3);
    font-size: var(--fs-2xl);
    font-weight: 600;
  }
  .guide-prose :global(h2) {
    margin: var(--sp-5) 0 var(--sp-2);
    font-size: var(--fs-xl);
    font-weight: 600;
  }
  .guide-prose :global(h3) {
    margin: var(--sp-4) 0 var(--sp-2);
    font-size: var(--fs-lg);
    font-weight: 600;
  }
  .guide-prose :global(h1:first-child),
  .guide-prose :global(h2:first-child) {
    margin-top: 0;
  }
  .guide-prose :global(p) {
    margin: 0 0 var(--sp-3);
  }
  .guide-prose :global(ul),
  .guide-prose :global(ol) {
    margin: 0 0 var(--sp-3) var(--sp-4);
    padding: 0;
  }
  .guide-prose :global(li) {
    margin: 0 0 var(--sp-1);
  }
  .guide-prose :global(a) {
    color: var(--accent-emphasis);
    text-decoration: underline;
  }
  .guide-prose :global(code) {
    padding: 0.1em 0.35em;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    background: var(--inset);
    border-radius: var(--r-sm);
  }
  .guide-prose :global(pre) {
    margin: 0 0 var(--sp-3);
    padding: var(--sp-3);
    overflow-x: auto;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    background: var(--inset);
    border-radius: var(--r-md);
  }
  .guide-prose :global(pre code) {
    padding: 0;
    background: transparent;
  }
  .guide-prose :global(blockquote) {
    margin: 0 0 var(--sp-3);
    padding-left: var(--sp-3);
    color: var(--text-2);
    border-left: 3px solid var(--border);
  }
  .guide-prose :global(table) {
    margin: 0 0 var(--sp-3);
    font-family: var(--sans);
    font-size: var(--fs-sm);
    border-collapse: collapse;
  }
  .guide-prose :global(th),
  .guide-prose :global(td) {
    padding: var(--sp-1) var(--sp-2);
    text-align: left;
    border: 1px solid var(--border);
  }
  .guide-prose :global(hr) {
    margin: var(--sp-4) 0;
    border: none;
    border-top: 1px solid var(--border);
  }
</style>
