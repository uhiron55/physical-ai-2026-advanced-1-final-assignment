#!/usr/bin/env bash
set -euo pipefail

CHECKPOINT_DIR="${1:?checkpoint directory is required}"
OUTPUT_DIR="${2:?output directory is required}"
TOTAL_STEPS="${3:?total training steps are required}"
SAVE_FREQ="${SAVE_FREQ:-${TOTAL_STEPS}}"

CONFIG_PATH="${CHECKPOINT_DIR}/pretrained_model"
if [[ ! -f "${CONFIG_PATH}/train_config.json" ]]; then
  echo "train_config.json was not found under ${CONFIG_PATH}" >&2
  exit 2
fi

lerobot-train \
  --config_path="${CONFIG_PATH}" \
  --resume=true \
  --output_dir="${OUTPUT_DIR}" \
  --steps="${TOTAL_STEPS}" \
  --save_freq="${SAVE_FREQ}" \
  --wandb.enable=false
