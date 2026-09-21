#!/usr/bin/env bash
# Update the headless Local Writing App server to the latest GitHub release,
# preserving the port and service user of the existing install, then restart.
#
#     sudo /opt/local-writing-app/update-server.sh          # from an install
#     sudo ./update-server.sh                                # from a tarball
#
# It follows the update channel this install is configured for (stable or
# nightly, read from the running app) and downloads that channel's latest release
# for this machine's architecture, then re-runs that release's own
# install-server.sh so the install logic always matches the version installed.
#   --force             reinstall even if already current / the app can't be reached
#   LWA_CHANNEL=nightly override the channel (otherwise taken from the running app)
set -euo pipefail

APP_NAME="local-writing-app"
INSTALL_DIR="/opt/${APP_NAME}"
SERVICE_PATH="/etc/systemd/system/${APP_NAME}.service"
REPO="antoncl/local-writing-app"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

if [ "$(id -u)" -ne 0 ]; then
  echo "This updater needs root. Re-run: sudo $0" >&2
  exit 1
fi

# The update wipes ${INSTALL_DIR}. If we're running from inside it, re-exec from
# a temp copy so this script file isn't deleted out from under bash mid-run.
self="$(readlink -f "$0")"
case "${self}" in
  "${INSTALL_DIR}/"*)
    tmpself="$(mktemp)"
    cp "${self}" "${tmpself}"
    chmod +x "${tmpself}"
    # Hand the copy's path forward so the re-exec'd run deletes it on exit.
    LWA_UPDATE_SELFCOPY="${tmpself}" exec "${tmpself}" "$@"
    ;;
esac

# curl or wget, whichever the box has.
fetch() {  # url -> stdout
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then wget -qO- "$1"
  else echo "Need curl or wget to fetch updates." >&2; exit 1; fi
}
download() {  # url dest
  if command -v curl >/dev/null 2>&1; then curl -fL -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -O "$2" "$1"
  else echo "Need curl or wget to download updates." >&2; exit 1; fi
}
# Pull a top-level JSON string field's value from stdin (no jq dependency).
json_field() {  # field-name  (reads stdin)
  grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]+\"" | head -1 | sed -E 's/.*"([^"]+)"$/\1/'
}
# Pull a top-level JSON boolean field's value ("true"/"false") from stdin.
json_bool() {  # field-name  (reads stdin)
  grep -oE "\"$1\"[[:space:]]*:[[:space:]]*(true|false)" | head -1 | grep -oE 'true|false'
}

# Map this machine's architecture onto a release asset suffix.
case "$(uname -m)" in
  x86_64|amd64)  ARCH="x64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *)
    echo "No prebuilt server for architecture '$(uname -m)'. Only x86_64 and aarch64 are published." >&2
    exit 1
    ;;
esac
ASSET="${APP_NAME}-linux-${ARCH}-server.tar.gz"

if [ ! -f "${SERVICE_PATH}" ]; then
  echo "No existing service at ${SERVICE_PATH} — run install-server.sh first." >&2
  exit 1
fi

# Preserve the running install's port and service user so an update never
# silently resets a custom port or user.
PORT="$(sed -n 's/^Environment=LWA_PORT=//p' "${SERVICE_PATH}" | head -1)"
PORT="${PORT:-8787}"
RUN_USER="$(sed -n 's/^User=//p' "${SERVICE_PATH}" | head -1)"

# Ask the running app what channel it follows and whether an update exists — the
# same channel-aware verdict the in-app checker uses, so a nightly install is
# never told "up to date" against a stable release (or downgraded onto one).
check="$(fetch "http://127.0.0.1:${PORT}/api/updates/check" 2>/dev/null || true)"
channel=""
available=""
reachable=""
if [ -n "${check}" ]; then
  channel="$(printf '%s' "${check}" | json_field channel || true)"
  available="$(printf '%s' "${check}" | json_bool update_available || true)"
  reachable="$(printf '%s' "${check}" | json_bool reachable || true)"
fi
# Env override wins; otherwise the app's configured channel; otherwise stable.
# Track that last fallback so we can warn before proceeding — assuming stable on
# a nightly box (e.g. --force with the service stopped) would silently downgrade.
channel_defaulted=0
if [ -z "${LWA_CHANNEL:-}" ] && [ -z "${channel}" ]; then channel_defaulted=1; fi
channel="${LWA_CHANNEL:-${channel:-stable}}"

if [ "${FORCE}" -eq 0 ]; then
  if [ -z "${check}" ]; then
    echo "Couldn't reach the running app on port ${PORT} to check for updates." >&2
    echo "Start the service, or re-run with --force to reinstall the latest anyway." >&2
    exit 1
  fi
  if [ "${reachable}" != "true" ]; then
    echo "The app couldn't reach GitHub to check for updates. Try again later, or use --force." >&2
    exit 1
  fi
  if [ "${available}" != "true" ]; then
    echo "Already up to date (${channel} channel)."
    exit 0
  fi
fi

if [ "${channel_defaulted}" -eq 1 ]; then
  echo "Note: couldn't read the update channel from the app; assuming stable." >&2
  echo "      If this is a nightly install, re-run with LWA_CHANNEL=nightly." >&2
fi

running="$(fetch "http://127.0.0.1:${PORT}/api/version" 2>/dev/null | json_field version || true)"
echo "Updating ${running:-unknown} on the ${channel} channel (${ARCH}, port ${PORT})..."

# Where the channel's assets live: stable = the latest non-prerelease release;
# nightly = the rolling `nightly` prerelease tag.
case "${channel}" in
  nightly) asset_base="https://github.com/${REPO}/releases/download/nightly" ;;
  *)       asset_base="https://github.com/${REPO}/releases/latest/download" ;;
esac

# Download and unpack the latest release into a temp dir we clean up on exit.
tmp="$(mktemp -d)"
cleanup() {
  rm -rf "${tmp}"
  if [ -n "${LWA_UPDATE_SELFCOPY:-}" ]; then rm -f "${LWA_UPDATE_SELFCOPY}"; fi
}
trap cleanup EXIT
echo "Downloading ${ASSET}..."
download "${asset_base}/${ASSET}" "${tmp}/${ASSET}"
tar -xzf "${tmp}/${ASSET}" -C "${tmp}"

new_installer="${tmp}/${APP_NAME}-linux-${ARCH}-server/install-server.sh"
if [ ! -f "${new_installer}" ]; then
  echo "Downloaded archive is missing install-server.sh — aborting." >&2
  exit 1
fi

# Hand off to the new release's own installer with the preserved settings.
LWA_PORT="${PORT}" RUN_USER="${RUN_USER}" bash "${new_installer}"

# Confirm what's actually running now.
sleep 2
now="$(fetch "http://127.0.0.1:${PORT}/api/version" 2>/dev/null | json_field version || true)"
echo
echo "Update complete. Now running version ${now:-unknown} (${channel} channel)."
