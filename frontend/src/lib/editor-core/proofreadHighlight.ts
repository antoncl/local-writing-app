// Proofreading (ADR-0102 §3): the one layer that draws findings in prose, and
// the one popover that offers their fixes. Every engine's findings come through
// here; none gets its own layer.
//
// The plugin state is a DecorationSet, mapped through edits. A refresh rebuilds
// it from the lens's cache: a block whose text has findings cached shows them,
// and a block still being linted keeps its mapped underlines until its result
// arrives (no flicker while typing). Refreshes are scheduled, never run inside
// a view update: after an edit (debounced), when a lint lands, and when the
// lens says findings may have changed.
//
// A fix is an ordinary edit: one transaction replacing the finding's text, so
// undo, the save and marks behave as they do for typing (`insertText` takes the
// marks at the position, like a keystroke). Harper's `applySuggestion` is not
// used: it returns the whole text, and putting a whole block back would drop
// its marks.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, type EditorState } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";
import { anchoredPopover } from "@/lib/actions/anchoredPopover";
import { docRange, textBlocks, type BlockText } from "@/lib/proofread/blockText";
import { isSpelling, type Finding } from "@/lib/proofread/findings";
import type { ProofreadLens } from "@/lib/stores/proofreading.svelte";
import "@/lib/editor-core/proofreadHighlight.css";

export const MARK_CLASS = "proofread-mark";
const POPOVER_CLASS = "proofread-popover";
/** Quiet after typing before the changed blocks are linted. */
export const EDIT_DEBOUNCE_MS = 600;
/** Coalesce a burst of landing lints into one redraw. */
const RESULT_DEBOUNCE_MS = 40;

/** A fix in document positions relative to its finding's start, so it stays
 *  right while the decoration is mapped through edits elsewhere. */
type RelativeFix = { label: string; from: number; to: number; insert: string };

/** What a finding's decoration carries. */
export type FindingSpec = {
  finding: Finding;
  /** The text the finding was made for; a fix applies only while it is unchanged. */
  problem: string;
  size: number;
  fixes: RelativeFix[];
};

export type ProofreadOptions = {
  lens: ProofreadLens | null;
  /** Whether this editor proofreads at all (step 1: scene prose only). */
  enabled: () => boolean;
};

const pluginKey = new PluginKey<DecorationSet>("proofreadHighlight");

/** The decorations for one block's findings. */
export function findingDecorations(block: BlockText, findings: Finding[]): Decoration[] {
  const decorations: Decoration[] = [];
  for (const finding of findings) {
    if (finding.to <= finding.from || finding.to > block.text.length) continue;
    const range = docRange(block, finding.from, finding.to);
    const fixes = finding.fixes.map((fix) => {
      const at = docRange(block, fix.from, fix.to);
      return { label: fix.label, from: at.from - range.from, to: at.to - range.from, insert: fix.insert };
    });
    const spec: FindingSpec = {
      finding,
      problem: block.text.slice(finding.from, finding.to),
      size: range.to - range.from,
      fixes,
    };
    const kindClass = isSpelling(finding) ? "proofread-spelling" : "proofread-issue";
    decorations.push(
      Decoration.inline(range.from, range.to, { class: `${MARK_CLASS} ${kindClass}` }, { proofread: spec }),
    );
  }
  return decorations;
}

/** The finding decoration covering document position `pos`, if any. */
export function findingAt(state: EditorState, pos: number): Decoration | null {
  const set = pluginKey.getState(state);
  if (!set) return null;
  const hits = set.find(pos, pos + 1, (spec) => Boolean(spec.proofread));
  return hits.find((d) => d.from <= pos && pos < d.to) ?? null;
}

/** Apply `fix` of the finding decorated by `deco`. False, changing nothing,
 *  when the text under it changed since the finding was made. */
export function applyFix(view: EditorView, deco: Decoration, fix: RelativeFix): boolean {
  const spec = (deco.spec as { proofread: FindingSpec }).proofread;
  const { doc } = view.state;
  if (deco.to - deco.from !== spec.size || doc.textBetween(deco.from, deco.to) !== spec.problem) return false;
  const from = deco.from + fix.from;
  const to = deco.from + fix.to;
  const tr = fix.insert ? view.state.tr.insertText(fix.insert, from, to) : view.state.tr.delete(from, to);
  view.dispatch(tr.scrollIntoView());
  return true;
}

/** Every finding decoration's spec, in document order (tests and the e2e
 *  check read what is drawn through this). */
export function proofreadFindings(state: EditorState): FindingSpec[] {
  const set = pluginKey.getState(state);
  if (!set) return [];
  return set.find().map((d) => (d.spec as { proofread: FindingSpec }).proofread);
}

type FindingPopover = {
  readonly target: HTMLElement | null;
  show(target: HTMLElement, spec: FindingSpec, onFix: (fix: RelativeFix) => void): void;
  hide(): void;
};

