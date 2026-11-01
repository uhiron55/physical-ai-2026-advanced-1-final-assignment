# Jev-guided CRANE+ imitation learning

This project generates image-conditioned pick-and-place demonstrations in Gazebo.
Jev selects the high-level phase, MoveIt 2 plans a collision-aware trajectory, and ROS 2 controllers execute it.
The resulting camera images, joint states, actions, phases, and Jev decisions are recorded and converted to a LeRobot dataset for ACT training.

## Project status

| Layer | Result |
| --- | --- |
| Scripted teacher | Two Jev-selected routes completed pick-and-place in Gazebo. |
| Data pipeline | rosbag2 audit, 20 Hz synchronization, and LeRobot conversion completed. |
| Full-task ACT | Closed-loop execution ran at 20.03 Hz, but pick-and-place remained incomplete. |
| Phase-clipped ACT | Three post-hoc selected held-out conditions produced local cube Z increases of 20.02-21.24 mm. |

The phase-clipped result is a local behavior observation. It is not a strict grasp-success rate or evidence that the full transfer, release, and return sequence has been learned.

## Repository guide

- [`REPORT.md`](REPORT.md): experiment narrative, measurements, limitations, and next experiments.
- [`SUBMISSION.md`](SUBMISSION.md): submission URLs and the final preflight checklist.
- [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md): tested environment and clean-clone procedure.
- [`docs/REPOSITORY_LAYOUT.md`](docs/REPOSITORY_LAYOUT.md): purpose of each directory and artifact boundary.
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md): bundled derivations and external dependencies.
- [`LICENSE`](LICENSE): Apache License 2.0 for the repository source.
- [`results/grasp_lift_summary.json`](results/grasp_lift_summary.json): portable evaluation summary.
- [`results/artifact_manifest.json`](results/artifact_manifest.json): identifiers, sizes, and hashes for excluded large artifacts.

Run the dependency-free repository preflight before publishing:

```bash
python3 scripts/validate_repository.py
```

Build the complete tested environment from the digest-pinned ROS image, pinned `uv`, and the 101-package ML lock:

```bash
docker build --target full -t pai-final-assignment:full .
docker run --rm -it --gpus all pai-final-assignment:full
```

For ROS development and deterministic teacher validation without the ML stack, build the lighter `ros-runtime` target instead.

The repository intentionally excludes credentials, rosbag2 recordings, datasets, checkpoints, generated videos, and local machine paths.

## Architecture

```text
Teacher collection runtime
Gazebo camera / joint state
  -> ROS-Gazebo bridge / joint-state broadcaster
  -> parameterized pick-and-place coordinator
  <-> Jev phase-selector ROS node <-> Jev API
  -> MoveIt 2 move_group
  -> arm / gripper controllers
  -> rosbag2 recording

Offline data and learning
rosbag2 -> audit and 20 Hz synchronization -> LeRobotDataset -> ACT checkpoint

Learned-policy runtime
camera + joint state -> ACT rollout ROS node <-> HTTP inference server
                     -> arm / gripper controllers -> Gazebo
```

The architecture is responsibility-based rather than one-node-per-joint. The
`parameterized_pick_place` executable creates separate arm and gripper ROS 2
nodes, while `controller_manager` manages the individual joints. Jev and the
Python 3.12 ACT inference server are external processes reached through narrow
interfaces; dataset conversion and ACT training are offline processes, not ROS
2 nodes. The teacher-collection runtime and learned-policy runtime are separate
execution modes.

Key topic groups are `/camera/image_raw` and `/joint_states` for observation;
`/jev_crane/phase_request`, `/jev_crane/selected_phase`, and
`/jev_crane/decision` for strategy selection; `/pick_place/task_context` and
`/pick_place/phase` for episode context; and the arm / gripper controller-state
and joint-trajectory topics for teacher recording and ACT execution. MoveIt 2
planning and execution use ROS 2 action interfaces in addition to these topics.

The repository contains the validated scripted baseline, a fixed-camera Gazebo world, the Jev phase selector, the MoveIt 2 phase executor, rosbag2 auditing, LeRobot conversion, and an ACT training command.

The validated pilot follows this route:

1. A fixed 320 x 240 RGB camera observes the entire work area.
2. Jev selects `home_transfer` or `direct_transfer` as the high-level transfer strategy.
3. MoveIt 2 plans each approach, grasp, transfer, release, and return trajectory.
4. ROS 2 controllers execute the trajectories in Gazebo.
5. rosbag2 records images, joint states, controller references, phases, and the Jev decision.
6. The converter samples the streams onto a 20 Hz grid and creates an image-conditioned LeRobotDataset.
7. ACT learns five joint targets from the camera image and five-dimensional robot state.

