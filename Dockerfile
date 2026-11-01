FROM airobotbook/ros2-desktop-ai-robot-book-humble@sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63 AS ros-runtime

USER root
WORKDIR /workspace
COPY --chown=ubuntu:ubuntu . /workspace
RUN chown ubuntu:ubuntu /workspace

USER ubuntu
RUN /bin/bash -lc '\
    source /opt/ros/humble/setup.bash && \
    source /home/ubuntu/airobot_ws/install/setup.bash && \
    colcon build \
      --symlink-install \
      --base-paths src \
      --install-base install_integrated && \
    PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_repository.py'

ENTRYPOINT ["/bin/bash"]


FROM ros-runtime AS full

ARG UV_VERSION=0.13.6
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_CACHE_DIR=/tmp/uv-cache \
    VIRTUAL_ENV=/opt/venvs/lerobot-gpu-py312 \
    PATH=/opt/venvs/lerobot-gpu-py312/bin:${PATH}

USER root
RUN python3 -m pip install --no-cache-dir "uv==${UV_VERSION}" && \
    uv python install 3.12.16 && \
    uv venv --python 3.12.16 "${VIRTUAL_ENV}" && \
    uv pip sync \
      --python "${VIRTUAL_ENV}/bin/python" \
      --torch-backend cu128 \
      /workspace/requirements-ml.lock.txt && \
    "${VIRTUAL_ENV}/bin/python" -c \
      'import torch, lerobot, rosbags, pyarrow, cv2; print(torch.__version__, lerobot.__version__)' && \
    rm -rf "${UV_CACHE_DIR}"

USER ubuntu
WORKDIR /workspace
ENTRYPOINT ["/bin/bash"]
