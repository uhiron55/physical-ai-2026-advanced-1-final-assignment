#!/usr/bin/env python3
"""Convert successful parameterized pick-and-place bags to LeRobot."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np
import torch
try:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
except ImportError:  # LeRobot <= 0.4 compatibility.
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_types_from_msg, get_typestore


JOINT_ORDER = [
    "crane_plus_joint1",
    "crane_plus_joint2",
    "crane_plus_joint4",
    "crane_plus_joint3",
    "crane_plus_joint_hand",
]
ARM_TOPIC = "/crane_plus_arm_controller/controller_state"
GRIPPER_TOPIC = "/crane_plus_gripper_controller/controller_state"
JOINT_TOPIC = "/joint_states"
CONTEXT_TOPIC = "/pick_place/task_context"
CAMERA_TOPIC = "/camera/image_raw"
PHASE_TOPIC = "/pick_place/phase"

CONTROLLER_STATE_MSG = """
std_msgs/Header header
string[] joint_names
trajectory_msgs/JointTrajectoryPoint reference
trajectory_msgs/JointTrajectoryPoint feedback
trajectory_msgs/JointTrajectoryPoint error
trajectory_msgs/JointTrajectoryPoint output
trajectory_msgs/JointTrajectoryPoint desired
trajectory_msgs/JointTrajectoryPoint actual
string[] multi_dof_joint_names
trajectory_msgs/MultiDOFJointTrajectoryPoint multi_dof_reference
trajectory_msgs/MultiDOFJointTrajectoryPoint multi_dof_feedback
trajectory_msgs/MultiDOFJointTrajectoryPoint multi_dof_error
trajectory_msgs/MultiDOFJointTrajectoryPoint multi_dof_output
trajectory_msgs/MultiDOFJointTrajectoryPoint multi_dof_desired
trajectory_msgs/MultiDOFJointTrajectoryPoint multi_dof_actual
"""


def load_config(path: Path):
    spec = importlib.util.spec_from_file_location("pick_place_features", path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def ordered_positions(names, positions, order):
    values = dict(zip(names, positions))
    return [float(values[name]) for name in order]


def sample_and_hold(times, values, target_times, dtype=np.float32):
    times = np.asarray(times, dtype=np.int64)
    values = np.asarray(values, dtype=dtype)
    indices = np.searchsorted(times, target_times, side="right") - 1
    indices = np.clip(indices, 0, len(times) - 1)
    return values[indices]


def decode_image(message):
    if message.encoding not in {"rgb8", "bgr8"}:
        raise RuntimeError(f"Unsupported image encoding: {message.encoding}")
    row_bytes = int(message.step)
    expected_row_bytes = int(message.width) * 3
    if row_bytes < expected_row_bytes:
        raise RuntimeError(
            f"Image step {row_bytes} is smaller than RGB row {expected_row_bytes}"
        )
    raw = np.frombuffer(message.data, dtype=np.uint8)
    expected_size = int(message.height) * row_bytes
    if raw.size != expected_size:
        raise RuntimeError(
            f"Image payload has {raw.size} bytes, expected {expected_size}"
        )
    image = raw.reshape(int(message.height), row_bytes)[:, :expected_row_bytes]
    image = image.reshape(int(message.height), int(message.width), 3)
    if message.encoding == "bgr8":
        image = image[..., ::-1]
    return np.ascontiguousarray(image)


def read_messages(bag_dir: Path, require_phase: bool = False):
    topics = {
        JOINT_TOPIC: [],
        ARM_TOPIC: [],
        GRIPPER_TOPIC: [],
        CONTEXT_TOPIC: [],
        CAMERA_TOPIC: [],
    }
    if require_phase:
        topics[PHASE_TOPIC] = []
    typestore = get_typestore(Stores.ROS2_HUMBLE)
    typestore.register(
        get_types_from_msg(
            CONTROLLER_STATE_MSG,
            "control_msgs/msg/JointTrajectoryControllerState",
        )
    )
    with Reader(bag_dir) as reader:
        connections = [c for c in reader.connections if c.topic in topics]
        for connection, timestamp, rawdata in reader.messages(connections=connections):
            message = typestore.deserialize_cdr(rawdata, connection.msgtype)
            topics[connection.topic].append((timestamp, message))
    for topic, messages in topics.items():
        if not messages:
            raise RuntimeError(f"Required topic has no messages: {topic} ({bag_dir})")
    return topics


def phase_matches(value: str, selector: str) -> bool:
    return value == selector or value.startswith(selector + ":")


def episode_arrays(
    bag_dir: Path,
    fps: int,
    start_phase: str | None = None,
    end_phase: str | None = None,
):
    messages = read_messages(bag_dir, require_phase=bool(start_phase or end_phase))
    joint_times = [timestamp for timestamp, _ in messages[JOINT_TOPIC]]
    joint_values = [
        ordered_positions(message.name, message.position, JOINT_ORDER)
        for _, message in messages[JOINT_TOPIC]
    ]
    arm_times = [timestamp for timestamp, _ in messages[ARM_TOPIC]]
    arm_values = [
        ordered_positions(
            message.joint_names,
            message.reference.positions,
            JOINT_ORDER[:4],
        )
        for _, message in messages[ARM_TOPIC]
    ]
    gripper_times = [timestamp for timestamp, _ in messages[GRIPPER_TOPIC]]
    gripper_values = [
        float(message.reference.positions[0])
        for _, message in messages[GRIPPER_TOPIC]
    ]
    context_times = [timestamp for timestamp, _ in messages[CONTEXT_TOPIC]]
    context_values = [
        [float(value) for value in message.data]
        for _, message in messages[CONTEXT_TOPIC]
    ]
    camera_times = [timestamp for timestamp, _ in messages[CAMERA_TOPIC]]
    camera_values = [
        decode_image(message) for _, message in messages[CAMERA_TOPIC]
    ]

    start_time = max(
        joint_times[0],
        arm_times[0],
        gripper_times[0],
        context_times[0],
        camera_times[0],
    )
    end_time = min(
        joint_times[-1],
        arm_times[-1],
        gripper_times[-1],
        context_times[-1],
        camera_times[-1],
    )
    frame_count = max(1, int((end_time - start_time) * fps / 1e9))
    target_times = start_time + np.arange(frame_count, dtype=np.int64) * int(1e9 / fps)

    states = sample_and_hold(joint_times, joint_values, target_times)
    arm_actions = sample_and_hold(arm_times, arm_values, target_times)
    gripper_actions = sample_and_hold(
        gripper_times, gripper_values, target_times
    ).reshape(-1, 1)
    contexts = sample_and_hold(context_times, context_values, target_times)
    images = sample_and_hold(
        camera_times, camera_values, target_times, dtype=np.uint8
    )
    actions = np.hstack([arm_actions, gripper_actions])

    if start_phase or end_phase:
        phase_times = [timestamp for timestamp, _ in messages[PHASE_TOPIC]]
        phase_values = [
            json.loads(message.data)["phase"]
            for _, message in messages[PHASE_TOPIC]
        ]
        sampled_phases = sample_and_hold(
            phase_times,
            phase_values,
            target_times,
            dtype=object,
        )
        start_index = 0
        if start_phase:
            starts = [
                index
                for index, value in enumerate(sampled_phases)
                if phase_matches(str(value), start_phase)
            ]
            if not starts:
                raise RuntimeError(
                    f"Start phase {start_phase!r} was not found in {bag_dir}"
                )
            start_index = starts[0]
        end_index = len(sampled_phases)
        if end_phase:
            ends = [
                index
                for index, value in enumerate(sampled_phases[start_index:], start_index)
                if phase_matches(str(value), end_phase)
            ]
            if not ends:
                raise RuntimeError(
                    f"End phase {end_phase!r} was not found in {bag_dir}"
                )
            end_index = ends[0]
        if end_index <= start_index:
            raise RuntimeError(
                f"Invalid phase window {start_phase!r} -> {end_phase!r} in {bag_dir}"
            )
        states = states[start_index:end_index]
        actions = actions[start_index:end_index]
        contexts = contexts[start_index:end_index]
        images = images[start_index:end_index]

    return states, actions, contexts, images


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "/workspace/artifacts/rosbags/pick_place_variations/manifest.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "/workspace/artifacts/lerobot/crane_plus_parameterized_pick_place"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(
            "/workspace/configs/crane_features_pick_place_variations.py"
        ),
    )
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--start-phase")
    parser.add_argument("--end-phase")
    parser.add_argument("--task-name")
    parser.add_argument(
        "--include-environment-state",
        action="store_true",
        help="Include simulator object coordinates as a privileged observation feature",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help="Map container paths below /workspace to this host directory",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"Output exists; pass --overwrite to replace it: {args.output_dir}"
            )
        resolved = args.output_dir.resolve()
        allowed_root = (
            (args.runtime_root / "artifacts" / "lerobot").resolve()
            if args.runtime_root
            else Path("/workspace/artifacts/lerobot").resolve()
        )
        if allowed_root not in resolved.parents:
            raise RuntimeError(f"Refusing to delete outside {allowed_root}: {resolved}")
        shutil.rmtree(resolved)

    config = load_config(args.config)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    successful = [item for item in manifest["episodes"] if item.get("success")]
    if not successful:
        raise RuntimeError("Manifest contains no successful episodes")

    features = dict(config.features)
    if args.include_environment_state:
        features["observation.environment_state"] = (
            config.environment_state_feature
        )

    dataset = LeRobotDataset.create(
        repo_id=config.repo_id,
        fps=args.fps,
        root=args.output_dir,
        robot_type=config.robot_type,
        features=features,
        use_videos=False,
    )
    episode_frames = []
    for record in successful:
        bag_path_text = record["bag_path"]
        if args.runtime_root and bag_path_text.startswith("/workspace/"):
            bag_path = args.runtime_root / bag_path_text.removeprefix("/workspace/")
        else:
            bag_path = Path(bag_path_text)
        states, actions, contexts, images = episode_arrays(
            bag_path,
            args.fps,
            start_phase=args.start_phase,
            end_phase=args.end_phase,
        )
        for state, action, context, image in zip(states, actions, contexts, images):
            frame = {
                "observation.images.front": image,
                "observation.state": torch.tensor(state, dtype=torch.float32),
                "action": torch.tensor(action, dtype=torch.float32),
                "task": args.task_name or config.task_name,
            }
            if args.include_environment_state:
                frame["observation.environment_state"] = torch.tensor(
                    context, dtype=torch.float32
                )
            dataset.add_frame(frame)
        dataset.save_episode()
        episode_frames.append(len(states))
        print(f"EPISODE={record['episode_id']} FRAMES={len(states)}")

    print(f"DATASET_PATH={dataset.root}")
    print(f"EPISODES={dataset.num_episodes}")
    print(f"FRAMES={len(dataset)}")
    print(f"FPS={args.fps}")
    print(f"EPISODE_FRAMES={episode_frames}")


if __name__ == "__main__":
    main()
