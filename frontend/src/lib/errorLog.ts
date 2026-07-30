/**
 * The frontend's side of the durable error log (#386).
 *
 * The browser has no filesystem, so every runtime failure it can catch is shipped
 * to the backend (`api.logClientError`) to be appended to the open project's
 * `errors.log`. Two entry points feed it:
 *
 *  - `reportClientError`, called from the app's single `run()` funnel — the path
 *    every user action's failure already collapses through; and
 *  - the global `error` / `unhandledrejection` listeners installed by
 *    `installGlobalErrorLogging`, which catch the failures that never reach
 *    `run()` (an uncaught render error, a dropped promise in an effect).
 *
 * Reporting is always fire-and-forget and never throws: `api.logClientError`
 * swallows its own transport errors, and nothing here adds a way to fail.
 */
import { api, type ClientErrorReport } from "@/lib/api";

/** Normalise any thrown value into a report and ship it. Never throws. */
export function reportClientError(cause: unknown, context?: string): void {
  const report: ClientErrorReport = {
    message: cause instanceof Error ? cause.message : String(cause),
    detail: cause instanceof Error ? cause.stack : undefined,
    context,
  };
  void api.logClientError(report);
}

let installed = false;

/**
 * Route uncaught errors and unhandled promise rejections into the log. Idempotent
 * — safe to call once on mount; a second call is a no-op.
 */
export function installGlobalErrorLogging(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", (event) => {
    reportClientError(event.error ?? event.message, "window.onerror");
  });
  window.addEventListener("unhandledrejection", (event) => {
    reportClientError(event.reason, "unhandledrejection");
  });
}
