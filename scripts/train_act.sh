#!/usr/bin/env bash
set -euo pipefail

DATASET_ROOT="${1:?dataset root is required}"
OUTPUT_DIR="${2:?output directory is required}"
STEPS="${3:-200}"
REPO_ID="${LEROBOT_DATASET_REPO_ID:-crane_plus_parameterized_pick_place}"
BATCH_SIZE="${BATCH_SIZE:-4}"
USE_AMP="${USE_AMP:-false}"

lerobot-train \
  --dataset.repo_id="${REPO_ID}" \
  --dataset.root="${DATASET_ROOT}" \
  --policy.type=act \
  --policy.device=cuda \
  --policy.use_amp="${USE_AMP}" \
  --policy.push_to_hub=false \
  --output_dir="${OUTPUT_DIR}" \
  --job_name=crane-plus-act \
  --steps="${STEPS}" \
  --batch_size="${BATCH_SIZE}" \
  --num_workers=0 \
  --env_eval_freq=0 \
  --wandb.enable=false \
  --save_checkpoint=true \
  --save_freq="${STEPS}"
