# Submission record

This file is the single place for final submission identifiers.
Do not put credentials, private URLs, or local filesystem paths here.

## Submission identifiers

| Item | Value |
| --- | --- |
| Public repository URL | `https://github.com/uhiron55/physical-ai-2026-advanced-1-final-assignment` |
| Fixed commit SHA | `1c6a64e319899976a336d046dfa7f05034a32077` |
| Demonstration video URL | `PENDING` |
| Report | `REPORT.md` |
| Machine-readable result | `results/grasp_lift_summary.json` |
| Top-level repository license | Apache-2.0 (`LICENSE`) |

## Evidence boundary

- The scripted teacher completed Gazebo pick-and-place demonstrations.
- The full-task ACT policy did not complete pick-and-place.
- In three post-hoc selected held-out initial conditions, the phase-clipped policy produced final cube Z increases of 20.02-21.24 mm.
- The six held-out episodes were excluded from every training manifest, but their conditions remain inside the widened collection range and do not establish out-of-distribution generalization.
- Each local trial used one 100-action ACT chunk without policy re-inference or temporal ensembling; low-level joint feedback remained active.
- These three observations do not establish a strict grasp-success rate or population success rate.
- Transfer, release, and return remain outside the demonstrated ACT capability.

## Preflight checklist

- [x] Choose and add the top-level `LICENSE` file.
- [x] Review `THIRD_PARTY_NOTICES.md` against the current dependency set.
- [x] Run `python3 scripts/validate_repository.py` with no findings.
- [x] Build from a clean source copy by following `docs/REPRODUCIBILITY.md`.
- [x] Run one scripted teacher episode from the clean source copy.
- [x] Identify excluded large artifacts with size and SHA-256 in `results/artifact_manifest.json`.
- [x] Confirm that no credential, rosbag2 file, dataset, checkpoint, or generated video is tracked.
- [x] Label teacher footage and learned-policy footage explicitly in the video-rendering script.
- [ ] Create the public repository and record its URL above.
- [ ] Record the submitted commit SHA above.
- [ ] Publish the demonstration video and record its URL above.
- [ ] Verify that the repository, report, and video describe the same evaluation boundary.

## Clean-clone result

| Check | Result |
| --- | --- |
| Date | `2026-11-01` |
| Source state | Local source copy on `2026-11-01`; final public commit SHA remains pending |
| Environment | Fresh source copy mounted in the pinned container digest |
| Build | Passed in a fresh digest-pinned container; 2 packages built |
| Scripted teacher smoke test | Passed with deterministic fallback; 2.81 mm placement error |
| Repository validator | Passed after build; generated build roots excluded by policy |

