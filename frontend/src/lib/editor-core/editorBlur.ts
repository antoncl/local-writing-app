// TipTap's `onBlur` is a raw DOM listener, so it runs inside whatever Svelte
// reaction is active when the browser fires `blur`. When an `{#if}`/`{#each}`/
// `{#key}` block tears down a subtree holding a FOCUSED editor, Chrome fires
// `blur` synchronously inside that block effect, and a `$state` write there
// throws `state_unsafe_mutation` — in production builds too (#2461).
//
// Svelte runs its own `onblur=` handlers outside any reaction; this gives a
// TipTap blur handler the same footing. `untrack` is the public way to say
// "this write is not part of the running reaction", and it stays synchronous —
// deferring to a microtask instead could land the hide AFTER a quick refocus.
import { untrack } from "svelte";

/** Wrap a TipTap `onBlur` callback so its state writes are safe however the
 *  blur was caused. */
export function onEditorBlur(handler: () => void): () => void {
  return () => untrack(handler);
}
