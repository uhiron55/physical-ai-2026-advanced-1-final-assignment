#!/usr/bin/env python3
"""Select a high-level pick-and-place strategy with Jev and safe fallback."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String


DESCRIPTIONS = {
    "home_transfer": (
        "Move to the known home pose before approaching the placement target. "
        "This is longer but provides a stable, repeatable transfer path."
    ),
    "direct_transfer": (
        "Plan directly from the lifted grasp pose to the placement target. "
        "This is shorter but can be harder to plan near the table."
    ),
}

INPUT_MODES = {"text", "image", "image_text"}


class JevPhaseSelector(Node):
    def __init__(self) -> None:
        super().__init__("jev_phase_selector")
        self.declare_parameter("use_jev", True)
        self.declare_parameter("confidence_threshold", 0.55)
        self.declare_parameter("request_timeout", 12.0)
        self.declare_parameter("input_mode", "text")
        self.declare_parameter("image_topic", "/camera/image_raw")
        self.declare_parameter("image_jpeg_quality", 90)

        self.use_jev = bool(self.get_parameter("use_jev").value)
        self.confidence_threshold = float(
            self.get_parameter("confidence_threshold").value
        )
        self.request_timeout = float(self.get_parameter("request_timeout").value)
        self.input_mode = str(self.get_parameter("input_mode").value)
        self.image_topic = str(self.get_parameter("image_topic").value)
        self.image_jpeg_quality = int(
            self.get_parameter("image_jpeg_quality").value
        )
        if self.input_mode not in INPUT_MODES:
            raise ValueError(
                f"input_mode must be one of {sorted(INPUT_MODES)}: "
                f"{self.input_mode}"
            )
        self.api_key = os.getenv("TYPESAFE_API_KEY", "")
        self.model = os.getenv("TYPESAFE_DEFAULT_MODEL", "jev-1.14.0")
        self.latest_image_jpeg: bytes | None = None
        self.latest_image_shape: tuple[int, int] | None = None

        self.selected_pub = self.create_publisher(
            String, "/jev_crane/selected_phase", 10
        )
        self.decision_pub = self.create_publisher(
            String, "/jev_crane/decision", 10
        )
        self.create_subscription(
            String, "/jev_crane/phase_request", self.on_request, 10
        )
        if self.input_mode in {"image", "image_text"}:
            self.create_subscription(
                Image,
                self.image_topic,
                self.on_image,
                qos_profile_sensor_data,
            )

        if self.use_jev and not self.api_key:
            self.get_logger().warning(
                "TYPESAFE_API_KEY is absent; recommended strategy fallback is active."
            )

    def on_image(self, message: Image) -> None:
        if message.encoding not in {"rgb8", "bgr8"}:
            self.get_logger().warning(
                f"Unsupported camera encoding for Jev: {message.encoding}"
            )
            return

        channels = 3
        row_width = message.step or message.width * channels
        raw = np.frombuffer(message.data, dtype=np.uint8)
        expected_size = message.height * row_width
        if raw.size < expected_size:
            self.get_logger().warning("Camera frame is shorter than its ROS metadata")
            return
        image = raw[:expected_size].reshape(message.height, row_width)
        image = image[:, : message.width * channels].reshape(
            message.height, message.width, channels
        )
        if message.encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        # Jev requires both dimensions to be at least 280 px. Preserve the
        # camera geometry by padding instead of stretching the 320 x 240 frame.
        target_side = max(280, message.width, message.height)
        vertical = target_side - message.height
        horizontal = target_side - message.width
        image = cv2.copyMakeBorder(
            image,
            vertical // 2,
            vertical - vertical // 2,
            horizontal // 2,
            horizontal - horizontal // 2,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        encoded, jpeg = cv2.imencode(
            ".jpg",
            image,
            [cv2.IMWRITE_JPEG_QUALITY, self.image_jpeg_quality],
        )
        if not encoded:
            self.get_logger().warning("Failed to encode the camera frame for Jev")
            return
        self.latest_image_jpeg = jpeg.tobytes()
        self.latest_image_shape = (image.shape[1], image.shape[0])

    def on_request(self, message: String) -> None:
        try:
            request_data = json.loads(message.data)
            request_id = str(request_data["request_id"])
            candidates = [str(value) for value in request_data["candidates"]]
            recommended = str(request_data["recommended"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.get_logger().error(f"Invalid phase request: {exc}")
            return

        choice = recommended
        model_choice = None
        confidence = 0.0
        probabilities = {}
        fallback_reason = None

        if self.use_jev and self.api_key:
            try:
                result = self.ask_jev(request_data, candidates)
                model_choice = result["choice"]
                confidence = result["confidence"]
                probabilities = result["probabilities"]
                if model_choice not in candidates:
                    fallback_reason = "invalid_choice"
                elif confidence < self.confidence_threshold:
                    fallback_reason = "low_confidence"
                else:
                    choice = model_choice
            except Exception as exc:
                fallback_reason = f"api_error:{type(exc).__name__}"
                self.get_logger().warning(f"Jev request failed: {exc}")
        else:
            fallback_reason = "jev_disabled" if not self.use_jev else "missing_api_key"

        selected = String()
        selected.data = f"{request_id}|{choice}"
        self.selected_pub.publish(selected)

        decision = {
            "request_id": request_id,
            "episode_id": request_data.get("episode_id"),
            "decision_type": "transfer_strategy",
            "current_phase": request_data.get("current_phase"),
            "candidates": candidates,
            "recommended": recommended,
            "model": self.model if self.use_jev else None,
            "input_mode": self.input_mode,
            "image_available": self.latest_image_jpeg is not None,
            "image_shape": self.latest_image_shape,
            "model_choice": model_choice,
            "choice": choice,
            "confidence": confidence,
            "probabilities": probabilities,
            "fallback_reason": fallback_reason,
            "task_context": request_data.get("task_context", {}),
        }
        decision_message = String()
        decision_message.data = json.dumps(
            decision, separators=(",", ":"), ensure_ascii=True
        )
        self.decision_pub.publish(decision_message)
        self.get_logger().info(
            f"strategy={choice}, confidence={confidence:.2f}, "
            f"fallback={fallback_reason}"
        )

    def ask_jev(self, request_data: dict, candidates: list[str]) -> dict:
        criteria = {
            candidate: DESCRIPTIONS.get(candidate, candidate)
            for candidate in candidates
        }
        task_context = request_data.get("task_context", {})
        use_image = self.input_mode in {"image", "image_text"}
        use_text_context = self.input_mode in {"text", "image_text"}
        if use_image and self.latest_image_jpeg is None:
            raise RuntimeError("No camera frame is available for Jev image input")

        state = {
            "task": (
                "Choose a safe transfer strategy for a simulated CRANE+ "
                "pick-and-place episode after the cube has been grasped and lifted."
            ),
            "current_phase": request_data.get("current_phase"),
            "candidate_descriptions": criteria,
        }
        if use_text_context:
            state["task_context"] = task_context
        if use_image:
            state["camera_frame"] = "jev-camera-frame"

        if self.input_mode == "text":
            instructions = (
                "Choose one candidate from the supplied task context. "
                "When direct_path_clear is true and optimization_goal is "
                "efficiency, choose direct_transfer. When direct_path_clear "
                "is false or optimization_goal is stability, choose "
                "home_transfer."
            )
        elif self.input_mode == "image":
            instructions = (
                "Inspect `camera_frame` and choose one candidate. A visible green "
                "route cue means the direct route is clear and favors "
                "direct_transfer. A visible orange route cue means the stable "
                "route through home is required and favors home_transfer."
            )
        else:
            instructions = (
                "Inspect `camera_frame` and the supplied task_context, then choose "
                "one candidate. The visible route cue and structured context encode "
                "the same condition and should agree."
            )

        payload = {
            "model": self.model,
            "state": state,
            "questions": {
                "next_strategy": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
                }
            },
        }
        if use_image:
            payload["assets"] = {
                "jev-camera-frame": {
                    "type": "image",
                    "format": "jpg",
                    "data_base64": base64.b64encode(
                        self.latest_image_jpeg
                    ).decode("ascii"),
                }
            }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if use_image:
            headers["TypeSafe-Danger-Zone-Images"] = "true"
        request = urllib.request.Request(
            "https://api.typesafe.ai/v1/systemone",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.request_timeout
            ) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Jev HTTP {exc.code}") from exc
        resolved_model = body.get("model")
        if resolved_model != self.model:
            raise RuntimeError(
                f"Jev model mismatch: requested {self.model}, resolved {resolved_model}"
            )
        answer = body["answers"]["next_strategy"]
        return {
            "choice": answer.get("choice"),
            "confidence": float(answer.get("confidence", 0.0)),
            "probabilities": answer.get("probabilities", {}),
        }


def main(args=None) -> None:
    rclpy.init(args=args)
    node = JevPhaseSelector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
