#!/usr/bin/env python3

import base64
import json
import time
import urllib.request

import cv2
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import Float64MultiArray, String
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


ARM_JOINTS = [
    "crane_plus_joint1",
    "crane_plus_joint2",
    "crane_plus_joint4",
    "crane_plus_joint3",
]
GRIPPER_JOINT = "crane_plus_joint_hand"
JOINTS = ARM_JOINTS + [GRIPPER_JOINT]
LIMITS = [
    (-2.618, 2.618),
    (-1.833, 1.798),
    (-1.850, 1.780),
    (-2.566, 2.461),
    (-0.716, 0.681),
]


def clamp(value, lower, upper):
    return max(lower, min(value, upper))


class ActRolloutController(Node):
    def __init__(self):
        super().__init__("act_rollout_controller")
        self.declare_parameter("server_url", "http://127.0.0.1:8765")
        self.declare_parameter("rate_hz", 20.0)
        self.declare_parameter("command_duration", 0.08)
        self.declare_parameter("max_delta", 0.08)
        self.declare_parameter("stop_after_s", 45.0)
        self.declare_parameter("max_steps", 0)
        self.declare_parameter("start_delay_s", 0.5)
        self.declare_parameter("jpeg_quality", 90)

        self.server_url = str(self.get_parameter("server_url").value).rstrip("/")
        self.rate_hz = float(self.get_parameter("rate_hz").value)
        self.command_duration = float(self.get_parameter("command_duration").value)
        self.max_delta = float(self.get_parameter("max_delta").value)
        self.stop_after_s = float(self.get_parameter("stop_after_s").value)
        self.max_steps = int(self.get_parameter("max_steps").value)
        self.start_delay_s = float(self.get_parameter("start_delay_s").value)
        self.jpeg_quality = int(self.get_parameter("jpeg_quality").value)

        self.image = None
        self.state = None
        self.ready_at = time.monotonic() + self.start_delay_s
        self.started = None
        self.step = 0
        self.errors = 0
        self.done = False

        self.arm_pub = self.create_publisher(
            JointTrajectory,
            "/crane_plus_arm_controller/joint_trajectory",
            10,
        )
        self.gripper_pub = self.create_publisher(
            JointTrajectory,
            "/crane_plus_gripper_controller/joint_trajectory",
            10,
        )
        self.action_pub = self.create_publisher(
            Float64MultiArray,
            "/act_rollout/action",
            10,
        )
        self.status_pub = self.create_publisher(String, "/act_rollout/status", 10)
        self.create_subscription(
            Image,
            "/camera/image_raw",
            self.on_image,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            JointState,
            "/joint_states",
            self.on_joint_state,
            qos_profile_sensor_data,
        )
        self.reset_policy()
        self.timer = self.create_timer(1.0 / self.rate_hz, self.tick)

    def reset_policy(self):
        request = urllib.request.Request(
            self.server_url + "/reset",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            json.load(response)

    def on_image(self, message):
        if message.encoding not in ("rgb8", "bgr8"):
            self.get_logger().error(f"Unsupported image encoding: {message.encoding}")
            return
        array = np.frombuffer(message.data, dtype=np.uint8)
        image = array.reshape(message.height, message.step)[:, : message.width * 3]
        image = image.reshape(message.height, message.width, 3)
        if message.encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        self.image = image

    def on_joint_state(self, message):
        values = dict(zip(message.name, message.position))
        if all(name in values for name in JOINTS):
            self.state = [float(values[name]) for name in JOINTS]

    def tick(self):
        if self.done or self.image is None or self.state is None:
            return
        now = time.monotonic()
        if now < self.ready_at:
            return
        if self.started is None:
            self.started = now
        if now - self.started >= self.stop_after_s:
            self.finish("completed", {"reason": "time_limit"})
            return
        ok, encoded = cv2.imencode(
            ".jpg",
            self.image,
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )
        if not ok:
            self.finish("error", {"reason": "jpeg_encode_failed"})
            return
        payload = {
            "image_jpeg": base64.b64encode(encoded).decode("ascii"),
            "state": self.state,
        }
        request = urllib.request.Request(
            self.server_url + "/predict",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.load(response)
            self.errors = 0
        except Exception as exc:
            self.errors += 1
            self.publish_status("error", {"reason": str(exc), "errors": self.errors})
            if self.errors >= 3:
                self.finish("failed", {"reason": "consecutive_inference_errors"})
            return

        raw = [float(value) for value in result["action"]]
        command = []
        for current, target, limits in zip(self.state, raw, LIMITS):
            bounded = clamp(target, limits[0], limits[1])
            command.append(clamp(bounded, current - self.max_delta, current + self.max_delta))
        self.publish_command(command)
        self.step += 1
        if self.max_steps > 0 and self.step >= self.max_steps:
            self.finish("completed", {"reason": "step_limit", "steps": self.step})
            return
        if self.step == 1 or self.step % 20 == 0:
            self.publish_status(
                "running",
                {
                    "step": self.step,
                    "latency_ms": result.get("latency_ms"),
                    "raw_action": raw,
                    "command": command,
                },
            )

    def publish_command(self, command):
        duration_ns = int(self.command_duration * 1_000_000_000)
        arm = JointTrajectory()
        arm.joint_names = ARM_JOINTS
        arm_point = JointTrajectoryPoint()
        arm_point.positions = command[:4]
        arm_point.time_from_start.sec = duration_ns // 1_000_000_000
        arm_point.time_from_start.nanosec = duration_ns % 1_000_000_000
        arm.points.append(arm_point)
        self.arm_pub.publish(arm)

        gripper = JointTrajectory()
        gripper.joint_names = [GRIPPER_JOINT]
        gripper_point = JointTrajectoryPoint()
        gripper_point.positions = [command[4]]
        gripper_point.time_from_start = arm_point.time_from_start
        gripper.points.append(gripper_point)
        self.gripper_pub.publish(gripper)

        message = Float64MultiArray()
        message.data = command
        self.action_pub.publish(message)

    def publish_status(self, status, details):
        message = String()
        message.data = json.dumps(
            {"status": status, **details},
            separators=(",", ":"),
        )
        self.status_pub.publish(message)
        if status != "running":
            self.get_logger().info(message.data)

    def finish(self, status, details):
        self.publish_status(status, details)
        self.done = True
        self.timer.cancel()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = ActRolloutController()
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
