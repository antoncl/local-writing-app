// TipTap's event callbacks (onBlur, onUpdate, onTransaction, …) are raw DOM-
// driven, so they run inside whatever Svelte reaction is active when the
// browser fires the underlying event. When an `{#if}`/`{#each}`/`{#key}` block
// tears down a subtree holding a FOCUSED editor — or a focused node-view input
// like the interiority textarea, whose blur write-back dispatches a
// transaction — Chrome fires `blur` synchronously inside that block effect,
// and a `$state` write there throws `state_unsafe_mutation`, in production
// builds too (#2461).
//
// Svelte runs its own `on…=` handlers outside any reaction; this gives a TipTap
// callback the same footing. `untrack` is the public way to say "this write is
// not part of the running reaction", and it stays synchronous — deferring to a
// microtask instead could land a hide AFTER a quick refocus.
import { untrack } from "svelte";

/** Wrap a TipTap editor callback so its state writes are safe however the
 *  event behind it was caused. Wrap every callback that writes state. */
export function editorCallback<A extends unknown[]>(handler: (...args: A) => void): (...args: A) => void {
  return (...args) => untrack(() => handler(...args));
}
