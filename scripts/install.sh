#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR="${B2_APP_DIR:-/opt/b2-droid}"
DATA_DIR="${B2_DATA_DIR:-/var/lib/b2-droid}"
SERVICE_USER="${B2_USER:-droid}"
BOOTLOADER_DIR="${B2_BOOTLOADER_DIR:-/opt/b2-bootloader}"
LLM_MODEL_NAME="qwen2.5-1.5b-instruct-q4_k_m.gguf"
LLM_MODEL_URL="${B2_LLM_MODEL_URL:-https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/$LLM_MODEL_NAME}"
LLM_MODEL_SHA256="${B2_LLM_MODEL_SHA256:-6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e}"
INSTALL_LLM="${B2_INSTALL_LLM:-auto}"
CHAT_API="${B2_CHAT_API:-http://127.0.0.1:8080/v1/chat/completions}"
if [[ -f /etc/b2-droid.env ]]; then
  CONFIGURED_CHAT_API="$(sudo awk -F= '$1=="B2_CHAT_API" {print substr($0,index($0,"=")+1)}' /etc/b2-droid.env | tail -n1)"
  CONFIGURED_INSTALL_LLM="$(sudo awk -F= '$1=="B2_INSTALL_LLM" {print $2}' /etc/b2-droid.env | tail -n1)"
  CHAT_API="${CONFIGURED_CHAT_API:-$CHAT_API}"
  INSTALL_LLM="${CONFIGURED_INSTALL_LLM:-$INSTALL_LLM}"
fi
CHAT_BASE="${CHAT_API%/v1/chat/completions}"
MANAGED_LLM=false
INSTALLED_LLAMA=false

echo "Installing B2 from $SOURCE_DIR into permanent system location $APP_DIR"

configure_dashboard_password() {
  if sudo grep -q '^B2_WEB_PASSWORD=.' /etc/b2-droid.env 2>/dev/null; then
    return
  fi
  local dashboard_password="${B2_WEB_PASSWORD:-}"
  if [[ -z "$dashboard_password" && -t 0 ]]; then
    read -r -s -p "Choose the adult dashboard password (12+ characters): " dashboard_password
    echo
  fi
  if [[ "$dashboard_password" =~ ^[A-Za-z0-9._@%+=:-]{12,}$ ]]; then
    printf 'B2_WEB_PASSWORD=%s\n' "$dashboard_password" \
      | sudo tee -a /etc/b2-droid.env >/dev/null
    echo "Adult dashboard enabled. Username: admin"
  else
    echo "WARNING: Dashboard remains disabled until B2_WEB_PASSWORD is set." >&2
  fi
}

configure_dashboard_network() {
  if systemctl list-unit-files avahi-daemon.service >/dev/null 2>&1; then
    sudo systemctl enable --now avahi-daemon.service
  fi
  if command -v ufw >/dev/null 2>&1 \
    && sudo ufw status | grep -q '^Status: active'; then
    local web_port
    web_port="$(sudo awk -F= '$1=="B2_WEB_PORT" {print $2}' /etc/b2-droid.env | tail -n1)"
    web_port="${web_port:-8088}"
    sudo ufw allow "$web_port/tcp" comment 'B2 adult dashboard'
  fi
}

migrate_runtime_defaults() {
  # Migrate only the exact old factory ceiling; preserve intentional custom
  # values. Newly introduced settings are appended without exposing secrets.
  if sudo grep -q '^B2_MOTOR_SPEED_MAX=200$' /etc/b2-droid.env 2>/dev/null; then
    sudo sed -i 's/^B2_MOTOR_SPEED_MAX=200$/B2_MOTOR_SPEED_MAX=240/' \
      /etc/b2-droid.env
  fi
  if sudo grep -q '^B2_AMBIENT_MULTIPLIER=1\.65$' /etc/b2-droid.env 2>/dev/null; then
    sudo sed -i 's/^B2_AMBIENT_MULTIPLIER=1\.65$/B2_AMBIENT_MULTIPLIER=1.30/' \
      /etc/b2-droid.env
  fi
  if ! sudo grep -q '^B2_MOTOR_STARTUP_FLOOR=' /etc/b2-droid.env 2>/dev/null; then
    printf '%s\n' 'B2_MOTOR_STARTUP_FLOOR=220' \
      | sudo tee -a /etc/b2-droid.env >/dev/null
  fi
  if ! sudo grep -q '^B2_STARTUP_VOLUME_FLOOR=' /etc/b2-droid.env 2>/dev/null; then
    printf '%s\n' 'B2_STARTUP_VOLUME_FLOOR=100' \
      | sudo tee -a /etc/b2-droid.env >/dev/null
  fi
}

