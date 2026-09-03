// The one and only HTTP client to the backend. Every request goes through
// `request` / `streamNdjson` below, which is what injects the open project's
// scope on the wire (`scopeHeaders`, #413) — a raw `fetch` from a component or
// store skips that and talks to the wrong project, invisibly. That boundary is
// enforced: `scripts/check_http_client.py` fails CI on any network primitive
// (`fetch` to a URL, `EventSource`, `WebSocket`, `XMLHttpRequest`, axios)
// outside this file (ADR-0056, #977). Add a method here; do not reach for the
// network anywhere else.
//
// The network primitives live here; the domain method objects that call them
// live in the sibling modules under lib/api/ and are composed into `api` in
// lib/api.ts.
import type { ChatSessionJournalEntry, ChatUsage } from "@/lib/types";

// Backend base URL. Defaults to a same-origin relative path (ADR-0072 §1): in
// the packaged product the backend serves this bundle, so `/api` reaches it
// with no baked-in address. Only the production build takes this default; both
// dev stacks bake an absolute VITE_API_BASE at build time (vite.config.js) —
// Anton's serve talks to :8787 cross-origin, `--mode claude` to its own derived
// backend port — so dev never proxies and streaming responses stay unbuffered.
export const baseUrl = import.meta.env.VITE_API_BASE ?? "/api";

// A WebSocket URL for a backend path, derived from the same base the HTTP client
// uses so both dev (an absolute cross-origin base) and the packaged app (the
// relative same-origin `/api`) reach the backend. A relative base resolves
// against the page origin; either way http(s) swaps to ws(s).
export function apiWsUrl(path: string): string {
  const url = new URL(`${baseUrl}${path}`, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

// Open the session-presence WebSocket (#1378). The raw socket primitive lives
// here with the rest of the backend transport — ADR-0056's http-client-guard
// keeps network I/O in this one module; the presence controller in
// lib/sessionPresence.ts only drives the returned socket's lifecycle.
export function openSessionPresenceSocket(): WebSocket {
  return new WebSocket(apiWsUrl("/session/live"));
}

// The open project's root, carried on every request so the backend resolves the
// request's scope from the request itself (#413 / ADR-0045) rather than from a
// process-wide record of what was last opened. Set on a successful open/create
// and overwritten on a switch (which is just another open); null before any
// project is open, so the machine-level surfaces run unbound. URL-encoded into
// the header so a non-ASCII folder name survives a latin-1 HTTP header.
//
// It is mirrored in `sessionStorage` (per browser tab) so the scope survives a
// re-instantiation of THIS module while the app stays mounted — a Vite hot update,
// or any other dev module re-eval — which would otherwise reset a bare module
// variable back to null while a project is still open and 409 "No project is open."
// the next project-scoped fetch (#965). sessionStorage is not module state, so a
// fresh instance recovers it. This is NOT the ambient current-project #413 removed:
// that was a backend process global answering "what did SOME request open"; this is
// per-tab frontend state answering "what did THIS tab open" — exactly the request's
// own scope (ADR-0045). Per-tab means a new tab correctly starts unscoped until it
// opens a project, and since the app never returns to a no-project state after the
// first open (a switch just overwrites), the stored value always names the tab's
// currently-open project.
const SCOPE_STORAGE_KEY = "lwa.projectScopeRoot";

function readStoredScopeRoot(): string | null {
  try {
    return sessionStorage.getItem(SCOPE_STORAGE_KEY);
  } catch {
    return null; // sessionStorage unavailable (some test / SSR environments)
  }
}

let projectScopeRoot: string | null = readStoredScopeRoot();

export function setProjectScopeRoot(root: string | null): void {
  projectScopeRoot = root;
  try {
    if (root === null) sessionStorage.removeItem(SCOPE_STORAGE_KEY);
    else sessionStorage.setItem(SCOPE_STORAGE_KEY, root);
  } catch {
    // sessionStorage unavailable — the module variable still carries scope for
    // this instance's lifetime; only cross-re-instantiation recovery is lost.
  }
}

export function scopeHeaders(): Record<string, string> {
  // Fall back to the stored value when the module variable was reset out from
  // under us (module re-eval) but the tab still has a project open (#965).
  const root = projectScopeRoot ?? readStoredScopeRoot();
  return root === null ? {} : { "X-Project-Root": encodeURIComponent(root) };
}

/** Error subclass that carries the raw response detail so structured callers
 * can extract fields (e.g. PreviewError's line/col). `.message` still reads as
 * a human-readable string via formatErrorDetail. */
export class HttpError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.detail = detail;
  }
}

