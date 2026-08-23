# Local Writing App — headless server (Raspberry Pi / Linux)

This tarball runs the app as a background **systemd service** on a headless box
and serves it over your LAN, so you can write from any browser on your network.

## Install

```bash
tar -xzf local-writing-app-*-server.tar.gz
cd local-writing-app-*-server   # or wherever it extracted
sudo ./install-server.sh
```

The installer copies the app to `/opt/local-writing-app`, creates a systemd
service that runs it as **your** user (not root), enables it on boot, and prints
the LAN URL (e.g. `http://192.168.1.42:8787`).

Options (export before running):

- `LWA_PORT=9000 sudo -E ./install-server.sh` — a different port.
- `RUN_USER=writer sudo ./install-server.sh` — a specific service user.

## ⚠ No authentication

The service binds `0.0.0.0` so other machines can reach it, and the app has **no
login**. Only run it on a **trusted private network**, for a single trusted user.
Do not expose it to the internet.

## Manage it

```bash
systemctl status local-writing-app      # is it running?
journalctl -u local-writing-app -f      # live logs
systemctl restart local-writing-app     # restart
sudo systemctl disable --now local-writing-app   # stop + disable
```

## Uninstall

```bash
sudo systemctl disable --now local-writing-app
sudo rm /etc/systemd/system/local-writing-app.service
sudo rm -r /opt/local-writing-app
```

Your projects live in the folder you choose from the app's settings (under your
home dir by default) and are **not** removed by uninstalling.