UPDATE_MODE=false
if [[ "${1:-}" == "--update" ]]; then
  UPDATE_MODE=true
fi

if [[ "$UPDATE_MODE" == false ]]; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-dev build-essential portaudio19-dev \
    alsa-utils ffmpeg libgl1 libglib2.0-0 network-manager arduino-cli rsync \
    git cmake curl libopenblas-dev liblapack-dev libjpeg-dev avahi-daemon
  if apt-cache show polkitd >/dev/null 2>&1; then
    sudo apt-get install -y polkitd pkexec
  else
    sudo apt-get install -y policykit-1
  fi
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd --system --create-home --groups audio,dialout,video "$SERVICE_USER"
  fi
fi

if [[ "$UPDATE_MODE" == true ]]; then
  ARDUINO_PORT="$(sudo awk -F= '$1=="B2_SERIAL_PORT" {print $2}' /etc/b2-droid.env | tail -n1)"
  ARDUINO_FQBN="$(sudo awk -F= '$1=="B2_ARDUINO_FQBN" {print $2}' /etc/b2-droid.env | tail -n1)"
  FLASH_ARDUINO="$(sudo awk -F= '$1=="B2_FLASH_ARDUINO" {print $2}' /etc/b2-droid.env | tail -n1)"
  ARDUINO_PORT="${ARDUINO_PORT:-/dev/ttyACM0}"
  ARDUINO_FQBN="${ARDUINO_FQBN:-arduino:avr:uno}"
  FLASH_ARDUINO="${FLASH_ARDUINO:-true}"
  sudo systemctl stop b2-droid.service 2>/dev/null || true
  sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" \
    "$DATA_DIR" "$DATA_DIR/Ultralytics" "$DATA_DIR/models" "$DATA_DIR/context.d"
  # Python keeps the serial descriptor open for its lifetime. Give systemd and
  # the Arduino's USB serial interface time to finish closing before avrdude.
  for _ in {1..20}; do
    if ! command -v fuser >/dev/null 2>&1 || ! fuser "$ARDUINO_PORT" >/dev/null 2>&1; then
      break
    fi
    sleep 0.1
  done
  rsync -a --delete --exclude data --exclude .venv --exclude .git \
    --exclude whisper.cpp --exclude llama.cpp --exclude voices --exclude yolo11n.onnx \
    --exclude yolo11n.pt "$SOURCE_DIR/" "$APP_DIR/"
  sudo install -d -m 755 "$BOOTLOADER_DIR/b2" \
    /etc/systemd/system/b2-droid.service.d
  sudo install -m 644 "$APP_DIR/b2/__init__.py" "$APP_DIR/b2/config.py" \
    "$APP_DIR/b2/runtime_config.py" "$APP_DIR/b2/updater.py" \
    "$APP_DIR/b2/updater_daemon.py" "$BOOTLOADER_DIR/b2/"
  printf '%s\n' '[Service]' 'Environment=B2_UPDATE_MEDIA_ROOT=/run/b2-disabled-update-scan' \
    | sudo tee /etc/systemd/system/b2-droid.service.d/10-external-updater.conf >/dev/null
  sudo install -m 644 "$APP_DIR/systemd/b2-update.service" \
    /etc/systemd/system/b2-update.service
  sudo systemctl daemon-reload
  sudo systemctl enable b2-update.service
  "$APP_DIR/.venv/bin/pip" install "setuptools<81" wheel
  "$APP_DIR/.venv/bin/pip" install "$APP_DIR"
  "$APP_DIR/.venv/bin/pip" install --upgrade \
    git+https://github.com/ageitgey/face_recognition_models
  "$APP_DIR/.venv/bin/python" -c \
    "import face_recognition, face_recognition_models; print('Face recognition verified')"
  migrate_runtime_defaults
  configure_dashboard_password
  configure_dashboard_network
  if ! sudo -u "$SERVICE_USER" env \
    B2_APP_DIR="$APP_DIR" B2_SERIAL_PORT="$ARDUINO_PORT" \
    B2_ARDUINO_FQBN="$ARDUINO_FQBN" B2_FLASH_ARDUINO="$FLASH_ARDUINO" \
    bash "$APP_DIR/scripts/flash-arduino.sh"; then
    echo "WARNING: Arduino firmware was not updated; B2 software update will continue." >&2
  fi
  sudo systemctl restart b2-droid.service
  sudo systemctl start b2-update.service
  exit 0