The first integrated fallback pilot completed the pick-and-place task with a 3.87 mm placement error. Three subsequent episodes used authenticated Jev decisions without fallback. Jev selected `home_transfer` with confidence 0.94-0.96, and all three episodes succeeded with placement errors of 2.70-7.48 mm. Their image-conditioned dataset contains 2,478 frames at 20 Hz.

A second authenticated pilot added an observable route cue. A green cue represented `direct_clear`, and an orange cue represented `home_safe`. Jev selected `direct_transfer` and `home_transfer` respectively with confidence 1.00 and no fallback. Both tasks succeeded with placement errors of 6.52 mm and 5.17 mm. The two-strategy LeRobot dataset contains 1,498 frames at 20 Hz. A 10-step ACT GPU smoke test completed on an RTX 5070 and saved a checkpoint.

The accepted balanced collection contains 20 successful episodes: 10 `direct_clear` and 10 `home_safe`. The initial batch completed 19/20; one episode timed out before task execution and was recollected under the same condition. All 20 accepted bags passed required-topic, image-format, and timestamp audits. The converted LeRobot dataset contains 15,016 frames at 20 Hz. Full-precision ACT training reached 2,000 steps on an RTX 5070 with a final loss of 1.500 and a finite gradient norm of 77.821. Offline inference produced finite actions for 20/20 sampled observations with a first-action mean absolute error of 0.0461. The 45-second Gazebo rollout ran at 20.03 Hz, but it did not complete the grasp.

A controlled follow-up compared the fixed 20-episode baseline with two 40-episode datasets. Both additions used authenticated Jev `image_text` decisions. `narrow-40` added repetitions from the original range, while `diverse-40` widened cube position and execution velocity. All added demonstrations succeeded and passed bag audits. The shared six-episode holdout combines diversity-motion pilot episodes 700-703 and authenticated Jev `image_text` pilot episodes 710-711. Its cube-y range is -0.104209 to -0.096274 m and its velocity-scale range is 0.7340 to 0.7963. The episodes are absent from every training manifest, but they are within the widened collection range rather than evidence of out-of-distribution generalization. With FP32, batch 4, seed 1000, and 2,000 optimizer steps fixed, first-frame MAE on this holdout was 0.0775 for `baseline-20`, 0.0661 for `narrow-40`, and 0.1030 for `diverse-40`. The result supports a quantity benefit under the tested budget, but not a diversity benefit. All three fixed-condition 45-second Gazebo rollouts produced finite actions and arm motion, yet none moved the cube. The offline gain has therefore not become closed-loop task success.

Resuming `diverse-40` from 2,000 to 4,000 optimizer steps reduced its training first-frame MAE from 0.0940 to 0.0675 and its shared-holdout MAE from 0.1030 to 0.0838. The matched 45-second rollout still produced no cube movement. More optimization partly addressed the wider distribution, but it did not solve the closed-loop grasp.

The first failure was then isolated as a phase-clipped `descend -> grasp -> lift` subtask. The training slice contains 40 episodes and 4,467 frames; the held-out slice contains 6 episodes and 661 frames. A 2,000-step ACT run reached loss 1.377, finite gradient norm 80.725, training first-frame MAE 0.0301 rad, holdout first-frame MAE 0.0259 rad, and 100-action chunk MAE 0.0148 rad on holdout episode 0. Temporal ensembling was disabled (`temporal_ensemble_coeff: null`). In single-chunk Gazebo evaluations without policy re-inference inside the chunk, three post-hoc selected held-out initial conditions produced cube Z increases of 20.02, 20.16, and 21.24 mm. The low-level joint controllers remained feedback controlled. This is a local behavior check, not a grasp-success rate or completion of the full transfer, release, and return sequence.

The fallback pilot validates deterministic behavior when a Jev credential is unavailable. Such an episode proves the integration and decision-recording path, but it must not be reported as an actual Jev API decision. The authenticated three-episode pilot is the evidence route for actual Jev use.

The green and orange cues are controlled visual labels, not physical obstacles. This pilot validates a cue-conditioned two-mode data path; it does not show obstacle-aware path reasoning. Closed-loop Gazebo rollout and a larger balanced dataset remain the next evaluation gates.

## Reproduction outline

Build the ROS 2 workspace, launch the camera-enabled Gazebo world, and collect balanced route-cue episodes with `scripts/generate_pick_place_variations.py`:

