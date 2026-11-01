#!/usr/bin/env python3
"""Summarize an ACT closed-loop rollout recorded with rosbag2."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message


ACTION_TOPIC = "/act_rollout/action"
STATUS_TOPIC = "/act_rollout/status"


def read_rollout(bag: Path) -> tuple[list[list[float]], list[dict]]:
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions(
            input_serialization_format="cdr",
            output_serialization_format="cdr",
        ),
    )
    topic_types = {
        item.name: get_message(item.type)
        for item in reader.get_all_topics_and_types()
    }
    actions: list[list[float]] = []
    statuses: list[dict] = []
    while reader.has_next():
        topic, data, _ = reader.read_next()
        if topic == ACTION_TOPIC:
            message = deserialize_message(data, topic_types[topic])
            actions.append([float(value) for value in message.data])
        elif topic == STATUS_TOPIC:
            message = deserialize_message(data, topic_types[topic])
            try:
                statuses.append(json.loads(message.data))
            except json.JSONDecodeError:
                statuses.append({"status": "invalid_json", "raw": message.data})
    return actions, statuses


def summarize(actions: list[list[float]], statuses: list[dict]) -> dict:
    if not actions:
        raise ValueError("The bag contains no ACT rollout actions")
    matrix = np.asarray(actions, dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError(f"Expected a 2-D action matrix, got {matrix.shape}")
    latency = [
        float(item["latency_ms"])
        for item in statuses
        if item.get("latency_ms") is not None
    ]
    path_length = np.abs(np.diff(matrix, axis=0)).sum(axis=0)
    terminal = next(
        (item for item in reversed(statuses) if item.get("status") != "running"),
        None,
    )
    return {
        "action_count": int(matrix.shape[0]),
        "action_dimensions": int(matrix.shape[1]),
        "action_min": matrix.min(axis=0).tolist(),
        "action_max": matrix.max(axis=0).tolist(),
        "action_std": matrix.std(axis=0).tolist(),
        "command_path_length_l1": path_length.tolist(),
        "command_path_length_l1_total": float(path_length.sum()),
        "latency_ms": {
            "samples": len(latency),
            "min": min(latency) if latency else None,
            "median": statistics.median(latency) if latency else None,
            "mean": statistics.fmean(latency) if latency else None,
            "max": max(latency) if latency else None,
        },
        "terminal_status": terminal,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bag", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(*read_rollout(args.bag))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
