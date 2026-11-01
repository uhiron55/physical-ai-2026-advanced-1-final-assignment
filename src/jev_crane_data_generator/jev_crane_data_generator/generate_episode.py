#!/usr/bin/env python3

import json
import os
import time
import urllib.error
import urllib.request

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray, String
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


ARM_JOINTS = [
    "crane_plus_joint1",
    "crane_plus_joint2",
    "crane_plus_joint4",
    "crane_plus_joint3",
]
GRIPPER_JOINT = "crane_plus_joint_hand"
ARM_LIMITS = [
    (-1.5, 1.5),
    (-1.0, 1.0),
    (-1.2, 1.2),
    (-1.2, 1.2),
]
TARGETS = [
    [0.35, -0.25, 0.30, 0.20],
    [-0.35, -0.20, 0.25, -0.20],
    [0.20, 0.30, -0.25, 0.30],
]


def clamp(value, lower, upper):
    return max(lower, min(value, upper))


class JevCraneEpisode(Node):
    def __init__(self):
        super().__init__("jev_crane_data_generator")

        self.declare_parameter("episode_id", "episode-000")
        self.declare_parameter("target_index", 0)
        self.declare_parameter("decision_interval", 0.8)
        self.declare_parameter("command_duration", 0.55)
        self.declare_parameter("step_size", 0.12)
        self.declare_parameter("goal_tolerance", 0.035)
        self.declare_parameter("confidence_threshold", 0.55)
        self.declare_parameter("max_decisions", 40)
        self.declare_parameter("gripper_open", -0.5236)
        self.declare_parameter("use_jev", True)

        self.episode_id = str(self.get_parameter("episode_id").value)
        target_index = int(self.get_parameter("target_index").value)
        self.target = TARGETS[target_index % len(TARGETS)].copy()
        self.decision_interval = float(self.get_parameter("decision_interval").value)
        self.command_duration = float(self.get_parameter("command_duration").value)
        self.step_size = float(self.get_parameter("step_size").value)
        self.goal_tolerance = float(self.get_parameter("goal_tolerance").value)
        self.confidence_threshold = float(
            self.get_parameter("confidence_threshold").value
        )
        self.max_decisions = int(self.get_parameter("max_decisions").value)
        self.gripper_open = float(self.get_parameter("gripper_open").value)
        self.use_jev = bool(self.get_parameter("use_jev").value)

        self.api_key = os.getenv("TYPESAFE_API_KEY", "")
        self.model = os.getenv("TYPESAFE_DEFAULT_MODEL", "jev-latest")
        if self.use_jev and not self.api_key:
            raise RuntimeError("TYPESAFE_API_KEY is required when use_jev=true")

        self.current = None
        self.command = None
        self.phase = "reach_target"
        self.decision_count = 0
        self.last_decision_time = 0.0
        self.last_error = None
        self.nonprogress_count = 0
        self.done = False
        self.exit_code = 1
        self.started_published = False

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
            "/jev_crane/action",
            10,
        )
        self.decision_pub = self.create_publisher(
            String,
            "/jev_crane/decision",
            10,
        )
        self.episode_pub = self.create_publisher(
            String,
            "/jev_crane/episode_state",
            10,
        )
        self.create_subscription(
            JointState,
            "/joint_states",
            self.on_joint_state,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            f"Episode {self.episode_id}: target={self.target}, model={self.model}"
        )

    def on_joint_state(self, msg):
        positions = dict(zip(msg.name, msg.position))
        if not all(name in positions for name in ARM_JOINTS):
            return
        self.current = [float(positions[name]) for name in ARM_JOINTS]
        if self.command is None:
            self.command = self.current.copy()

    def tick(self):
        if self.done or self.current is None:
            return
        now = time.monotonic()
        if not self.started_published:
            self.publish_episode("started", {"target": self.target})
            self.started_published = True
            self.last_decision_time = now
            return
        if now - self.last_decision_time < self.decision_interval:
            return
        self.last_decision_time = now

        active_target = self.target if self.phase == "reach_target" else [0.0] * 4
        errors = [target - value for target, value in zip(active_target, self.current)]
        max_error = max(abs(value) for value in errors)

        if max_error <= self.goal_tolerance:
            if self.phase == "reach_target":
                self.phase = "return_home"
                self.last_error = None
                self.nonprogress_count = 0
                self.publish_episode("target_reached", {"current": self.current})
                self.get_logger().info("Target reached; returning to home pose.")
                return
            self.publish_episode(
                "completed",
                {"current": self.current, "decisions": self.decision_count},
            )
            self.get_logger().info(
                f"Episode complete after {self.decision_count} decisions."
            )
            self.exit_code = 0
            self.done = True
            return

        self.decision_count += 1
        if self.decision_count > self.max_decisions:
            self.publish_episode(
                "failed",
                {"reason": "max_decisions", "current": self.current},
            )
            self.get_logger().error("Episode failed: maximum decisions exceeded.")
            self.done = True
            return

        if self.last_error is not None and max_error >= self.last_error - 0.005:
            self.nonprogress_count += 1
        else:
            self.nonprogress_count = 0
        self.last_error = max_error

        candidates = self.make_candidates(active_target, errors)
        fallback_choice = max(
            candidates,
            key=lambda name: candidates[name]["expected_reduction"],
        )

        response = None
        fallback_reason = None
        if self.use_jev:
            try:
                response = self.ask_jev(active_target, errors, candidates)
            except Exception as exc:  # Preserve the episode through transient API errors.
                fallback_reason = f"api_error:{type(exc).__name__}"
                self.get_logger().warning(f"Jev request failed; fallback used: {exc}")

        choice = response.get("choice") if response else None
        confidence = float(response.get("confidence", 0.0)) if response else 0.0
        if choice not in candidates:
            fallback_reason = fallback_reason or "invalid_choice"
        elif confidence < self.confidence_threshold:
            fallback_reason = "low_confidence"
        elif self.nonprogress_count >= 2:
            fallback_reason = "nonprogress_guard"

        if fallback_reason:
            choice = fallback_choice

        selected = candidates[choice]
        self.command = selected["positions"]
        self.publish_commands()
        self.publish_decision(
            {
                "episode_id": self.episode_id,
                "phase": self.phase,
                "decision_index": self.decision_count,
                "model": response.get("model") if response else None,
                "current": self.current,
                "target": active_target,
                "errors": errors,
                "choice": choice,
                "confidence": confidence,
                "probabilities": response.get("probabilities", {}) if response else {},
                "fallback_reason": fallback_reason,
                "command": self.command,
            }
        )
        self.get_logger().info(
            f"{self.phase} #{self.decision_count}: {choice}, "
            f"confidence={confidence:.2f}, fallback={fallback_reason}"
        )

    def make_candidates(self, target, errors):
        candidates = {}
        for index, error in enumerate(errors):
            if abs(error) <= self.goal_tolerance:
                continue
            next_positions = self.command.copy()
            delta = max(-self.step_size, min(self.step_size, error))
            lower, upper = ARM_LIMITS[index]
            next_positions[index] = clamp(next_positions[index] + delta, lower, upper)
            label = f"joint_{index + 1}_toward_target"
            candidates[label] = {
                "positions": next_positions,
                "expected_reduction": min(abs(error), abs(delta)),
                "description": (
                    f"Move {ARM_JOINTS[index]} by {delta:+.3f} rad toward its target; "
                    f"current error is {error:+.3f} rad."
                ),
            }

        if not candidates:
            candidates["hold"] = {
                "positions": self.command.copy(),
                "expected_reduction": 0.0,
                "description": "Hold position because all joints are within tolerance.",
            }
        return candidates

    def ask_jev(self, target, errors, candidates):
        criteria = {name: value["description"] for name, value in candidates.items()}
        payload = {
            "model": self.model,
            "state": {
                "task": "Reach the target joint pose safely and efficiently in simulation.",
                "phase": self.phase,
                "joint_order": ARM_JOINTS,
                "current_positions_rad": self.current,
                "target_positions_rad": target,
                "errors_rad": errors,
                "joint_limits_rad": ARM_LIMITS,
                "decision_index": self.decision_count,
            },
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": (
                        "Choose the single safe candidate that most reduces the largest "
                        "remaining joint error. Prefer direct progress and remain within limits."
                    ),
                    "criteria": criteria,
                }
            },
        }
        request = urllib.request.Request(
            "https://api.typesafe.ai/v1/systemone",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Jev HTTP {exc.code}") from exc
        answer = body["answers"]["next_action"]
        return {
            "model": body.get("model"),
            "choice": answer.get("choice"),
            "confidence": answer.get("confidence", 0.0),
            "probabilities": answer.get("probabilities", {}),
        }

    def publish_commands(self):
        arm = JointTrajectory()
        arm.joint_names = ARM_JOINTS
        point = JointTrajectoryPoint()
        point.positions = self.command
        duration_ns = int(self.command_duration * 1_000_000_000)
        point.time_from_start.sec = duration_ns // 1_000_000_000
        point.time_from_start.nanosec = duration_ns % 1_000_000_000
        arm.points.append(point)
        self.arm_pub.publish(arm)

        gripper = JointTrajectory()
        gripper.joint_names = [GRIPPER_JOINT]
        gripper_point = JointTrajectoryPoint()
        gripper_point.positions = [self.gripper_open]
        gripper_point.time_from_start = point.time_from_start
        gripper.points.append(gripper_point)
        self.gripper_pub.publish(gripper)

        action = Float64MultiArray()
        action.data = self.command + [self.gripper_open]
        self.action_pub.publish(action)

    def publish_decision(self, payload):
        message = String()
        message.data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        self.decision_pub.publish(message)

    def publish_episode(self, event, details):
        message = String()
        message.data = json.dumps(
            {
                "episode_id": self.episode_id,
                "event": event,
                "phase": self.phase,
                "details": details,
            },
            separators=(",", ":"),
            ensure_ascii=True,
        )
        self.episode_pub.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = JevCraneEpisode()
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.05)
            node.tick()
        time.sleep(0.5)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        exit_code = node.exit_code
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