```bash
python3 scripts/generate_pick_place_variations.py \
  --start-id 500 \
  --episode-count 20 \
  --seed 20261106 \
  --route-profile mixed \
  --manifest-name manifest-jev-route-cue-balanced-500-519.json
```

The Jev selector supports three input modes without changing the downstream
MoveIt 2 or ACT interfaces:

- `text`: use the structured task context (the validated baseline).
- `image`: infer the route profile from the latest camera frame.
- `image_text`: evaluate the camera frame and structured context together.

The repository pins `TYPESAFE_DEFAULT_MODEL=jev-1.14.0` rather than the
mutable `jev-latest` alias. Every API response is checked against the requested
model ID, so a silent server-side remap stops collection instead of mixing
model revisions in one dataset.

Image modes preserve the 320 x 240 camera geometry and pad the frame to
320 x 320 before JPEG encoding, satisfying Jev's minimum image dimensions.
They also enable the required `TypeSafe-Danger-Zone-Images` request header.

Compare all three modes on the same two route cues before collecting a larger
dataset:

```bash
python3 scripts/probe_jev_input_modes.py \
  --repeats 5 \
  --output /workspace/artifacts/experiments/jev-input-modes/pilot-5x.json
```

The probe separates the model's raw choice from the strategy executed after
the confidence fallback. It records both correctness measures, confidence,
probabilities, fallback reason, image availability, and end-to-end response
latency for every condition. Inject `TYPESAFE_API_KEY` at runtime; the script
never writes it to the result.

In the five-repeat controlled probe, `text` and `image_text` both achieved
10/10 correct raw model choices without fallback. Image-only input achieved
6/10 correct raw choices and triggered low-confidence fallback in all 10
calls. Two subsequent `image_text` motion episodes succeeded without fallback;
Jev selected the direct and safe routes with confidence 0.94 and 0.98.
Accordingly, the larger authenticated collection uses `image_text`.

Run the same route-balanced collection with image input and wider, explicitly
recorded sampling ranges:

```bash
python3 scripts/generate_pick_place_variations.py \
  --start-id 600 \
  --episode-count 100 \
  --seed 20261031 \
  --route-profile mixed \
  --jev-input-mode image_text \
  --cube-x-min -0.003 --cube-x-max 0.003 \
  --cube-y-min -0.106 --cube-y-max -0.094 \
  --velocity-min 0.70 --velocity-max 0.85 \
  --manifest-name manifest-jev-image-diverse-100.json
```

The broader ranges are experiment parameters, not assumed-safe settings. Start
with a small pilot and retain only episodes that pass the existing motion and
bag audits. The generator records the ranges, seed, Jev input mode, and sampled
values in the manifest.

Use `--no-use-jev` only for motion-range pilots when the API credential is not
available. Those episodes record deterministic fallback decisions and must not
be reported as authenticated Jev decisions.

Create nested, route-balanced 20/40/80-episode training manifests while keeping
20 successful episodes fixed as an offline holdout:

```bash
python3 scripts/prepare_scaling_manifests.py \
  /workspace/artifacts/rosbags/pick_place_variations/manifest-jev-image-diverse-100.json \
  --output-dir /workspace/artifacts/experiments/jev-image-scaling \
  --sizes 20 40 80 \
  --holdout-count 20 \
  --seed 20261031
```

For the matched quantity-versus-diversity experiment, combine the same
20-episode baseline with either 20 narrow-condition episodes or 20
diverse-condition episodes:

```bash
python3 scripts/prepare_quantity_diversity_manifests.py \
  --baseline /workspace/artifacts/rosbags/pick_place_variations/manifest-jev-route-cue-balanced-success-20.json \
  --narrow-addition /workspace/artifacts/rosbags/pick_place_variations/manifest-image-text-narrow-720-739.json \
  --diverse-addition /workspace/artifacts/rosbags/pick_place_variations/manifest-image-text-diverse-740-759.json \
  --output-dir /workspace/artifacts/experiments/quantity-versus-diversity \
  --baseline-count 20 \
  --additional-count 20 \
  --seed 20261031
```

This emits `baseline-20.json`, `narrow-40.json`, and `diverse-40.json` with
source manifests and route counts recorded in each artifact.

After running `audit_pick_place_bag.py` for each bag, aggregate motion,
rosbag2, image, timestamp, and Jev-decision quality into one JSON artifact:

```bash
python3 scripts/summarize_pick_place_collection.py \
  --manifest /workspace/artifacts/rosbags/pick_place_variations/manifest-image-text-narrow-720-739.json \
  --audit-dir /workspace/artifacts/experiments/quantity-versus-diversity/audits-narrow \
  --output /workspace/artifacts/experiments/quantity-versus-diversity/narrow-addition-20-summary.json \
  --condition narrow-addition-20
```