/** A caught client-side failure shipped to the backend error log (#386).
 * `context` names where it happened; `detail` carries a stack or extra text. */
export interface ClientErrorReport {
  message: string;
  context?: string;
  detail?: string;
}

// While a page-hide flush is in progress every save PUT is marked `keepalive` so
// the browser lets an in-flight request finish even as the tab closes (#369).
// It is a transient hint, not a mode: App toggles it around the (brief) flush,
// and a keepalive request the flag catches by accident is harmless — it only
// asks the browser not to abort the request on unload. Note the ~64KB keepalive
// body cap: a very large scene save can still be dropped on a hard kill (the
// irreducible residual tracked in #455). The `visibilitychange: hidden` trigger
// covers the common case regardless, because the page is still alive then to
// complete a normal-weight request.
let keepaliveSaves = false;
export function setKeepaliveSaves(active: boolean): void {
  keepaliveSaves = active;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    keepalive: options.keepalive ?? keepaliveSaves,
    headers: {
      "Content-Type": "application/json",
      ...scopeHeaders(),
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new HttpError(
      formatErrorDetail(detail) ?? response.statusText,
      response.status,
      detail,
    );
  }
  // 204 No Content (e.g. the dedicated tag-entry delete, ADR-0082 slice 1
  // review fix; the unified `/api/nodes/{id}` delete) has no body to parse —
  // `response.json()` throws on an empty body.
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function formatErrorDetail(detail: unknown): string | null {
  // FastAPI returns plain strings for ProjectServiceError, but its 422
  // validation errors arrive as an array of {loc, msg, type} objects. Without
  // explicit handling those stringified to "[object Object]" — flatten them
  // into a human-readable form so users see what went wrong.
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const obj = item as { loc?: unknown[]; msg?: string; type?: string };
          const field = Array.isArray(obj.loc) ? obj.loc.filter((p) => p !== "body").join(".") : "";
          return field ? `${field}: ${obj.msg ?? obj.type ?? "invalid"}` : (obj.msg ?? JSON.stringify(item));
        }
        return String(item);
      })
      .join("; ");
  }
  if (typeof detail === "object") {
    // PreviewError shape: { message, line?, col? }. FastAPI validation shape:
    // { msg, loc, type }. Surface whichever is present.
    const obj = detail as { message?: string; msg?: string };
    return obj.message ?? obj.msg ?? JSON.stringify(detail);
  }
  return String(detail);
}

export type AIStreamEvent =
  | { type: "delta"; text: string }
  | { type: "thinking"; text: string }
  | {
      type: "done";
      provider: string;
      model: string;
      latency_ms: number;
      stop_reason: string | null;
      truncated: boolean;
      policy: string;
      session_id?: string;
      char_count?: number;
      usage?: ChatUsage | null;
      cost_usd?: number | null;
      journal_added?: ChatSessionJournalEntry[];
    }
  | {
      type: "error";
      error: string;
      provider: string;
      model: string;
      latency_ms: number;
      policy: string;
    };

export async function* streamNdjson(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncIterableIterator<AIStreamEvent> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...scopeHeaders() },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? response.statusText);
  }
  if (!response.body) {
    throw new Error("Streaming not supported by this response.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        let nl = buffer.indexOf("\n");
        while (nl !== -1) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (line) {
            try {
              yield JSON.parse(line) as AIStreamEvent;
            } catch {
              // Ignore malformed lines — server should never emit them, but
              // don't kill the whole stream over one bad chunk.
            }
          }
          nl = buffer.indexOf("\n");
        }
      }
      if (done) break;
    }
    const tail = buffer.trim();
    if (tail) {
      try {
        yield JSON.parse(tail) as AIStreamEvent;
      } catch {
        // ignore
      }
    }
  } finally {
    reader.releaseLock();
  }
}
