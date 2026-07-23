#!/usr/bin/env bash
set -euo pipefail

MODEL_ROOT=/home/intern/local-ai-models/comfyui

export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
export DO_NOT_TRACK=1

download_verified() {
  local url=$1
  local destination=$2
  local expected_size=$3
  local expected_sha256=$4
  local partial="${destination}.partial"

  mkdir -p "$(dirname "$destination")"
  if [[ -f "$destination" ]]; then
    local current_size
    current_size=$(stat -c '%s' "$destination")
    local current_sha256
    current_sha256=$(sha256sum "$destination" | awk '{print $1}')
    if [[ "$current_size" == "$expected_size" && "$current_sha256" == "$expected_sha256" ]]; then
      echo "verified existing: $destination"
      return
    fi
    echo "refusing to overwrite an unexpected existing file: $destination" >&2
    return 1
  fi

  curl --fail --location --retry 8 --continue-at - \
    --output "$partial" "$url"

  local actual_size
  actual_size=$(stat -c '%s' "$partial")
  if [[ "$actual_size" != "$expected_size" ]]; then
    echo "size mismatch for $partial: $actual_size != $expected_size" >&2
    return 1
  fi
  local actual_sha256
  actual_sha256=$(sha256sum "$partial" | awk '{print $1}')
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    echo "sha256 mismatch for $partial: $actual_sha256 != $expected_sha256" >&2
    return 1
  fi
  mv "$partial" "$destination"
  echo "downloaded and verified: $destination"
}

download_verified \
  'https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/e9e85de74a8f48c1e3e2656617626348675a2f21/split_files/diffusion_models/qwen_image_edit_2511_bf16.safetensors' \
  "$MODEL_ROOT/diffusion_models/qwen_image_edit_2511_bf16.safetensors" \
  40861031560 \
  ae42d927b5fac4f278b9a894554c727e619727a63622976f2d95625be4bce08c

download_verified \
  'https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/46839d338df81ce625d5fae27d7e370314c0fbc9/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors' \
  "$MODEL_ROOT/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
  9384670680 \
  cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4

download_verified \
  'https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/46839d338df81ce625d5fae27d7e370314c0fbc9/split_files/vae/qwen_image_vae.safetensors' \
  "$MODEL_ROOT/vae/qwen_image_vae.safetensors" \
  253806246 \
  a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f
