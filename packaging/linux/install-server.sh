#!/usr/bin/env bash
# Install the Local Writing App as a systemd service on a headless Linux box
# (e.g. a Raspberry Pi). Run from the extracted tarball directory:
#
#     sudo ./install-server.sh
#
# It binds 0.0.0.0 so the app is reachable from other machines on your LAN.
# The app has NO authentication (ADR-0072 §3) — only run it this way on a
# trusted private network, for a single trusted user.
set -euo pipefail

APP_NAME="local-writing-app"
INSTALL_DIR="/opt/${APP_NAME}"
SERVICE_PATH="/etc/systemd/system/${APP_NAME}.service"
# The service runs as the human who invoked sudo (so projects land in a real
# home dir), not root. Override by exporting RUN_USER before running.
RUN_USER="${RUN_USER:-${SUDO_USER:-$(id -un)}}"
PORT="${LWA_PORT:-8787}"

if [ "$(id -u)" -ne 0 ]; then
  echo "This installer needs root. Re-run: sudo ./install-server.sh" >&2
  exit 1
fi

here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "${here}/${APP_NAME}/${APP_NAME}" ]; then
  echo "Can't find ${APP_NAME}/${APP_NAME} next to this script — run it from the extracted tarball." >&2
  exit 1
fi

echo "Installing to ${INSTALL_DIR} (service user: ${RUN_USER}, port: ${PORT})..."
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cp -a "${here}/${APP_NAME}/." "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}/${APP_NAME}"

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=Local Writing App (local-first fiction writing)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
# Bind the LAN so the headless box is reachable. NO AUTH — trusted network only.
Environment=LWA_HOST=0.0.0.0
Environment=LWA_PORT=${PORT}
# --no-browser: a headless box has no display to open one on. The 0.0.0.0 bind
# above already makes this non-loopback (so the launcher skips the browser), but
# the flag says it outright and survives someone narrowing the bind to loopback.
ExecStart=${INSTALL_DIR}/${APP_NAME} --no-browser
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${APP_NAME}.service"

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Done. The app is running as a service."
echo "  Open on your LAN:  http://${ip:-<this-box-ip>}:${PORT}"
echo "  Status:            systemctl status ${APP_NAME}"
echo "  Logs:              journalctl -u ${APP_NAME} -f"
echo "  Uninstall:         systemctl disable --now ${APP_NAME}; rm ${SERVICE_PATH} ${INSTALL_DIR} -r"
