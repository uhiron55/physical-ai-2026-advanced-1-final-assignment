#!/usr/bin/env python3
"""Place Gazebo at the start of one clipped grasp-and-lift holdout episode."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import pyarrow.dataset as ds


ARM_JOINTS = [
    "crane_plus_joint1",
    "crane_plus_joint2",
    "crane_plus_joint4",
    "crane_plus_joint3",
]
GRIPPER_JOINT = "crane_plus_joint_hand"


def run(command: str) -> None:
    subprocess.run(["bash", "-lc", command], check=True)


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


def set_route_cue(route_profile: str) -> None:
    visible = (0.18, 0.13, 1.025)
    hidden = (0.18, 0.13, -1.0)
    if route_profile == "direct_clear":
        set_model_pose("route_direct_cue", *visible)
        set_model_pose("route_safe_cue", *hidden)
    else:
        set_model_pose("route_direct_cue", *hidden)
        set_model_pose("route_safe_cue", *visible)


def first_state(dataset_root: Path, episode_index: int) -> list[float]:
    table = ds.dataset(dataset_root / "data", format="parquet").to_table(
        columns=["frame_index", "observation.state"],
        filter=ds.field("episode_index") == episode_index,
    )
    rows = sorted(
        zip(
            table.column("frame_index").to_pylist(),
            table.column("observation.state").to_pylist(),
        ),
        key=lambda row: row[0],
    )
    if not rows:
        raise ValueError(f"Episode {episode_index} is not present in {dataset_root}")
    state = [float(value) for value in rows[0][1]]
    if len(state) != 5:
        raise ValueError(f"Expected five joint values, got {len(state)}")
    return state


def publish_trajectory(state: list[float], duration_s: float) -> None:
    seconds = int(duration_s)
    nanoseconds = int((duration_s - seconds) * 1_000_000_000)
    arm_positions = ", ".join(f"{value:.9f}" for value in state[:4])
    arm_names = ", ".join(f"'{name}'" for name in ARM_JOINTS)
    arm_message = (
        f"{{joint_names: [{arm_names}], points: [{{positions: [{arm_positions}], "
        f"time_from_start: {{sec: {seconds}, nanosec: {nanoseconds}}}}}]}}"
    )
    gripper_message = (
        f"{{joint_names: ['{GRIPPER_JOINT}'], points: [{{positions: [{state[4]:.9f}], "
        f"time_from_start: {{sec: {seconds}, nanosec: {nanoseconds}}}}}]}}"
    )
    setup = (
        "source /opt/ros/humble/setup.bash; "
        "source /home/ubuntu/airobot_ws/install/setup.bash; "
        "source /workspace/install_integrated/setup.bash; "
    )
    run(
        setup
        + "ros2 topic pub --once /crane_plus_arm_controller/joint_trajectory "
        + f' trajectory_msgs/msg/JointTrajectory "{arm_message}"'
    )
    run(
        setup
        + "ros2 topic pub --once /crane_plus_gripper_controller/joint_trajectory "
        + f' trajectory_msgs/msg/JointTrajectory "{gripper_message}"'
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--episode-index", type=int, default=0)
    parser.add_argument("--move-duration", type=float, default=3.0)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    episodes = manifest.get("episodes", manifest)
    episode = episodes[args.episode_index]
    parameters = episode["parameters"]
    state = first_state(args.dataset_root, args.episode_index)

    # Keep the cube away while the arm travels from home to the clipped
    # episode's start pose. Otherwise the setup motion can move the cube
    # before policy evaluation begins.
    set_model_pose("wood_cube_5cm", 0.0, 0.0, -1.0)
    set_route_cue(str(parameters["route_profile"]))
    publish_trajectory(state, args.move_duration)
    time.sleep(args.move_duration + 0.5)
    set_model_pose(
        "wood_cube_5cm",
        float(parameters["cube_x"]),
        float(parameters["cube_y"]),
        1.015,
    )
    time.sleep(1.0)
    print(
        json.dumps(
            {
                "episode_index": args.episode_index,
                "episode_id": episode["episode_id"],
                "cube_x": parameters["cube_x"],
                "cube_y": parameters["cube_y"],
                "route_profile": parameters["route_profile"],
                "initial_state": state,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