function createFindingPopover(): FindingPopover {
  const el = document.createElement("div");
  el.className = POPOVER_CLASS;
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", "Proofreading");
  let target: HTMLElement | null = null;
  let placement: ReturnType<typeof anchoredPopover> | null = null;

  function hide() {
    if (!target) return;
    target = null;
    placement?.destroy();
    placement = null;
    document.removeEventListener("keydown", onKeydown, true);
    document.removeEventListener("pointerdown", onPointerDown, true);
  }
  // Escape is consumed: the keypress that closes the popover must not also
  // close the dialog or menu the editor sits in.
  function onKeydown(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    hide();
  }
  function onPointerDown(event: Event) {
    const node = event.target;
    if (!(node instanceof Node) || (!el.contains(node) && !target?.contains(node))) hide();
  }

  function render(spec: FindingSpec, onFix: (fix: RelativeFix) => void) {
    el.replaceChildren();
    const message = document.createElement("p");
    message.className = `${POPOVER_CLASS}-message`;
    message.textContent = spec.finding.message;
    el.appendChild(message);
    if (spec.fixes.length === 0) return;
    const fixes = document.createElement("div");
    fixes.className = `${POPOVER_CLASS}-fixes`;
    for (const fix of spec.fixes) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `${POPOVER_CLASS}-fix`;
      button.textContent = fix.label;
      // Keep the editor's focus and selection: the fix is an edit in it.
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => {
        hide();
        onFix(fix);
      });
      fixes.appendChild(button);
    }
    el.appendChild(fixes);
  }

  return {
    get target() {
      return target;
    },
    show(next, spec, onFix) {
      target = next;
      render(spec, onFix);
      if (placement) {
        placement.update({ anchor: next });
        return;
      }
      placement = anchoredPopover(el, { anchor: next });
      document.addEventListener("keydown", onKeydown, true);
      document.addEventListener("pointerdown", onPointerDown, true);
    },
    hide,
  };
}

export const ProofreadHighlight = Extension.create<ProofreadOptions>({
  name: "proofreadHighlight",
  addOptions() {
    return { lens: null, enabled: () => false };
  },
  addProseMirrorPlugins() {
    const options = this.options;
    const active = () => Boolean(options.lens?.active) && options.enabled();

    return [
      new Plugin<DecorationSet>({
        key: pluginKey,
        state: {
          init: () => DecorationSet.empty,
          apply: (tr, old) => {
            const next = tr.getMeta(pluginKey) as DecorationSet | undefined;
            if (next) return next;
            return tr.docChanged ? old.map(tr.mapping, tr.doc) : old;
          },
        },
        view: (view) => {
          const lens = options.lens;
          const popover = createFindingPopover();
          let timer: ReturnType<typeof setTimeout> | null = null;
          let destroyed = false;

          const schedule = (delay: number) => {
            if (destroyed) return;
            if (timer !== null) clearTimeout(timer);
            timer = setTimeout(() => {
              timer = null;
              refresh();
            }, delay);
          };

          const replace = (next: DecorationSet) => {
            view.dispatch(view.state.tr.setMeta(pluginKey, next).setMeta("addToHistory", false));
          };

          // The browser's own spellcheck would double the spelling underlines:
          // off while the lens is on, back to the editor's own setting after.
          const ownSpellcheck = view.dom.getAttribute("spellcheck");
          const syncSpellcheck = () => {
            const want = active() ? "false" : ownSpellcheck;
            if (view.dom.getAttribute("spellcheck") === want) return;
            if (want === null) view.dom.removeAttribute("spellcheck");
            else view.dom.setAttribute("spellcheck", want);
          };

          function refresh() {
            if (destroyed) return;
            syncSpellcheck();
            const current = pluginKey.getState(view.state) ?? DecorationSet.empty;
            if (!lens || !active()) {
              popover.hide();
              if (current !== DecorationSet.empty) replace(DecorationSet.empty);
              return;
            }
            const decorations: Decoration[] = [];
            for (const block of textBlocks(view.state.doc)) {
              const cached = lens.cached(block.text);
              if (cached) {
                decorations.push(...findingDecorations(block, cached));
                continue;
              }
              decorations.push(...current.find(block.start, block.end));
              lens.lint(block.text).then(
                () => schedule(RESULT_DEBOUNCE_MS),
                () => undefined,
              );
            }
            replace(DecorationSet.create(view.state.doc, decorations));
          }

          const unsubscribe = lens?.subscribe(() => schedule(0)) ?? (() => undefined);
          schedule(0);

          const openAt = (target: HTMLElement) => {
            const pos = view.posAtDOM(target, 0);
            const deco = findingAt(view.state, pos);
            if (!deco) return;
            const spec = (deco.spec as { proofread: FindingSpec }).proofread;
            popover.show(target, spec, (fix) => {
              const live = findingAt(view.state, deco.from);
              if (!live || !applyFix(view, live, fix)) schedule(0);
              view.focus();
            });
          };
          // The plugin's props can't reach this view's popover, so the click
          // listener lives here.
          const onClick = (event: MouseEvent) => {
            if (!active() || event.button !== 0) return;
            const target = (event.target as Element | null)?.closest?.(`.${MARK_CLASS}`);
            if (target instanceof HTMLElement && view.dom.contains(target)) openAt(target);
          };
          view.dom.addEventListener("click", onClick);

          return {
            update(updated, previous) {
              if (updated.state.doc !== previous.doc) {
                schedule(EDIT_DEBOUNCE_MS);
                // The underline the popover hangs from was re-rendered or edited.
                if (popover.target && !updated.dom.contains(popover.target)) popover.hide();
              }
              syncSpellcheck();
            },
            destroy() {
              destroyed = true;
              if (timer !== null) clearTimeout(timer);
              unsubscribe();
              popover.hide();
              view.dom.removeEventListener("click", onClick);
            },
          };
        },
        props: {
          decorations(state) {
            return pluginKey.getState(state) ?? DecorationSet.empty;
          },
        },
      }),
    ];
  },
});
