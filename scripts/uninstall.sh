#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${B2_APP_DIR:-/opt/b2-droid}"
DATA_DIR="${B2_DATA_DIR:-/var/lib/b2-droid}"
BOOTLOADER_DIR="${B2_BOOTLOADER_DIR:-/opt/b2-bootloader}"
PURGE_DATA=false

usage() {
  echo "Usage: $0 [--purge-data]"
  echo ""
  echo "Without --purge-data, faces, memories, models and /etc/b2-droid.env are preserved."
  echo "With --purge-data, all persistent B2 data, configuration and logs are deleted."
}

for argument in "$@"; do
  case "$argument" in
    --purge-data) PURGE_DATA=true ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $argument" >&2; usage >&2; exit 2 ;;
  esac
done

safe_remove_tree() {
  local target="$1"
  case "$target" in
    ""|/|/opt|/var|/var/lib|/usr|/etc|/home)
      echo "Refusing unsafe removal target: $target" >&2
      exit 1
      ;;
  esac
  if [[ "$target" != /* ]]; then
    echo "Refusing non-absolute removal target: $target" >&2
    exit 1
  fi
  sudo rm -rf -- "$target"
}

echo "Stopping B2 services..."
sudo systemctl disable --now b2-update.service 2>/dev/null || true
sudo systemctl disable --now b2-droid.service 2>/dev/null || true
sudo systemctl disable --now b2-llm.service 2>/dev/null || true
sudo umount /run/b2-update-media 2>/dev/null || true
sudo rmdir /run/b2-update-media 2>/dev/null || true

sudo rm -f -- \
  /etc/systemd/system/b2-update.service \
  /etc/systemd/system/b2-droid.service \
  /etc/systemd/system/b2-llm.service \
  /etc/polkit-1/rules.d/49-b2-networkmanager.rules \
  /etc/logrotate.d/b2-droid
safe_remove_tree /etc/systemd/system/b2-droid.service.d
safe_remove_tree "$APP_DIR"
safe_remove_tree "$BOOTLOADER_DIR"

if [[ "$PURGE_DATA" == true ]]; then
  echo "Purging persistent faces, memories, models, configuration and logs..."
  safe_remove_tree "$DATA_DIR"
  safe_remove_tree /var/log/b2-droid
  sudo rm -f -- /etc/b2-droid.env
else
  echo "Preserved persistent data in $DATA_DIR and configuration in /etc/b2-droid.env."
fi

sudo systemctl daemon-reload
sudo systemctl reset-failed b2-update.service b2-droid.service b2-llm.service \
  2>/dev/null || true

echo "B2 application and services removed. The droid system user and shared Ubuntu packages remain."
