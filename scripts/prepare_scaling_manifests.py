#!/usr/bin/env python3
"""Create nested, route-balanced manifests for data-scaling experiments."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def stratification_value(episode: dict) -> str:
    return str(episode.get("parameters", {}).get("route_profile", "unknown"))


def balanced_order(episodes: list[dict], seed: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for episode in episodes:
        groups[stratification_value(episode)].append(episode)

    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)

    ordered: list[dict] = []
    labels = sorted(groups)
    while any(groups.values()):
        for label in labels:
            if groups[label]:
                ordered.append(groups[label].pop())
    return ordered


def write_manifest(
    path: Path,
    episodes: list[dict],
    *,
    source: Path,
    seed: int,
    split: str,
) -> None:
    route_counts: dict[str, int] = defaultdict(int)
    for episode in episodes:
        route_counts[stratification_value(episode)] += 1
    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(source.resolve()),
        "selection_seed": seed,
        "split": split,
        "episode_count": len(episodes),
        "route_counts": dict(sorted(route_counts.items())),
        "episodes": episodes,
    }
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[20, 40, 80])
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20261031)
    args = parser.parse_args()

    source = json.loads(args.manifest.read_text(encoding="utf-8"))
    successful = [
        episode
        for episode in source.get("episodes", [])
        if episode.get("success") is True
    ]
    if not successful:
        raise RuntimeError("The source manifest has no successful episodes")
    if args.holdout_count < 0:
        parser.error("--holdout-count must be non-negative")
    if any(size <= 0 for size in args.sizes):
        parser.error("Every --sizes value must be positive")

    ordered = balanced_order(successful, args.seed)
    holdout = ordered[: args.holdout_count]
    training_pool = ordered[args.holdout_count :]
    if max(args.sizes) > len(training_pool):
        raise RuntimeError(
            f"Need {max(args.sizes)} training episodes after holdout, "
            f"but only {len(training_pool)} are available"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if holdout:
        write_manifest(
            args.output_dir / f"holdout-{len(holdout)}ep.json",
            holdout,
            source=args.manifest,
            seed=args.seed,
            split="holdout",
        )
    for size in sorted(set(args.sizes)):
        write_manifest(
            args.output_dir / f"train-{size}ep.json",
            training_pool[:size],
            source=args.manifest,
            seed=args.seed,
            split="train",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
