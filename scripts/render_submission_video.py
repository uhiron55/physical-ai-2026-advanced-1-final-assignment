#!/usr/bin/env python3
"""Render a compact submission video from successful expert and ACT rollout bags."""

import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from rclpy.serialization import deserialize_message
from rosbag2_py import ConverterOptions, SequentialReader, StorageOptions
from rosidl_runtime_py.utilities import get_message


WIDTH = 1280
HEIGHT = 720
VIDEO_WIDTH = 960
FPS = 15
BG = (25, 35, 42)
WHITE = (240, 244, 247)
MUTED = (170, 183, 193)


def open_reader(path: Path):
    reader = SequentialReader()
    reader.open(
        StorageOptions(uri=str(path), storage_id="sqlite3"),
        ConverterOptions("cdr", "cdr"),
    )
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    return reader, types


def image_frames(path: Path, start_ns=None, end_ns=None):
    reader, types = open_reader(path)
    message_type = get_message(types["/camera/image_raw"])
    frames = []
    while reader.has_next():
        topic, data, timestamp = reader.read_next()
        if topic != "/camera/image_raw":
            continue
        if start_ns is not None and timestamp < start_ns:
            continue
        if end_ns is not None and timestamp > end_ns:
            continue
        message = deserialize_message(data, message_type)
        array = np.frombuffer(message.data, dtype=np.uint8)
        image = array.reshape(message.height, message.step)[:, : message.width * 3]
        image = image.reshape(message.height, message.width, 3)
        if message.encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        elif message.encoding != "bgr8":
            raise ValueError(f"Unsupported image encoding: {message.encoding}")
        frames.append((timestamp, image.copy()))
    return frames


def action_window(path: Path):
    reader, _ = open_reader(path)
    timestamps = []
    while reader.has_next():
        topic, _, timestamp = reader.read_next()
        if topic == "/act_rollout/action":
            timestamps.append(timestamp)
    if not timestamps:
        raise RuntimeError(f"No ACT actions in {path}")
    return timestamps[0] - 1_000_000_000, timestamps[-1] + 1_000_000_000


def put_text(canvas, text, origin, scale=0.7, color=WHITE, thickness=2):
    cv2.putText(
        canvas,
        text,
        origin,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def slide(title, lines, accent, seconds):
    canvas = np.full((HEIGHT, WIDTH, 3), BG, dtype=np.uint8)
    cv2.rectangle(canvas, (70, 75), (82, 645), accent, -1)
    put_text(canvas, title, (120, 165), 1.25, WHITE, 3)
    y = 260
    for line in lines:
        put_text(canvas, line, (120, y), 0.72, MUTED, 2)
        y += 58
    return [canvas.copy() for _ in range(round(seconds * FPS))]


def compose(frame, title, accent, details, progress, speed):
    canvas = np.full((HEIGHT, WIDTH, 3), BG, dtype=np.uint8)
    canvas[:, :VIDEO_WIDTH] = cv2.resize(frame, (VIDEO_WIDTH, HEIGHT))
    cv2.rectangle(canvas, (VIDEO_WIDTH, 0), (WIDTH, HEIGHT), BG, -1)
    cv2.rectangle(canvas, (VIDEO_WIDTH, 0), (VIDEO_WIDTH + 8, HEIGHT), accent, -1)
    put_text(canvas, title, (995, 80), 0.78, accent, 2)
    put_text(canvas, speed, (995, 120), 0.55, MUTED, 1)
    y = 190
    for label, value in details:
        put_text(canvas, label.upper(), (995, y), 0.46, MUTED, 1)
        put_text(canvas, value, (995, y + 34), 0.55, WHITE, 1)
        y += 92
    x0, x1, y0 = 995, 1240, 665
    cv2.rectangle(canvas, (x0, y0), (x1, y0 + 8), (70, 82, 91), -1)
    cv2.rectangle(canvas, (x0, y0), (x0 + round((x1 - x0) * progress), y0 + 8), accent, -1)
    return canvas


def segment(path, title, accent, details, playback_speed, window=None):
    frames = image_frames(path, *(window or (None, None)))
    if not frames:
        raise RuntimeError(f"No camera frames in {path}")
    first = frames[0][0]
    last = frames[-1][0]
    duration = max((last - first) / 1e9, 1 / FPS)
    output_count = max(1, round(duration * FPS / playback_speed))
    result = []
    for index in range(output_count):
        source_time = first + int((index / FPS) * playback_speed * 1e9)
        source_index = min(
            range(len(frames)),
            key=lambda item: abs(frames[item][0] - source_time),
        )
        result.append(
            compose(
                frames[source_index][1],
                title,
                accent,
                details,
                index / max(output_count - 1, 1),
                f"{playback_speed:g}x playback",
            )
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct-bag", type=Path, required=True)
    parser.add_argument("--safe-bag", type=Path, required=True)
    parser.add_argument("--act-bag", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    frames = []
    frames += slide(
        "AI-Guided CRANE+ Pick-and-Place",
        [
            "Jev selects a route strategy from the visible cue.",
            "MoveIt 2 executes demonstrations through ROS 2.",
            "ACT learns image + joint state -> joint action chunks.",
        ],
        (94, 211, 230),
        5,
    )
    frames += segment(
        args.direct_bag,
        "TEACHER / DIRECT",
        (90, 214, 120),
        [
            ("visual cue", "green"),
            ("decision", "direct_transfer"),
            ("result", "success / 5.93 mm"),
        ],
        2,
    )
    frames += segment(
        args.safe_bag,
        "TEACHER / SAFE",
        (70, 160, 245),
        [
            ("visual cue", "orange"),
            ("decision", "home_transfer"),
            ("result", "success / 7.58 mm"),
        ],
        2,
    )
    frames += segment(
        args.act_bag,
        "LEARNED POLICY / ACT",
        (210, 125, 245),
        [
            ("checkpoint", "FP32 / 2,000 steps"),
            ("control", "20 Hz closed loop"),
            ("result", "incomplete"),
        ],
        4,
        action_window(args.act_bag),
    )
    frames += slide(
        "Measured Results",
        [
            "20 successful demonstrations / 15,016 synchronized frames",
            "Jev decisions: 20/20, confidence 1.00, no fallback",
            "ACT offline first-action MAE: 0.0461 at 2,000 steps",
            "Teacher succeeds; learned full-task policy remains incomplete",
            "Failures are retained as evaluation evidence.",
        ],
        (94, 211, 230),
        8,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        intermediate = Path(directory) / "submission-mp4v.mp4"
        writer = cv2.VideoWriter(
            str(intermediate),
            cv2.VideoWriter_fourcc(*"mp4v"),
            FPS,
            (WIDTH, HEIGHT),
        )
        if not writer.isOpened():
            raise RuntimeError("OpenCV could not create the intermediate video")
        for frame in frames:
            writer.write(frame)
        writer.release()
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(intermediate),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(args.output),
            ],
            check=True,
        )
    print(args.output)


if __name__ == "__main__":
    main()
