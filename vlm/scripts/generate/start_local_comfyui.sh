#!/usr/bin/env bash
set -euo pipefail

COMFYUI_ROOT=/home/intern/wmy/ComfyUI
COMFYUI_PYTHON=/home/intern/anaconda3/envs/air310/bin/python
COMFYUI_OUTPUT='/home/intern/Supervised 2D to 3D/vlm/experiments/comfyui_output'
COMFYUI_DEVICE="${COMFYUI_CUDA_DEVICE:-0}"
COMFYUI_API_PORT="${COMFYUI_PORT:-8188}"

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

mkdir -p "$COMFYUI_OUTPUT"
cd "$COMFYUI_ROOT"

exec "$COMFYUI_PYTHON" main.py \
  --listen 127.0.0.1 \
  --port "$COMFYUI_API_PORT" \
  --cuda-device "$COMFYUI_DEVICE" \
  --highvram \
  --disable-auto-launch \
  --output-directory "$COMFYUI_OUTPUT"