fi

sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$APP_DIR" "$DATA_DIR"
sudo install -d -m 755 "$BOOTLOADER_DIR/b2" \
  /etc/systemd/system/b2-droid.service.d
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$DATA_DIR/Ultralytics" "$DATA_DIR/models" "$DATA_DIR/context.d"
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" /var/log/b2-droid
sudo touch /var/log/b2-droid/app.log
sudo chown "$SERVICE_USER:$SERVICE_USER" /var/log/b2-droid/app.log
sudo rsync -a --delete --exclude data --exclude .venv --exclude .git \
  --exclude whisper.cpp --exclude llama.cpp --exclude voices --exclude yolo11n.onnx \
  --exclude yolo11n.pt "$SOURCE_DIR/" "$APP_DIR/"
sudo install -m 644 "$APP_DIR/b2/__init__.py" "$APP_DIR/b2/config.py" \
  "$APP_DIR/b2/runtime_config.py" "$APP_DIR/b2/updater.py" \
  "$APP_DIR/b2/updater_daemon.py" "$BOOTLOADER_DIR/b2/"
printf '%s\n' '[Service]' 'Environment=B2_UPDATE_MEDIA_ROOT=/run/b2-disabled-update-scan' \
  | sudo tee /etc/systemd/system/b2-droid.service.d/10-external-updater.conf >/dev/null
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR" "$DATA_DIR"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install "setuptools<81" wheel
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install "$APP_DIR"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade \
  git+https://github.com/ageitgey/face_recognition_models
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/python" -c \
  "import face_recognition, face_recognition_models; print('Face recognition verified')"

if [[ ! -x "$APP_DIR/whisper.cpp/build/bin/whisper-cli" ]]; then
  if [[ ! -d "$APP_DIR/whisper.cpp/.git" ]]; then
    sudo -u "$SERVICE_USER" git clone --depth 1 \
      https://github.com/ggml-org/whisper.cpp.git "$APP_DIR/whisper.cpp"
  fi
  sudo -u "$SERVICE_USER" cmake -S "$APP_DIR/whisper.cpp" \
    -B "$APP_DIR/whisper.cpp/build" -DCMAKE_BUILD_TYPE=Release
  sudo -u "$SERVICE_USER" cmake --build "$APP_DIR/whisper.cpp/build" \
    --config Release --parallel "$(nproc)"
fi

if [[ "$INSTALL_LLM" == "auto" ]]; then
  LLM_HTTP_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --max-time 5 "$CHAT_BASE/v1/models" || true)"
  if [[ "$LLM_HTTP_STATUS" == "200" || "$LLM_HTTP_STATUS" == "503" ]]; then
    echo "Compatible language-model endpoint detected at $CHAT_BASE; preserving it."
    INSTALL_LLM=false
  else
    for LLAMA_EXECUTABLE in \
      "/home/$SERVICE_USER/.local/bin/llama" \
      /usr/local/bin/llama \
      /usr/bin/llama; do
      if [[ -x "$LLAMA_EXECUTABLE" ]]; then
        echo "Existing llama CLI detected at $LLAMA_EXECUTABLE; adopting it."
        INSTALLED_LLAMA=true
        INSTALL_LLM=false
        MANAGED_LLM=true
        break
      fi
    done
    if [[ "$INSTALLED_LLAMA" != "true" ]]; then
      INSTALL_LLM=true
    fi
  fi
fi

if [[ "$INSTALL_LLM" == "true" && ! -x "$APP_DIR/llama.cpp/build/bin/llama-server" ]]; then
  if [[ ! -d "$APP_DIR/llama.cpp/.git" ]]; then
    sudo -u "$SERVICE_USER" git clone --depth 1 \
      https://github.com/ggml-org/llama.cpp.git "$APP_DIR/llama.cpp"
  fi
  sudo -u "$SERVICE_USER" cmake -S "$APP_DIR/llama.cpp" \
    -B "$APP_DIR/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release \
    -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS
  sudo -u "$SERVICE_USER" cmake --build "$APP_DIR/llama.cpp/build" \
    --config Release --target llama-server --parallel "$(nproc)"
fi

