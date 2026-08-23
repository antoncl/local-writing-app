/**
 * Hold a WebSocket open while this tab is open so the desktop server can quit
 * when the last tab closes (#1378).
 *
 * The installed app is a local server the user reaches in their browser; closing
 * the tab should feel like closing the app. The backend counts open presence
 * sockets and — only on a loopback desktop launch — shuts down once none remain.
 * The socket closing is what signals "tab gone": it survives background-tab
 * throttling/freezing (the browser keeps the connection) yet closes promptly on
 * a real close or reload, which a heartbeat poll can't do reliably.
 *
 * Best-effort: if the socket can't open or later drops, we reconnect with
 * backoff; a brief gap is covered by the server's grace window, and a permanent
 * failure just means the server won't auto-quit (the pre-#1378 behavior). A
 * LAN/systemd server never consults presence, so the socket is a no-op there.
 */

import { openSessionPresenceSocket } from "./api";

const MAX_RECONNECT_DELAY_MS = 15_000;

let retry = 0;
let started = false;

function connect(): void {
  let ws: WebSocket;
  try {
    ws = openSessionPresenceSocket();
  } catch {
    // Constructor can throw on a malformed URL or a blocked scheme; treat it as a
    // failed connection and back off, rather than giving up on presence entirely.
    scheduleReconnect();
    return;
  }
  ws.addEventListener("open", () => {
    retry = 0;
  });
  ws.addEventListener("close", () => {
    // On tab close the page is torn down and this timer never fires (which is the
    // point); on a mid-session drop it reconnects, well inside the server's grace.
    // Connects are serialized after a close, so there is never a second live
    // socket to track — the close always belongs to the current one.
    scheduleReconnect();
  });
  // An 'error' is always followed by 'close', so reconnection is handled there.
}

function scheduleReconnect(): void {
  const delay = Math.min(1000 * 2 ** retry, MAX_RECONNECT_DELAY_MS);
  retry += 1;
  window.setTimeout(connect, delay);
}

/** Open the presence socket once, for the lifetime of this tab. Idempotent. */
export function startSessionPresence(): void {
  if (started || typeof WebSocket === "undefined") return;
  started = true;
  connect();
}