Each larger training manifest contains the smaller one, so changes in ACT
performance can be attributed to added episodes rather than a different random
sample. Keep fixed Gazebo rollout conditions in addition to the offline
holdout; frame-level random splitting would leak near-duplicate observations.

Audit every accepted bag before conversion:

```bash
python3 scripts/audit_pick_place_bag.py \
  /workspace/artifacts/rosbags/pick_place_variations/pick-place-var-410 \
  --report /workspace/artifacts/rosbags/pick_place_variations/pick-place-var-410/audit.json \
  --contact-sheet /workspace/artifacts/rosbags/pick_place_variations/pick-place-var-410/contact-sheet.png
```

To isolate the contact-heavy grasp-and-lift subtask, slice each recorded episode by its phase annotations. The end phase is excluded:

```bash
python scripts/convert_pick_place_variations.py \
  --manifest /workspace/artifacts/experiments/quantity-versus-diversity/manifests/diverse-40.json \
  --output-dir /workspace/artifacts/lerobot/crane_plus_diverse_40ep_grasp_lift \
  --fps 20 \
  --start-phase descend \
  --end-phase transfer \
  --task-name descend_grasp_and_lift_cube
```

Convert the accepted manifest and run the ACT smoke test:

```bash
python3 scripts/convert_pick_place_variations.py \
  --manifest /workspace/artifacts/rosbags/pick_place_variations/manifest-jev-route-cue-balanced-success-20.json \
  --output-dir /workspace/artifacts/lerobot/crane_plus_jev_route_cue_balanced_20ep \
  --fps 20

bash scripts/train_act.sh \
  /workspace/artifacts/lerobot/crane_plus_jev_route_cue_balanced_20ep \
  /workspace/artifacts/training/act-jev-route-cue-balanced-20ep-200step \
  200
```

The validated RTX 5070 run uses full precision because mixed precision produced a non-finite gradient norm.
`USE_AMP=false` is therefore the script default; enable mixed precision only after confirming finite gradients on the target GPU:

```bash
USE_AMP=false bash scripts/train_act.sh \
  /workspace/artifacts/lerobot/crane_plus_jev_route_cue_balanced_20ep \
  /workspace/artifacts/training/act-jev-route-cue-balanced-20ep-400step-fp32 \
  2000
```

The complete tested Python environment is frozen in `requirements-ml.lock.txt`.
The preferred path is the repository `Dockerfile`; when extending an already running compatible container, create the same environment with:

```bash
bash scripts/bootstrap_ml_env.sh /home/ubuntu/.venvs/lerobot-gpu-py312
```

Reload the checkpoint and compare its first action with the ground truth from every episode:

```bash
python scripts/evaluate_act_checkpoint.py \
  /workspace/artifacts/lerobot/crane_plus_jev_route_cue_balanced_20ep \
  /workspace/artifacts/training/act-jev-route-cue-balanced-20ep-400step-fp32/checkpoints/002000/pretrained_model
```

Summarize action ranges, command path length, latency, and terminal status from a recorded rollout:

```bash
python3 scripts/summarize_act_rollout.py \
  /workspace/artifacts/experiments/quantity-versus-diversity/rollouts/narrow-40/bag \
  --output /workspace/artifacts/experiments/quantity-versus-diversity/rollouts/narrow-40/action-summary.json
```

Resume a saved training state to a larger total step count while preserving the original run:

```bash
bash scripts/resume_act.sh \
  /workspace/artifacts/training/act-diverse-40ep-2000step/checkpoints/002000 \
  /workspace/artifacts/training/act-diverse-40ep-4000step \
  4000
```

## Closed-loop ACT rollout

LeRobot 0.6.1 runs in the Python 3.12 training environment, while ROS 2 Humble uses Python 3.10.
The rollout therefore uses a localhost HTTP boundary: the Python 3.12 server performs ACT inference, and the ROS 2 node publishes bounded joint trajectories.

Start the inference server:

```bash
source "${VIRTUAL_ENV:-/home/ubuntu/.venvs/lerobot-gpu-py312}/bin/activate"
python scripts/act_inference_server.py \
  --checkpoint /workspace/artifacts/training/act-jev-route-cue-balanced-20ep-400step-fp32/checkpoints/002000/pretrained_model
```

The checkpoint predicts chunks of 100 actions. To refresh the observation more often without retraining, limit the number of queued actions at inference time. At 20 Hz, 20 actions correspond to 1.0 second:

