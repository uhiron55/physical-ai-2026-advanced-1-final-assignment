#!/usr/bin/env python3
"""Audit a pick-and-place rosbag and render representative camera frames."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore


CAMERA_TOPIC = "/camera/image_raw"


def decode_image(message) -> np.ndarray:
    if message.encoding not in {"rgb8", "bgr8"}:
        raise ValueError(f"Unsupported image encoding: {message.encoding}")
    row_bytes = int(message.step)
    expected_row_bytes = int(message.width) * 3
    if row_bytes < expected_row_bytes:
        raise ValueError(
            f"Image step {row_bytes} is smaller than RGB row {expected_row_bytes}"
        )
    raw = np.frombuffer(message.data, dtype=np.uint8)
    expected_size = int(message.height) * row_bytes
    if raw.size != expected_size:
        raise ValueError(f"Image payload has {raw.size} bytes, expected {expected_size}")
    image = raw.reshape(int(message.height), row_bytes)[:, :expected_row_bytes]
    image = image.reshape(int(message.height), int(message.width), 3)
    if message.encoding == "bgr8":
        image = image[..., ::-1]
    return np.ascontiguousarray(image)


def make_contact_sheet(frames: list[tuple[int, np.ndarray]], output: Path) -> None:
    if not frames:
        return
    labels = ["start", "25%", "50%", "75%", "end"]
    height, width, _ = frames[0][1].shape
    label_height = 28
    canvas = Image.new("RGB", (width * len(frames), height + label_height), "white")
    draw = ImageDraw.Draw(canvas)
    first_timestamp = frames[0][0]
    for index, (timestamp, image) in enumerate(frames):
        canvas.paste(Image.fromarray(image), (index * width, label_height))
        elapsed = (timestamp - first_timestamp) / 1e9
        draw.text(
            (index * width + 8, 7),
            f"{labels[index]}  +{elapsed:.2f}s",
            fill="black",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bag", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--contact-sheet", type=Path)
    parser.add_argument(
        "--contact-sheet-window-topic",
        help="Limit contact-sheet frames to the first/last timestamps of this topic",
    )
    args = parser.parse_args()

    typestore = get_typestore(Stores.ROS2_HUMBLE)
    timestamps: dict[str, list[int]] = {}
    images: list[tuple[int, np.ndarray]] = []
    image_specs: Counter[tuple[int, int, str, int]] = Counter()

    with Reader(args.bag) as reader:
        for connection, timestamp, rawdata in reader.messages():
            timestamps.setdefault(connection.topic, []).append(timestamp)
            if connection.topic != CAMERA_TOPIC:
                continue
            message = typestore.deserialize_cdr(rawdata, connection.msgtype)
            image = decode_image(message)
            images.append((timestamp, image))
            image_specs[
                (
                    int(message.width),
                    int(message.height),
                    str(message.encoding),
                    int(message.step),
                )
            ] += 1

    if not images:
        raise RuntimeError(f"No camera frames in {args.bag}")

    topic_report = {}
    for topic, topic_timestamps in sorted(timestamps.items()):
        deltas = np.diff(np.asarray(topic_timestamps, dtype=np.int64))
        duration_s = (topic_timestamps[-1] - topic_timestamps[0]) / 1e9
        topic_report[topic] = {
            "count": len(topic_timestamps),
            "start_ns": topic_timestamps[0],
            "end_ns": topic_timestamps[-1],
            "duration_s": duration_s,
            "rate_hz": (len(topic_timestamps) - 1) / duration_s if duration_s else None,
            "non_monotonic_intervals": int(np.count_nonzero(deltas <= 0)),
            "max_gap_s": float(deltas.max() / 1e9) if deltas.size else 0.0,
        }

    required_topics = [
        "/camera/image_raw",
        "/joint_states",
        "/crane_plus_arm_controller/controller_state",
        "/crane_plus_gripper_controller/controller_state",
        "/pick_place/task_context",
        "/pick_place/phase",
    ]
    missing = [topic for topic in required_topics if topic not in timestamps]
    common_start = max(timestamps[topic][0] for topic in required_topics if topic in timestamps)
    common_end = min(timestamps[topic][-1] for topic in required_topics if topic in timestamps)

    report = {
        "bag": str(args.bag),
        "valid": not missing and common_end > common_start,
        "missing_required_topics": missing,
        "common_duration_s": (common_end - common_start) / 1e9,
        "image_specs": [
            {
                "width": spec[0],
                "height": spec[1],
                "encoding": spec[2],
                "step": spec[3],
                "count": count,
            }
            for spec, count in sorted(image_specs.items())
        ],
        "topics": topic_report,
    }

    if args.contact_sheet:
        contact_images = images
        if args.contact_sheet_window_topic:
            window = timestamps.get(args.contact_sheet_window_topic)
            if not window:
                raise ValueError(
                    f"Window topic not found: {args.contact_sheet_window_topic}"
                )
            contact_images = [
                item for item in images if window[0] <= item[0] <= window[-1]
            ]
            if not contact_images:
                raise ValueError(
                    "No camera frames overlap contact-sheet window topic: "
                    f"{args.contact_sheet_window_topic}"
                )
        indices = np.linspace(0, len(contact_images) - 1, 5, dtype=int)
        make_contact_sheet(
            [contact_images[index] for index in indices],
            args.contact_sheet,
        )
        report["contact_sheet"] = str(args.contact_sheet)
        report["contact_sheet_window_topic"] = args.contact_sheet_window_topic

    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
