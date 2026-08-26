#!/usr/bin/env bash
set -euo pipefail

read -r -p "Wi-Fi network name (SSID): " SSID
read -r -s -p "Wi-Fi password: " PASSWORD
echo
nmcli device wifi connect "$SSID" password "$PASSWORD"
echo "Connected to $SSID"
