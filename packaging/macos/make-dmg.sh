#!/usr/bin/env bash
# Build a drag-to-Applications .dmg from the frozen .app (macOS, ADR-0072 S5).
# Unsigned / experimental — Gatekeeper will warn on first open; users right-click
# > Open, or clear the quarantine attribute. Usage:
#   packaging/macos/make-dmg.sh <output.dmg>
set -euo pipefail

out="${1:?usage: make-dmg.sh <output.dmg>}"
app="dist/Local Writing App.app"

if [ ! -d "${app}" ]; then
  echo "Expected ${app} (the BUNDLE output) — did the frozen build run on macOS?" >&2
  exit 1
fi

staging="$(mktemp -d)/dmg"
mkdir -p "${staging}"
cp -R "${app}" "${staging}/"
ln -s /Applications "${staging}/Applications"

rm -f "${out}"
hdiutil create -volname "Local Writing App" -srcfolder "${staging}" -ov -format UDZO "${out}"
echo "wrote ${out}"
