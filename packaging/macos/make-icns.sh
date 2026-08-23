#!/usr/bin/env bash
# Build packaging/icons/icon.icns from icon-1024.png (macOS iconutil, ADR-0072
# S5). Run on a mac BEFORE the frozen build so the spec's BUNDLE embeds it.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
src="${here}/../icons/icon-1024.png"
iconset="$(mktemp -d)/icon.iconset"
mkdir -p "${iconset}"

for size in 16 32 128 256 512; do
  double=$((size * 2))
  sips -z "${size}" "${size}" "${src}" --out "${iconset}/icon_${size}x${size}.png" >/dev/null
  sips -z "${double}" "${double}" "${src}" --out "${iconset}/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "${iconset}" -o "${here}/../icons/icon.icns"
echo "wrote ${here}/../icons/icon.icns"
