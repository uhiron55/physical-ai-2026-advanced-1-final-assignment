#!/usr/bin/env python3
"""Collect parameterized CRANE+ pick-and-place episodes in Gazebo."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/workspace/artifacts/rosbags/pick_place_variations")
TOPICS = [
    "/camera/image_raw",
    "/joint_states",
    "/crane_plus_arm_controller/controller_state",
    "/crane_plus_gripper_controller/controller_state",
    "/pick_place/task_context",
    "/pick_place/phase",
    "/jev_crane/phase_request",
    "/jev_crane/decision",
]

# Start close to the official fixed condition and expand only within a narrow range.
EPISODES = [
    ("pick-place-var-201", 0.000, -0.100, 0.150, 0.000, "home_safe"),
    ("pick-place-var-202", 0.000, -0.099, 0.150, 0.000, "home_safe"),
    ("pick-place-var-203", 0.000, -0.101, 0.150, 0.000, "home_safe"),
    ("pick-place-var-204", 0.000, -0.098, 0.150, 0.000, "home_safe"),
    ("pick-place-var-205", 0.000, -0.102, 0.150, 0.000, "home_safe"),
    ("pick-place-var-206", 0.000, -0.097, 0.150, 0.000, "home_safe"),
    ("pick-place-var-207", 0.000, -0.103, 0.150, 0.000, "home_safe"),
]


def run(command: str, *, check: bool = True, capture: bool = False):
    return subprocess.run(
        ["bash", "-lc", command],
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def reset_cube(x: float, y: float) -> None:
    request = (
        'name: "wood_cube_5cm", position: {'
        f"x: {x}, y: {y}, z: 1.015"
        "}, orientation: {w: 1.0}"
    )
    run(
        "ign service -s /world/default/set_pose "
        "--reqtype ignition.msgs.Pose --reptype ignition.msgs.Boolean "
        f"--timeout 3000 --req '{request}'"
    )
    time.sleep(1.0)


def set_model_pose(name: str, x: float, y: float, z: float) -> None:
    request = (
        f'name: "{name}", position: {{x: {x}, y: {y}, z: {z}}}, '
        "orientation: {w: 1.0}"
    )
    run(
        "ign service -s /world/default/set_pose "
        "--reqtype ignition.msgs.Pose --reptype ignition.msgs.Boolean "
        f"--timeout 3000 --req '{request}'"
    )


def set_route_cue(route_profile: str) -> dict[str, object]:
    visible_pose = (0.18, 0.13, 1.025)
    hidden_pose = (0.18, 0.13, -1.0)
    if route_profile == "direct_clear":
        set_model_pose("route_direct_cue", *visible_pose)
        set_model_pose("route_safe_cue", *hidden_pose)
        return {
            "route_profile": route_profile,
            "direct_path_clear": True,
            "optimization_goal": "efficiency",
            "route_cue": "green",
            "recommended_strategy": "direct_transfer",
        }
    set_model_pose("route_direct_cue", *hidden_pose)
    set_model_pose("route_safe_cue", *visible_pose)
    return {
        "route_profile": "home_safe",
        "direct_path_clear": False,
        "optimization_goal": "stability",
        "route_cue": "orange",
        "recommended_strategy": "home_transfer",
    }


def cube_pose() -> dict[str, float]:
    output = run(
        "ign topic -e -t /world/default/pose/info -n 1",
        capture=True,
    ).stdout
    match = re.search(
        r'name: "wood_cube_5cm".*?position \{\s*'
        r'x: ([^\s]+)\s*y: ([^\s]+)\s*z: ([^\s]+)',
        output,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError("wood_cube_5cm pose was not found")
    return {
        "x": float(match.group(1)),
        "y": float(match.group(2)),
        "z": float(match.group(3)),
    }


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)


def collect_episode(
    episode_id: str,
    cube_x: float,
    cube_y: float,
    place_x: float,
    place_y: float,
    route_profile: str,
    jev_input_mode: str,
    velocity_scale: float,
    use_jev: bool,
) -> dict:
    output_dir = ROOT / episode_id
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {output_dir}")

    route_context = set_route_cue(route_profile)
    reset_cube(cube_x, cube_y)
    before = cube_pose()
    bag_command = (
        "source /opt/ros/humble/setup.bash; "
        "source /home/ubuntu/airobot_ws/install/setup.bash; "
        f"ros2 bag record -o '{output_dir}' {' '.join(TOPICS)}"
    )
    bag = subprocess.Popen(["bash", "-lc", bag_command])
    time.sleep(1.5)

    launch_command = (
        "source /opt/ros/humble/setup.bash; "
        "source /home/ubuntu/airobot_ws/install/setup.bash; "
        "source /workspace/install_integrated/setup.bash; "
        "timeout --signal=INT --kill-after=5s 70s "
        "ros2 launch parameterized_pick_place pick_and_place.launch.py "
        f"episode_id:={episode_id} cube_x:={cube_x} cube_y:={cube_y} "
        f"place_x:={place_x} place_y:={place_y} "
        f"route_profile:={route_context['route_profile']} "
        f"direct_path_clear:={str(route_context['direct_path_clear']).lower()} "
        f"optimization_goal:={route_context['optimization_goal']} "
        f"route_cue:={route_context['route_cue']} "
        f"recommended_strategy:={route_context['recommended_strategy']} "
        f"jev_input_mode:={jev_input_mode} "
        f"use_jev:={str(use_jev).lower()} "
        f"velocity_scale:={velocity_scale} acceleration_scale:={velocity_scale}"
    )
    started = time.monotonic()
    try:
        result = run(launch_command, check=False)
    finally:
        time.sleep(0.75)
        stop_process(bag)

    after = cube_pose()
    expected_x = place_x + 0.10
    expected_y = place_y
    position_error = (
        (after["x"] - expected_x) ** 2 +
        (after["y"] - expected_y) ** 2
    ) ** 0.5
    moved = (
        (after["x"] - before["x"]) ** 2 +
        (after["y"] - before["y"]) ** 2
    ) ** 0.5
    success = (
        result.returncode == 0
        and moved > 0.10
        and position_error < 0.06
        and 1.03 < after["z"] < 1.09
    )
    return {
        "episode_id": episode_id,
        "parameters": {
            "cube_x": cube_x,
            "cube_y": cube_y,
            "place_x": place_x,
            "place_y": place_y,
            "jev_input_mode": jev_input_mode,
            "use_jev": use_jev,
            "velocity_scale": velocity_scale,
            **route_context,
        },
        "bag_path": str(output_dir),
        "before": before,
        "after": after,
        "expected_final": {"x": expected_x, "y": expected_y, "z": 1.065},
        "moved_xy_m": moved,
        "position_error_m": position_error,
        "returncode": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "success": success,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-id", type=int)
    parser.add_argument("--episode-count", type=int)
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--manifest-name", default="manifest.json")
    parser.add_argument(
        "--jev-input-mode",
        choices=("text", "image", "image_text"),
        default="text",
    )
    parser.add_argument(
        "--use-jev",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--cube-x-min", type=float, default=0.0)
    parser.add_argument("--cube-x-max", type=float, default=0.0)
    parser.add_argument("--cube-y-min", type=float, default=-0.103)
    parser.add_argument("--cube-y-max", type=float, default=-0.097)
    parser.add_argument("--place-y-min", type=float, default=0.0)
    parser.add_argument("--place-y-max", type=float, default=0.0)
    parser.add_argument("--velocity-min", type=float, default=0.8)
    parser.add_argument("--velocity-max", type=float, default=0.8)
    parser.add_argument(
        "--route-profile",
        choices=("home_safe", "direct_clear", "mixed"),
        default="home_safe",
    )
    args = parser.parse_args()

    for minimum, maximum, label in (
        (args.cube_x_min, args.cube_x_max, "cube-x"),
        (args.cube_y_min, args.cube_y_max, "cube-y"),
        (args.place_y_min, args.place_y_max, "place-y"),
        (args.velocity_min, args.velocity_max, "velocity"),
    ):
        if minimum > maximum:
            parser.error(f"--{label}-min must not exceed --{label}-max")

    if (args.start_id is None) != (args.episode_count is None):
        parser.error("--start-id and --episode-count must be specified together")
    episodes = EPISODES
    if args.episode_count is not None:
        rng = random.Random(args.seed)
        episodes = []
        for index in range(args.episode_count):
            route_profile = args.route_profile
            if route_profile == "mixed":
                route_profile = "direct_clear" if index % 2 == 0 else "home_safe"
            episodes.append(
                (
                    f"pick-place-var-{args.start_id + index:03d}",
                    round(rng.uniform(args.cube_x_min, args.cube_x_max), 6),
                    round(rng.uniform(args.cube_y_min, args.cube_y_max), 6),
                    0.15,
                    round(rng.uniform(args.place_y_min, args.place_y_max), 6),
                    route_profile,
                    args.jev_input_mode,
                    round(rng.uniform(args.velocity_min, args.velocity_max), 4),
                    args.use_jev,
                )
            )
    else:
        episodes = [
            (*episode, args.jev_input_mode, args.velocity_min, args.use_jev)
            for episode in episodes
        ]

    ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / args.manifest_name
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": str(Path(__file__).resolve()),
        "seed": args.seed if args.episode_count is not None else None,
        "jev_input_mode": args.jev_input_mode,
        "use_jev": args.use_jev,
        "sampling_ranges": {
            "cube_x": [args.cube_x_min, args.cube_x_max],
            "cube_y": [args.cube_y_min, args.cube_y_max],
            "place_y": [args.place_y_min, args.place_y_max],
            "velocity_scale": [args.velocity_min, args.velocity_max],
        },
        "episodes": [],
    }
    for spec in episodes:
        print(f"\n=== {spec[0]} ===", flush=True)
        try:
            record = collect_episode(*spec)
        except Exception as exc:  # Preserve progress and make failures auditable.
            record = {
                "episode_id": spec[0],
                "parameters": {
                    "cube_x": spec[1],
                    "cube_y": spec[2],
                    "place_x": spec[3],
                    "place_y": spec[4],
                    "route_profile": spec[5],
                    "jev_input_mode": spec[6],
                    "velocity_scale": spec[7],
                    "use_jev": spec[8],
                },
                "success": False,
                "error": repr(exc),
            }
        manifest["episodes"].append(record)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)

    successes = sum(item.get("success", False) for item in manifest["episodes"])
    print(f"\nCollected {successes}/{len(episodes)} successful episodes")
    return 0 if successes else 1


if __name__ == "__main__":
    raise SystemExit(main())
