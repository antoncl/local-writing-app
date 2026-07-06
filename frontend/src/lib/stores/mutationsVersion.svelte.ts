// Cross-pane mutations freshness signal (#63, ADR-0014). Mutations live in
// scene bodies and every reader (lore-card timeline, effective-name matcher,
// effective-state scrub) derives from the backend index — this counter owns NO
// mutation state, it is just an invalidation tick. Bumped on a scene save that
// could change the index (the saved scene carries mutation markers before or
// after the edit); readers key their fetch effects on `mutationsVersion.value`
// so authoring in one pane refreshes an open lore card in another.
//
// Rune singleton (mirrors confirmService) rather than a writable so
// .svelte.ts rune modules can read it reactively inside $effect.

class MutationsVersionSignal {
  value = $state(0);

  bump(): void {
    this.value += 1;
  }
}

export const mutationsVersion = new MutationsVersionSignal();

// A scene participates in the mutations index iff its body holds at least one
// mutation marker comment (start or close — both begin `mutate:`). Saves of
// marker-free scenes that stay marker-free can never change the index, so
// they don't bump.
export function bodyHasMutationMarkers(body: string): boolean {
  return /<!--\s*mutate:/.test(body);
}
