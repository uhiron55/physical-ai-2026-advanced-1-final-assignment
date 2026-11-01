#!/usr/bin/env python3
"""Compare Jev text, image, and image+text strategy selection in ROS 2."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


PROFILES = {
    "direct_clear": {
        "direct_path_clear": True,
        "optimization_goal": "efficiency",
        "route_cue": "green",
        "recommended": "direct_transfer",
    },
    "home_safe": {
        "direct_path_clear": False,
        "optimization_goal": "stability",
        "route_cue": "orange",
        "recommended": "home_transfer",
    },
}


def run(command: str, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-lc", command], check=check, text=True)


def set_model_pose(name: str, z: float) -> None:
    request = (
        f'name: "{name}", position: {{x: 0.18, y: 0.13, z: {z}}}, '
        "orientation: {w: 1.0}"
    )
    run(
        "ign service -s /world/default/set_pose "
        "--reqtype ignition.msgs.Pose --reptype ignition.msgs.Boolean "
        f"--timeout 3000 --req '{request}'"
    )


def set_route_cue(profile: str) -> None:
    visible_z = 1.025
    hidden_z = -1.0
    if profile == "direct_clear":
        set_model_pose("route_direct_cue", visible_z)
        set_model_pose("route_safe_cue", hidden_z)
    else:
        set_model_pose("route_direct_cue", hidden_z)
        set_model_pose("route_safe_cue", visible_z)
    time.sleep(1.5)


class DecisionProbe(Node):
    def __init__(self) -> None:
        super().__init__(f"jev_input_probe_{uuid.uuid4().hex[:8]}")
        self.publisher = self.create_publisher(
            String, "/jev_crane/phase_request", 10
        )
        self.received: dict[str, dict] = {}
        self.create_subscription(String, "/jev_crane/decision", self.on_decision, 10)

    def on_decision(self, message: String) -> None:
        try:
            decision = json.loads(message.data)
        except json.JSONDecodeError:
            return
        request_id = decision.get("request_id")
        if request_id:
            self.received[str(request_id)] = decision

    def request(self, payload: dict, timeout: float) -> tuple[dict, float]:
        deadline = time.monotonic() + timeout
        while self.publisher.get_subscription_count() == 0:
            if time.monotonic() >= deadline:
                raise TimeoutError("The phase selector did not subscribe")
            rclpy.spin_once(self, timeout_sec=0.1)

        request_id = str(payload["request_id"])
        message = String()
        message.data = json.dumps(payload, separators=(",", ":"))
        started = time.perf_counter()
        self.publisher.publish(message)
        while request_id not in self.received:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"No decision for {request_id}")
            rclpy.spin_once(self, timeout_sec=0.1)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return self.received.pop(request_id), latency_ms


def start_selector(mode: str, timeout: float) -> subprocess.Popen:
    command = (
        "ros2 run jev_crane_data_generator phase_selector --ros-args "
        f"-r __node:=jev_phase_selector_probe_{mode} "
        "-p use_jev:=true "
        f"-p input_mode:={mode} "
        f"-p request_timeout:={timeout}"
    )
    return subprocess.Popen(
        ["bash", "-lc", command],
        start_new_session=True,
    )


def stop_selector(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("text", "image", "image_text"),
        default=["text", "image", "image_text"],
    )
    parser.add_argument("--request-timeout", type=float, default=20.0)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()

    if not os.getenv("TYPESAFE_API_KEY"):
        raise RuntimeError("TYPESAFE_API_KEY is required")
    if args.repeats <= 0:
        parser.error("--repeats must be positive")

    rclpy.init()
    probe = DecisionProbe()
    results: list[dict] = []
    try:
        for mode in args.modes:
            selector = start_selector(mode, args.request_timeout)
            try:
                time.sleep(3.0)
                for profile, condition in PROFILES.items():
                    set_route_cue(profile)
                    for repeat_index in range(args.repeats):
                        request_id = (
                            f"probe-{mode}-{profile}-{repeat_index}-"
                            f"{uuid.uuid4().hex[:8]}"
                        )
                        request = {
                            "request_id": request_id,
                            "episode_id": "jev-input-mode-probe",
                            "current_phase": "lifted",
                            "recommended": condition["recommended"],
                            "candidates": ["home_transfer", "direct_transfer"],
                            "task_context": {
                                "route_profile": profile,
                                "direct_path_clear": condition[
                                    "direct_path_clear"
                                ],
                                "optimization_goal": condition[
                                    "optimization_goal"
                                ],
                                "route_cue": condition["route_cue"],
                            },
                        }
                        decision, latency_ms = probe.request(
                            request, args.request_timeout + 5.0
                        )
                        expected = condition["recommended"]
                        results.append(
                            {
                                "input_mode": mode,
                                "route_profile": profile,
                                "repeat_index": repeat_index,
                                "expected": expected,
                                "model_correct": decision.get("model_choice")
                                == expected,
                                "executed_correct": decision.get("choice")
                                == expected,
                                "latency_ms": round(latency_ms, 3),
                                "decision": decision,
                            }
                        )
            finally:
                stop_selector(selector)
    finally:
        probe.destroy_node()
        rclpy.shutdown()

    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": os.getenv("TYPESAFE_DEFAULT_MODEL", "jev-1.14.0"),
        "result_count": len(results),
        "model_correct_count": sum(item["model_correct"] for item in results),
        "executed_correct_count": sum(
            item["executed_correct"] for item in results
        ),
        "fallback_count": sum(
            item["decision"].get("fallback_reason") is not None
            for item in results
        ),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(document, ensure_ascii=False, indent=2))
    api_errors = [
        item
        for item in results
        if str(item["decision"].get("fallback_reason", "")).startswith(
            "api_error:"
        )
    ]
    return 0 if not api_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
