#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${B2_APP_DIR:-/opt/b2-droid}"
PORT="${B2_SERIAL_PORT:-/dev/ttyACM0}"
FQBN="${B2_ARDUINO_FQBN:-arduino:avr:uno}"

if [[ "${B2_FLASH_ARDUINO:-true}" =~ ^(0|false|no)$ ]]; then
  echo "Arduino flashing disabled by B2_FLASH_ARDUINO."
  exit 0
fi
if [[ ! -e "$PORT" ]]; then
  echo "Arduino not found at $PORT; skipping firmware upload." >&2
  exit 2
fi

if ! arduino-cli core list | grep -q '^arduino:avr'; then
  arduino-cli core update-index
  arduino-cli core install arduino:avr
fi
if ! arduino-cli lib list | grep -q '^LedControl[[:space:]]'; then
  arduino-cli lib install LedControl
fi

TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT
SKETCH_DIR="$TEMP_ROOT/b2_arduino"
mkdir -p "$SKETCH_DIR"
cp "$APP_DIR/arduino.ino" "$SKETCH_DIR/b2_arduino.ino"

echo "Compiling Arduino firmware for $FQBN..."
arduino-cli compile --fqbn "$FQBN" "$SKETCH_DIR"
echo "Uploading Arduino firmware through $PORT..."
arduino-cli upload --port "$PORT" --fqbn "$FQBN" "$SKETCH_DIR"
echo "Arduino firmware upload complete."
