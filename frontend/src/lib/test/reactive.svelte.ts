// Wrap a plain fixture object in a `$state` proxy so a component's nested
// `bind:` into it (e.g. `bind:value={draft.display.ui_scale}`) is reactive
// under test. Without this, passing a plain object as a `$bindable` prop makes
// Svelte 5 print `binding_property_non_reactive` — harmless (the real app
// always passes `$state`-backed data) but noisy. Runes only compile in a
// `.svelte.[jt]s` module, so a plain `*.test.ts` can't wrap fixtures itself.
export function reactive<T>(value: T): T {
  const state = $state(value);
  return state;
}
