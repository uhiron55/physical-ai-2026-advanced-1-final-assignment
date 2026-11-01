#!/usr/bin/env python3
"""Save one ROS 2 RGB image for camera framing diagnostics."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


class FrameSaver(Node):
    def __init__(self, topic: str, output: Path) -> None:
        super().__init__("camera_frame_saver")
        self.output = output
        self.saved = False
        self.create_subscription(Image, topic, self.on_image, qos_profile_sensor_data)

    def on_image(self, message: Image) -> None:
        if self.saved:
            return
        if message.encoding not in {"rgb8", "bgr8"}:
            raise RuntimeError(f"Unsupported encoding: {message.encoding}")
        image = np.frombuffer(message.data, dtype=np.uint8).reshape(
            message.height,
            message.width,
            3,
        )
        if message.encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(self.output), image):
            raise RuntimeError(f"Failed to write {self.output}")
        self.get_logger().info(
            f"Saved {message.width}x{message.height} {message.encoding} to {self.output}"
        )
        self.saved = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/camera/image_raw")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rclpy.init()
    node = FrameSaver(args.topic, args.output)
    try:
        while rclpy.ok() and not node.saved:
            rclpy.spin_once(node, timeout_sec=1.0)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
