# Reproducibility

## Tested environment

| Component | Tested value |
| --- | --- |
| Container image | `airobotbook/ros2-desktop-ai-robot-book-humble` |
| Container digest | `sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63` |
| Base OS | Ubuntu 22.04 |
| ROS distribution | Humble |
| ROS base package | `0.10.0-1jammy.20250114.175320` |
| MoveIt package | `2.5.7-1jammy.20250114.205048` |
| ros_gz_sim package | `0.244.16-2jammy.20241205.203411` |
| GPU | NVIDIA GeForce RTX 5070, 12,227 MiB |
| NVIDIA driver | 610.88 |
| ML Python | 3.12.16 |
| PyTorch | `2.11.0+cu128` |
| LeRobot | `0.6.1` |
| NumPy | `2.2.6` |
| Pillow | `12.3.0` |

The image tag is mutable, so both the `Dockerfile` and manual fallback use the digest shown above.
GPU driver compatibility and the LeRobot environment remain host-dependent.

## Clean-clone procedure

1. Clone the repository and enter its root.
2. Copy `.env.example` to a local `.env` only when authenticated Jev evaluation is needed.
3. Keep the populated `.env` outside Git and inject it at container startup.
4. Build the `Dockerfile` target appropriate for the reproduction level.
5. Run the container with GPU access only when ACT training or inference is needed.
6. Run the repository validator.
7. Start with a deterministic teacher smoke test before using the Jev API or training ACT.

Preferred complete build:

```bash
docker build --target full -t pai-final-assignment:full .
docker run --rm -it \
  --gpus all \
  --name pai-final-assignment \
  pai-final-assignment:full
```

The `full` target layers Python 3.12.16, pinned `uv 0.13.6`, and the complete `requirements-ml.lock.txt` environment over the digest-pinned ROS target. The lighter `ros-runtime` target builds the two repository ROS 2 packages and runs the source validator without downloading the ML packages:

```bash
docker build --target ros-runtime -t pai-final-assignment:ros .
docker run --rm -it --name pai-final-assignment-ros pai-final-assignment:ros
```

`.dockerignore` excludes credentials, datasets, rosbag2 files, checkpoints, videos, and generated workspaces from the build context.

## Existing-container fallback

When inspecting source changes through a bind mount rather than rebuilding the image, start the pinned base image from the repository root:

```bash
docker run --rm -it \
  --gpus all \
  --name pai-final-assignment \
  --entrypoint /bin/bash \
  --mount type=bind,source="$(pwd)",target=/workspace \
  airobotbook/ros2-desktop-ai-robot-book-humble@sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63
```

For PowerShell, replace `$(pwd)` with `${PWD}`.
The explicit entrypoint override is required because the image normally starts its VNC desktop entrypoint instead of executing a trailing shell command.

Example build inside the container:

```bash
cd /workspace
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
ros2 pkg prefix crane_plus_description
ros2 pkg prefix crane_plus_moveit_config
colcon build \
  --symlink-install \
  --base-paths src \
  --install-base install_integrated
source /workspace/install_integrated/setup.bash
python3 scripts/validate_repository.py
```

The image supplies the CRANE+ packages under `/home/ubuntu/airobot_ws`.
Sourcing that workspace is required before parsing either launch file.

The `full` image already contains the tested LeRobot environment at `/opt/venvs/lerobot-gpu-py312`.
For the manual bind-mount fallback, create it with the included full freeze:

```bash
bash scripts/bootstrap_ml_env.sh /home/ubuntu/.venvs/lerobot-gpu-py312
source /home/ubuntu/.venvs/lerobot-gpu-py312/bin/activate
```

`requirements-ml.lock.txt` records the complete tested environment.
The bootstrap installs pinned `uv 0.13.6` when needed, uses its `cu128` PyTorch backend, and performs an import/version smoke test.
Creating the environment requires network access to Python and package indexes.

## Reproduction levels

### Level 1: repository validation

```bash
python3 scripts/validate_repository.py
```

This checks the source tree, compiles Python files without generating bytecode, parses package manifests and JSON results, validates local Markdown links, and rejects common generated or secret-bearing files.

Run the validator before the build and again afterward.
Generated `build*`, `install*`, and `log*` roots are intentionally excluded from source-content inspection.

### Level 2: scripted teacher smoke test

Start the headless world in one terminal:

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
source /workspace/install_integrated/setup.bash
ros2 launch jev_crane_data_generator crane_plus_headless.launch.py
```

Before collection, verify that the camera and controllers are ready:

```bash
ros2 topic list | grep '^/camera/image_raw$'
ros2 control list_controllers
```

Then run one deterministic teacher episode in another sourced terminal:

```bash
cd /workspace
python3 scripts/generate_pick_place_variations.py \
  --start-id 9900 \
  --episode-count 1 \
  --seed 20261101 \
  --route-profile direct_clear \
  --no-use-jev \
  --manifest-name cleanclone-smoke-9900.json
```

This procedure was repeated in a fresh container created from the pinned digest on 2026-11-01.
Both packages built, the world reached the camera/controller-ready state, and the teacher episode completed with a 2.81 mm placement error.
Such a run is an integration test and must not be reported as authenticated Jev evidence.

### Level 3: authenticated Jev collection

Inject `TYPESAFE_API_KEY` at runtime and collect a small pilot before scaling the dataset.
The tested model is pinned as `TYPESAFE_DEFAULT_MODEL=jev-1.14.0`.
The client rejects a response whose resolved model differs from the requested ID, preventing a mutable alias from silently changing the dataset generator.
Keep both the model's raw choice and the fallback-adjusted executed strategy in the result.

### Level 4: ACT training and closed-loop evaluation

Use the commands in `README.md` to convert the audited bags, train ACT, reload the checkpoint, and execute Gazebo closed-loop evaluation.
The original large artifacts are excluded from Git.
`results/artifact_manifest.json` records the logical paths, sizes, and SHA-256 values of the dataset manifests, dataset metadata, checkpoint, and selected evaluation bag.
Their publication status is currently `local_only`; only the portable summaries can be reviewed without access to those artifacts.

## Known reproducibility gap

The digest-pinned `ros-runtime` target built both ROS 2 packages and passed the repository validator in a clean Docker build on 2026-11-01.
The `full` target then installed Python 3.12.16 and all 101 locked packages from the network with pinned `uv 0.13.6`; a runtime `uv pip sync --check` required no changes, and the import/version smoke test reported PyTorch `2.11.0+cu128` and LeRobot `0.6.1`.
The deterministic teacher smoke test also completed in a fresh digest-pinned container with a 2.81 mm placement error.
Recomputation of the reported ACT metrics from shared large artifacts remains unverified.
Public artifact locations, repository URL, fixed commit, and video URL must be finalized before submission.

