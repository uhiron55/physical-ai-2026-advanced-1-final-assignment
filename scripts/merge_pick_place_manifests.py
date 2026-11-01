#!/usr/bin/env python3
"""Merge successful, unique pick-and-place episode records."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = {}
    failed = []
    for path in args.input:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for record in manifest["episodes"]:
            if record.get("success"):
                episode_id = record["episode_id"]
                if episode_id in records:
                    raise RuntimeError(f"Duplicate episode ID: {episode_id}")
                records[episode_id] = record
            else:
                failed.append(record["episode_id"])

    successful = [records[key] for key in sorted(records)]
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_manifests": [str(path) for path in args.input],
        "success_count": len(successful),
        "excluded_failed_episode_ids": sorted(failed),
        "episodes": successful,
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OUTPUT={args.output}")
    print(f"SUCCESS={len(successful)}")
    print(f"EXCLUDED_FAILED={len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
