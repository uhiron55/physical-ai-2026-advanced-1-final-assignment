#!/usr/bin/env python3
"""Build matched manifests that separate data quantity from condition diversity."""

from __future__ import annotations

import argparse
import copy
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def route_of(episode: dict) -> str:
    return str(episode.get("parameters", {}).get("route_profile", "unknown"))


def successful_episodes(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    episodes = [
        copy.deepcopy(episode)
        for episode in document.get("episodes", [])
        if episode.get("success") is True
    ]
    if not episodes:
        raise RuntimeError(f"No successful episodes in {path}")
    return episodes


def balanced_sample(episodes: list[dict], count: int, seed: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for episode in episodes:
        groups[route_of(episode)].append(episode)

    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)

    ordered: list[dict] = []
    labels = sorted(groups)
    while any(groups.values()) and len(ordered) < count:
        for label in labels:
            if groups[label] and len(ordered) < count:
                ordered.append(groups[label].pop())
    if len(ordered) < count:
        raise RuntimeError(f"Requested {count} episodes, found {len(ordered)}")
    return ordered


def validate_unique(episodes: list[dict], label: str) -> None:
    ids = [str(episode.get("episode_id")) for episode in episodes]
    duplicates = sorted({episode_id for episode_id in ids if ids.count(episode_id) > 1})
    if duplicates:
        raise RuntimeError(f"Duplicate episode IDs in {label}: {duplicates}")


def write_manifest(
    path: Path,
    episodes: list[dict],
    *,
    condition: str,
    sources: list[Path],
    seed: int,
) -> None:
    route_counts: dict[str, int] = defaultdict(int)
    for episode in episodes:
        route_counts[route_of(episode)] += 1
    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "quantity-versus-diversity",
        "condition": condition,
        "selection_seed": seed,
        "source_manifests": [str(source.resolve()) for source in sources],
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
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--narrow-addition", type=Path, required=True)
    parser.add_argument("--diverse-addition", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-count", type=int, default=20)
    parser.add_argument("--additional-count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261031)
    args = parser.parse_args()

    if args.baseline_count <= 0 or args.additional_count <= 0:
        parser.error("Episode counts must be positive")

    baseline = balanced_sample(
        successful_episodes(args.baseline), args.baseline_count, args.seed
    )
    narrow = balanced_sample(
        successful_episodes(args.narrow_addition),
        args.additional_count,
        args.seed + 1,
    )
    diverse = balanced_sample(
        successful_episodes(args.diverse_addition),
        args.additional_count,
        args.seed + 2,
    )

    conditions = {
        "baseline-20": (baseline, [args.baseline]),
        "narrow-40": (baseline + narrow, [args.baseline, args.narrow_addition]),
        "diverse-40": (baseline + diverse, [args.baseline, args.diverse_addition]),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for condition, (episodes, sources) in conditions.items():
        validate_unique(episodes, condition)
        write_manifest(
            args.output_dir / f"{condition}.json",
            episodes,
            condition=condition,
            sources=sources,
            seed=args.seed,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