```bash
python scripts/act_inference_server.py \
  --checkpoint /workspace/artifacts/training/act-diverse-40ep-4000step/checkpoints/004000/pretrained_model \
  --n-action-steps 20
```

In a ROS 2 shell, run a conservative 45-second rollout. The reported full-task run used `max_delta=0.08`; the published first-run example below uses `0.05` to reduce command changes during reproduction:

```bash
source /opt/ros/humble/setup.bash
source /workspace/install_integrated/setup.bash
ros2 run jev_crane_data_generator act_rollout_controller --ros-args \
  -p stop_after_s:=45.0 \
  -p max_steps:=0 \
  -p max_delta:=0.05 \
  -p command_duration:=0.10 \
  -p rate_hz:=20.0
```

Set `max_steps:=100` when an evaluation must execute exactly one ACT chunk.

For a phase-clipped `descend -> grasp -> lift` checkpoint, first recreate the
start of a held-out episode. This avoids evaluating a subtask policy
from the full task's home pose:

```bash
source "${VIRTUAL_ENV:-/home/ubuntu/.venvs/lerobot-gpu-py312}/bin/activate"
python scripts/prepare_grasp_lift_rollout.py \
  /workspace/artifacts/lerobot/crane_plus_holdout_6ep_grasp_lift \
  /workspace/artifacts/experiments/quantity-versus-diversity/manifests/holdout-6.json \
  --episode-index 0
```

The preparation script reads the clipped episode's first joint state, moves the arm to that state while the cube is temporarily placed outside the workspace, then restores the cube and route cue before evaluation. This prevents the setup trajectory from disturbing the object.

Run one complete predicted chunk with a wider per-command safety bound after the start state has been prepared:

```bash
ros2 run jev_crane_data_generator act_rollout_controller --ros-args \
  -p stop_after_s:=20.0 \
  -p max_steps:=100 \
  -p start_delay_s:=0.5 \
  -p max_delta:=0.30 \
  -p command_duration:=0.08 \
  -p rate_hz:=20.0
```

The start delay gives rosbag2 discovery time to subscribe before the first action. Holdout episode indices 0, 3, and 4 were selected after training as a diagnostic subset that covered both route labels and different cube y positions. Their observed cube Z increases were 20.02, 20.16, and 21.24 mm. The 15 mm final-Z threshold was introduced for this diagnostic to separate clear vertical displacement from small pose variation. It is not a contact, support, or strict grasp criterion. The rerun of episode 4 recorded all 100 actions, and the cube height changed by less than 0.004 mm during a two-second post-run hold. These three post-hoc selected trials are not an estimate of a population success rate. The runtime artifact is written to `artifacts/experiments/grasp-lift-subtask/summary.json`; the portable result subset is included in `results/grasp_lift_summary.json`, and large-artifact identities are recorded in `results/artifact_manifest.json`.

The controller rejects non-finite actions, clamps every joint to the CRANE+ limits, limits each command delta, and stops after three consecutive inference errors.

Render a 1-3 minute evidence video from two successful Jev demonstrations and one ACT rollout:

```bash
python3 scripts/render_submission_video.py \
  --direct-bag /workspace/artifacts/rosbags/pick_place_variations/pick-place-var-518 \
  --safe-bag /workspace/artifacts/rosbags/pick_place_variations/pick-place-var-520 \
  --act-bag /workspace/artifacts/rollouts/act-home-safe-2000step-fp32-full-001 \
  --output /workspace/artifacts/submission/pai-final-assignment.mp4
```

The rendered video labels accelerated segments, marks the first two sections as teacher demonstrations and the final evaluation as an ACT rollout, and keeps the incomplete ACT rollout visible as evaluation evidence.

## Security and generated data

Copy `.env.example` to an environment file outside the repository and provide `TYPESAFE_API_KEY` at runtime.
Keep `TYPESAFE_DEFAULT_MODEL=jev-1.14.0` unless a new model is evaluated as a separate dataset version.
Do not commit credentials, rosbag2 files, datasets, checkpoints, videos, or local absolute paths.

## Provenance

The parameterized pick-and-place node is derived from revision `19c1d6069126cd27488bf1bbefd410704bfc515d` of the Apache-2.0 licensed [AI-Robot-Book-Humble/crane_plus](https://github.com/AI-Robot-Book-Humble/crane_plus) example. The upstream README states that the AX-12A CAD models are used with permission from ROBOTIS and that related intellectual-property rights remain with ROBOTIS. This repository does not redistribute the upstream CAD, meshes, or Docker image.
The validated training environment uses Python 3.12.16, LeRobot 0.6.1, PyTorch 2.11.0+cu128, and an NVIDIA RTX 5070.
