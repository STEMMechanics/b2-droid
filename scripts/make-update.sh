#!/usr/bin/env bash
set -euo pipefail

DESTINATION="${1:?Usage: scripts/make-update.sh /path/to/sd-card [version]}"
VERSION="${2:-$(date -u +%Y%m%d%H%M%S)}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE="$DESTINATION/b2-update.tar.gz"

mkdir -p "$DESTINATION"
tar -czf "$ARCHIVE" -C "$PROJECT_DIR" \
  --exclude=.git --exclude=.venv --exclude=data --exclude=whisper.cpp \
  --exclude=voices --exclude=yolo11n.onnx --exclude=yolo11n.pt .
if command -v sha256sum >/dev/null 2>&1; then
  CHECKSUM="$(sha256sum "$ARCHIVE" | cut -d ' ' -f 1)"
elif command -v shasum >/dev/null 2>&1; then
  CHECKSUM="$(shasum -a 256 "$ARCHIVE" | cut -d ' ' -f 1)"
else
  echo "Neither sha256sum nor shasum is installed." >&2
  exit 1
fi
printf '{"manifest_version":1,"version":"%s","sha256":"%s","database_compatibility":{"min":0,"max":1}}\n' "$VERSION" "$CHECKSUM" \
  > "$DESTINATION/b2-update.json"
echo "Created B2 update $VERSION in $DESTINATION"
