#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${B2_APP_DIR:-/opt/b2-droid}"
DATA_DIR="${B2_DATA_DIR:-/var/lib/b2-droid}"
HF_MODEL="${B2_LLM_HF_MODEL:-Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M}"
CONTEXT_SIZE="${B2_LLM_CONTEXT_SIZE:-4096}"

for executable in \
  /home/droid/.local/bin/llama \
  /usr/local/bin/llama \
  /usr/bin/llama; do
  if [[ -x "$executable" ]]; then
    exec "$executable" server -hf "$HF_MODEL" \
      --host 127.0.0.1 --port 8080 --ctx-size "$CONTEXT_SIZE" --parallel 1
  fi
done

exec "$APP_DIR/llama.cpp/build/bin/llama-server" \
  --model "$DATA_DIR/models/qwen2.5-1.5b-instruct-q4_k_m.gguf" \
  --host 127.0.0.1 --port 8080 --ctx-size 4096 --parallel 1
