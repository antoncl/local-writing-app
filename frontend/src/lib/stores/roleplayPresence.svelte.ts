// Per-pane "this scene's editor holds roleplay beats" (ADR-0070 S3). A projection
// of the editor surface — surfaced from ProseBodyView → NodeEditor
// (onInteriorityChange) — so App can gate the ≡-menu "Finalize roleplay…" action
// without editorPanes carrying editor-content state. Keyed by editor pane id; a
// closed pane's stale entry is harmless (only the focused pane is ever read).
class RoleplayPresence {
  #byPane = $state<Record<string, boolean>>({});

  set(paneId: string, hasBeats: boolean): void {
    if (Boolean(this.#byPane[paneId]) === hasBeats) return;
    this.#byPane = { ...this.#byPane, [paneId]: hasBeats };
  }

  has(paneId: string | null | undefined): boolean {
    return paneId ? Boolean(this.#byPane[paneId]) : false;
  }
}

export const roleplayPresence = new RoleplayPresence();
