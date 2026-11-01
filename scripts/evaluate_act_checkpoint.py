#!/usr/bin/env python3
"""Evaluate a local ACT checkpoint on the first frame of each dataset episode."""

import argparse
import json
from pathlib import Path

import torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies import make_pre_post_processors
from lerobot.policies.act.modeling_act import ACTPolicy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument(
        "--repo-id",
        default="crane_plus_parameterized_pick_place",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    dataset = LeRobotDataset(args.repo_id, root=args.dataset_root)
    policy = ACTPolicy.from_pretrained(
        args.checkpoint,
        local_files_only=True,
    ).to(args.device).eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=args.checkpoint,
        preprocessor_overrides={"device_processor": {"device": args.device}},
    )

    rows = []
    with torch.inference_mode():
        for episode in range(dataset.num_episodes):
            index = int(dataset.meta.episodes[episode]["dataset_from_index"])
            item = dataset[index]
            policy.reset()
            observation = {
                "observation.images.front": item["observation.images.front"],
                "observation.state": item["observation.state"],
                "task": item["task"],
            }
            prediction = postprocessor(
                policy.select_action(preprocessor(observation))
            ).squeeze(0).cpu()
            target = item["action"].cpu()
            rows.append(
                {
                    "episode": episode,
                    "mae": float((prediction - target).abs().mean()),
                    "finite": bool(torch.isfinite(prediction).all()),
                    "max_abs": float(prediction.abs().max()),
                    "prediction": prediction.tolist(),
                    "target": target.tolist(),
                }
            )

    summary = {
        "checkpoint": str(args.checkpoint),
        "samples": len(rows),
        "finite_count": sum(row["finite"] for row in rows),
        "mean_mae": sum(row["mae"] for row in rows) / len(rows),
        "max_abs_prediction": max(row["max_abs"] for row in rows),
        "rows": rows,
    }
    output = args.output or args.checkpoint / "offline_inference_sanity.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