if [[ "$INSTALL_LLM" == "true" && ! -f "$DATA_DIR/models/$LLM_MODEL_NAME" ]]; then
  sudo -u "$SERVICE_USER" curl -L --fail --retry 3 \
    --output "$DATA_DIR/models/$LLM_MODEL_NAME.part" "$LLM_MODEL_URL"
  echo "$LLM_MODEL_SHA256  $DATA_DIR/models/$LLM_MODEL_NAME.part" \
    | sha256sum -c -
  sudo -u "$SERVICE_USER" mv "$DATA_DIR/models/$LLM_MODEL_NAME.part" \
    "$DATA_DIR/models/$LLM_MODEL_NAME"
fi
if [[ "$INSTALL_LLM" == "true" ]]; then
  MANAGED_LLM=true
fi

if [[ ! -f "$APP_DIR/whisper.cpp/models/ggml-tiny.en.bin" ]]; then
  sudo -u "$SERVICE_USER" "$APP_DIR/whisper.cpp/models/download-ggml-model.sh" tiny.en
fi
if [[ ! -f "$APP_DIR/whisper.cpp/models/ggml-small.en.bin" ]]; then
  sudo -u "$SERVICE_USER" "$APP_DIR/whisper.cpp/models/download-ggml-model.sh" small.en
fi

if [[ ! -f "$APP_DIR/voices/en_GB-alba-medium.onnx" ]]; then
  sudo -u "$SERVICE_USER" install -d "$APP_DIR/voices"
  sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/python" -m piper.download_voices \
    --data-dir "$APP_DIR/voices" en_GB-alba-medium
fi

if [[ ! -f "$APP_DIR/yolo11n.onnx" ]]; then
  sudo -u "$SERVICE_USER" sh -c \
    "cd '$APP_DIR' && '$APP_DIR/.venv/bin/yolo' export model=yolo11n.pt format=onnx imgsz=320"
fi

if [[ ! -f /etc/b2-droid.env ]]; then
  sudo install -m 600 "$APP_DIR/config/b2.env.example" /etc/b2-droid.env
fi
migrate_runtime_defaults
configure_dashboard_password
configure_dashboard_network
ARDUINO_PORT="$(sudo awk -F= '$1=="B2_SERIAL_PORT" {print $2}' /etc/b2-droid.env | tail -n1)"
ARDUINO_FQBN="$(sudo awk -F= '$1=="B2_ARDUINO_FQBN" {print $2}' /etc/b2-droid.env | tail -n1)"
FLASH_ARDUINO="$(sudo awk -F= '$1=="B2_FLASH_ARDUINO" {print $2}' /etc/b2-droid.env | tail -n1)"
ARDUINO_PORT="${ARDUINO_PORT:-/dev/ttyACM0}"
ARDUINO_FQBN="${ARDUINO_FQBN:-arduino:avr:uno}"
FLASH_ARDUINO="${FLASH_ARDUINO:-true}"
sudo systemctl stop b2-droid.service 2>/dev/null || true
if ! sudo -u "$SERVICE_USER" env \
  B2_APP_DIR="$APP_DIR" B2_SERIAL_PORT="$ARDUINO_PORT" \
  B2_ARDUINO_FQBN="$ARDUINO_FQBN" B2_FLASH_ARDUINO="$FLASH_ARDUINO" \
  bash "$APP_DIR/scripts/flash-arduino.sh"; then
  echo "WARNING: Arduino firmware was not updated; Ubuntu installation will continue." >&2
fi
sudo install -m 644 "$APP_DIR/systemd/b2-droid.service" /etc/systemd/system/b2-droid.service
sudo install -m 644 "$APP_DIR/systemd/b2-update.service" /etc/systemd/system/b2-update.service
if [[ "$MANAGED_LLM" == "true" ]]; then
  sudo install -m 644 "$APP_DIR/systemd/b2-llm.service" /etc/systemd/system/b2-llm.service
fi
sudo install -m 644 "$APP_DIR/config/49-b2-networkmanager.rules" \
  /etc/polkit-1/rules.d/49-b2-networkmanager.rules
sudo install -m 644 "$APP_DIR/config/b2-droid.logrotate" \
  /etc/logrotate.d/b2-droid
sudo systemctl daemon-reload
if [[ "$MANAGED_LLM" == "true" ]]; then
  sudo systemctl enable b2-llm.service
  sudo systemctl restart b2-llm.service
fi
sudo systemctl enable b2-droid.service
sudo systemctl enable b2-update.service
sudo systemctl restart b2-droid.service
sudo systemctl restart b2-update.service
echo "B2 installed. Follow logs with: journalctl -u b2-droid -f"
