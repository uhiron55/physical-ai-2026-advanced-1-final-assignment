# Third-party notices

This repository contains project code and small evaluation metadata only.
It does not redistribute Docker images, robot datasets, checkpoints, rosbag2 recordings, or generated videos.

## Bundled derivative

### AI-Robot-Book-Humble / crane_plus

`src/parameterized_pick_place/` is derived from the CRANE+ MoveIt 2 example in [AI-Robot-Book-Humble/crane_plus](https://github.com/AI-Robot-Book-Humble/crane_plus) at revision `19c1d6069126cd27488bf1bbefd410704bfc515d`.
The upstream repository includes an Apache License 2.0 `LICENSE` file, and the source package declares `Apache-2.0` in `package.xml`.
The derived package retains an `Apache-2.0` declaration and identifies the upstream project in the repository documentation.
The upstream README states that AX-12A CAD models are used with permission from ROBOTIS and that the related intellectual property remains with ROBOTIS.
This repository does not redistribute those CAD models, upstream meshes, or the AI-Robot-Book-Humble Docker image.

## Runtime dependencies not redistributed here

| Component | Use in this project | Upstream |
| --- | --- | --- |
| ROS 2 Humble | Node communication, messages, rosbag2, controllers | <https://docs.ros.org/en/humble/> |
| MoveIt 2 | Collision-aware teacher trajectory planning | <https://moveit.picknik.ai/> |
| Gazebo / ros_gz | Simulation, camera, and ROS bridge | <https://gazebosim.org/> |
| LeRobot | Dataset representation and ACT training | <https://github.com/huggingface/lerobot> |
| PyTorch | ACT training and inference | <https://pytorch.org/> |
| Jev | Authenticated high-level route selection API | <https://typesafe.ai/> |
| AI-Robot-Book-Humble container | ROS 2 desktop and CRANE+ runtime base | <https://github.com/AI-Robot-Book-Humble> |

Each dependency remains subject to its own license and service terms.
The Jev credential is supplied only at runtime through an environment variable and is not part of the repository.

## Top-level license

Repository source is released under the Apache License 2.0 in `LICENSE`.
Third-party components remain governed by their respective licenses and service terms.

