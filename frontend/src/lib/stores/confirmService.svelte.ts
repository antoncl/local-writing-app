// Destructive-action confirmation service — owns the active confirm-modal
// request plus the per-operation "don't show this again" suppression list
// (localStorage). Extracted from App.svelte (#14 P0), which was a god-shell
// carrying this alongside the editor/autosave/schema concerns.
//
// Singleton: one app shell mounts one ConfirmModal, so a single module-level
// instance with a rune field is correct and idiomatic. Not a writable store —
// a controller with traceable methods (see docs/frontend-architecture.md).
//
// The confirm action itself (onConfirm) is supplied by each caller and runs
// through App's `run()` error/status wrapper, injected as `onRun` in onMount so
// this service stays ignorant of App's error state.

export type ConfirmationRequest = {
  title: string;
  message: string;
  details?: string[];
  confirmLabel: string;
  destructive: boolean;
  cannotBeUndone?: boolean;
  dontShowAgainKey?: string;
  onConfirm: () => Promise<void>;
};

const SUPPRESS_PREFIX = "confirmSuppress:";

class ConfirmService {
  // The pending confirmation, or null when no modal is showing. Read by the
  // ConfirmModal markup in App.
  active = $state<ConfirmationRequest | null>(null);

  // Runs a confirm action with the host's error handling. Default just invokes
  // it; App overrides this with its own `run()` in onMount.
  onRun: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };

  #isSuppressed(key: string): boolean {
    try {
      return localStorage.getItem(SUPPRESS_PREFIX + key) === "1";
    } catch {
      return false;
    }
  }

  #suppress(key: string) {
    try {
      localStorage.setItem(SUPPRESS_PREFIX + key, "1");
    } catch {
      // ignore storage failures — worst case, we ask again next time.
    }
  }

  // Gate a destructive action behind the confirm modal, honouring a
  // per-op-type "don't show again" suppression. If suppressed, runs the action
  // immediately; otherwise opens the modal.
  request(options: ConfirmationRequest) {
    if (options.dontShowAgainKey && this.#isSuppressed(options.dontShowAgainKey)) {
      void this.onRun(options.onConfirm);
      return;
    }
    this.active = options;
  }

  // Confirm handler for the modal's primary button. Closes the modal, records
  // the suppression if requested, then runs the action.
  async resolve(dontShowAgain = false) {
    const current = this.active;
    if (!current) return;
    this.active = null;
    if (dontShowAgain && current.dontShowAgainKey) {
      this.#suppress(current.dontShowAgainKey);
    }
    await this.onRun(current.onConfirm);
  }

  // Dismiss without running the action (cancel / backdrop).
  dismiss() {
    this.active = null;
  }
}

export const confirmService = new ConfirmService();
