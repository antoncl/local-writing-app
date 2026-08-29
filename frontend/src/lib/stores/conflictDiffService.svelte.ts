// Diff-preview conflict resolver (ADR-0077 rung 3, #1638). The "changed on disk"
// dialog, upgraded from confirmService's blind text prompt to a modal that SHOWS
// the on-disk-vs-local diff before the author chooses. confirmService is
// text-only (it renders fixed strings), so this is its rich-content sibling: one
// app shell mounts one ConflictDiffModal bound to `active`.
//
// Singleton with a rune field, same shape and rationale as confirmService — a
// controller with traceable methods, not a writable store. The resolutions
// (onSelect) are supplied per caller and run through App's `run()` wrapper,
// injected as `onRun` in onMount so this service stays ignorant of App's error
// state.

export type ConflictDiffAction = {
  label: string;
  // Danger styling for the overwrite / discard side.
  destructive?: boolean;
  onSelect: () => Promise<void> | void;
};

export type ConflictDiffRequest = {
  // The document's title, for the header.
  title: string;
  // The two prose bodies to diff: `localBody` is the warm "now" (your version),
  // `onDiskBody` the cool "was". When both are null or equal the conflict is
  // field-only (metadata / status) — the modal shows a note, not an empty diff.
  localBody: string | null;
  onDiskBody: string | null;
  // The context's resolutions, right-aligned; the LAST is the primary. Every path
  // out of the modal is one of these (there is no separate backdrop/Esc dismissal —
  // the app's modals are button-only, matching ConfirmModal), so the "resolve later"
  // escape is itself an action: autosave passes Keep editing / Overwrite, close passes
  // Cancel / Discard and close / Overwrite and close.
  actions: ConflictDiffAction[];
};

class ConflictDiffService {
  // The pending conflict, or null when no modal is showing. Read by ConflictDiffModal.
  active = $state<ConflictDiffRequest | null>(null);

  // Runs a resolution with the host's error handling. Default just invokes it;
  // App overrides this with its own `run()` in onMount (same as confirmService).
  onRun: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };

  request(options: ConflictDiffRequest) {
    this.active = options;
  }

  // Run one action's resolution and close.
  select(action: ConflictDiffAction) {
    this.active = null;
    void this.onRun(async () => {
      await action.onSelect();
    });
  }
}

export const conflictDiffService = new ConflictDiffService();
