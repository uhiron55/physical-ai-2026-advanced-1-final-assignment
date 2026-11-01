# Repository layout

- `Dockerfile`: digest-pinned ROS build plus the default full `uv`-managed ML runtime.
- `.dockerignore`: credentials and large/generated experiment artifacts excluded from the build context.

```text
.
|-- README.md                  Project entrypoint and measured status
|-- REPORT.md                  Detailed experiment report
|-- SUBMISSION.md              Submission identifiers and preflight checklist
|-- THIRD_PARTY_NOTICES.md     Attribution and dependency boundary
|-- LICENSE                    Apache License 2.0 for repository source
|-- .env.example               Empty Jev environment-variable template
|-- requirements-ml.lock.txt   Complete tested Python environment freeze
|-- configs/                   LeRobot dataset feature definitions
|-- docs/                      Reproduction and repository guidance
|-- results/                   Small portable evaluation summaries
|-- scripts/                   Collection, audit, conversion, training, and evaluation CLIs
|-- tests/                     Negative fixtures for repository validation
`-- src/                       ROS 2 packages and Gazebo world
```

## Source ownership

- `src/jev_crane_data_generator/` contains the project-specific ROS 2 data-generation and ACT rollout nodes.
- `src/parameterized_pick_place/` contains the parameterized teacher executor derived from the AI-Robot-Book-Humble CRANE+ example.
- `scripts/` contains orchestration and data-processing commands that operate on artifacts outside Git.
- `results/` contains compact JSON evidence and a hash manifest for large local artifacts that are not committed.

## Artifact boundary

The following items are generated or sensitive and must remain outside Git:

- Jev credentials and populated `.env` files
- rosbag2 databases and MCAP files
- camera-frame collections and LeRobot datasets
- ACT checkpoints and model weights
- generated videos
- local Docker volumes and absolute host paths

The `.gitignore` enforces common filename patterns, while `scripts/validate_repository.py` performs a second content-level preflight.

## Naming convention

- Scripts use verbs that describe their operation, such as `convert_`, `prepare_`, `evaluate_`, and `summarize_`.
- Portable result files describe the evaluated scope, such as `grasp_lift_summary.json`.
- Large run-specific artifacts retain their experiment IDs outside the repository rather than being copied into `results/`.

