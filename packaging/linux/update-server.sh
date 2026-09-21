#!/usr/bin/env bash
# Update the headless Local Writing App server to the latest GitHub release,
# preserving the port and service user of the existing install, then restart.
#
#     sudo /opt/local-writing-app/update-server.sh          # from an install
#     sudo ./update-server.sh                                # from a tarball
#
# It downloads the latest release for this machine's architecture and re-runs
# that release's own install-server.sh, so the install logic always matches the
# version being installed. Pass --force to reinstall even if already current.
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

strip_v() { printf '%s' "${1#v}"; }

# Latest published version (release tag), and the version currently running.
latest_tag="$(fetch "https://api.github.com/repos/${REPO}/releases/latest" | json_field tag_name || true)"
if [ -z "${latest_tag}" ]; then
  echo "Couldn't determine the latest release. Check your network and try again." >&2
  exit 1
fi
latest="$(strip_v "${latest_tag}")"

running="$(fetch "http://127.0.0.1:${PORT}/api/version" 2>/dev/null | json_field version || true)"

if [ "${FORCE}" -eq 0 ] && [ -n "${running}" ] && [ "${running}" = "${latest}" ]; then
  echo "Already up to date (version ${running})."
  exit 0
fi
echo "Updating ${running:-unknown} -> ${latest} (${ARCH}, port ${PORT})..."

# Download and unpack the latest release into a temp dir we clean up on exit.
tmp="$(mktemp -d)"
cleanup() {
  rm -rf "${tmp}"
  if [ -n "${LWA_UPDATE_SELFCOPY:-}" ]; then rm -f "${LWA_UPDATE_SELFCOPY}"; fi
}
trap cleanup EXIT
echo "Downloading ${ASSET}..."
download "https://github.com/${REPO}/releases/latest/download/${ASSET}" "${tmp}/${ASSET}"
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
echo "Update complete. Now running version ${now:-${latest}}."
