#!/usr/bin/env python3
"""Summarize motion, bag-audit, and Jev-decision results for one collection."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from rosbags.highlevel import AnyReader
from rosbags.typesys import Stores, get_typestore


def load_decisions(bag: Path, typestore) -> list[dict]:
    decisions: list[dict] = []
    with AnyReader([bag], default_typestore=typestore) as reader:
        connections = [
            connection
            for connection in reader.connections
            if connection.topic == "/jev_crane/decision"
        ]
        for connection, _, rawdata in reader.messages(connections=connections):
            message = reader.deserialize(rawdata, connection.msgtype)
            decisions.append(json.loads(message.data))
    return decisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--condition", required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    episodes = manifest.get("episodes", [])
    if not episodes:
        raise RuntimeError("The manifest contains no episodes")

    typestore = get_typestore(Stores.ROS2_HUMBLE)
    audits = []
    decisions = []
    for episode in episodes:
        episode_id = str(episode["episode_id"])
        audit_path = args.audit_dir / f"{episode_id}.json"
        audits.append(json.loads(audit_path.read_text(encoding="utf-8")))
        decisions.extend(load_decisions(Path(episode["bag_path"]), typestore))

    route_counts = Counter(
        str(episode.get("parameters", {}).get("route_profile", "unknown"))
        for episode in episodes
    )
    errors = [float(episode["position_error_m"]) * 1000 for episode in episodes]
    image_specs = sorted(
        {
            (spec["width"], spec["height"], spec["encoding"])
            for audit in audits
            for spec in audit.get("image_specs", [])
        }
    )
    confidences = [float(decision.get("confidence", 0)) for decision in decisions]
    summary = {
        "condition": args.condition,
        "manifest": str(args.manifest),
        "episodes": len(episodes),
        "successes": sum(episode.get("success") is True for episode in episodes),
        "route_counts": dict(sorted(route_counts.items())),
        "position_error_mm": {
            "mean": round(statistics.mean(errors), 3),
            "max": round(max(errors), 3),
        },
        "bag_valid": sum(audit.get("valid") is True for audit in audits),
        "timestamp_non_monotonic_total": sum(
            topic.get("non_monotonic_intervals", 0)
            for audit in audits
            for topic in audit.get("topics", {}).values()
        ),
        "image_specs": [
            {"width": width, "height": height, "encoding": encoding}
            for width, height, encoding in image_specs
        ],
        "jev": {
            "decisions": len(decisions),
            "model_correct": sum(
                decision.get("model_choice") == decision.get("recommended")
                for decision in decisions
            ),
            "fallbacks": sum(
                decision.get("fallback_reason") is not None
                for decision in decisions
            ),
            "confidence_mean": (
                round(statistics.mean(confidences), 3) if confidences else None
            ),
            "confidence_min": min(confidences) if confidences else None,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
