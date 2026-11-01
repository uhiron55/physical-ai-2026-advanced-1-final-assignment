#!/usr/bin/env bash
set -eo pipefail

: "${TYPESAFE_API_KEY:?TYPESAFE_API_KEY must be supplied with docker --env-file}"

source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
source /workspace/install_integrated/setup.bash
set -u

episode_id="${1:-episode-$(date +%Y%m%d-%H%M%S)}"
target_index="${2:-0}"
output_root="/workspace/artifacts/rosbags/jev_generated"
bag_path="${output_root}/${episode_id}"

mkdir -p "${output_root}" /workspace/artifacts/logs
if [[ -e "${bag_path}" ]]; then
  echo "Bag path already exists: ${bag_path}" >&2
  exit 2
fi

ros2 bag record \
  -o "${bag_path}" \
  /joint_states \
  /jev_crane/action \
  /jev_crane/decision \
  /jev_crane/episode_state \
  /crane_plus_arm_controller/joint_trajectory \
  /crane_plus_gripper_controller/joint_trajectory \
  >/workspace/artifacts/logs/${episode_id}-rosbag.log 2>&1 &
bag_pid=$!

cleanup() {
  if kill -0 "${bag_pid}" 2>/dev/null; then
    kill -INT "${bag_pid}" 2>/dev/null || true
    wait "${bag_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

sleep 2
set +e
ros2 run jev_crane_data_generator generate_episode --ros-args \
  -p episode_id:="${episode_id}" \
  -p target_index:="${target_index}"
node_status=$?
set -e

cleanup
trap - EXIT

echo "EPISODE_ID=${episode_id}"
echo "BAG_PATH=${bag_path}"
echo "NODE_STATUS=${node_status}"
exit "${node_status}"
