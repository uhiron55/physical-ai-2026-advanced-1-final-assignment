#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_path="${1:-/home/ubuntu/.venvs/lerobot-gpu-py312}"

uv_bin="${UV_BIN:-$(command -v uv || true)}"
if [[ -z "${uv_bin}" ]]; then
  python3 -m pip install --user "uv==0.13.6"
  uv_bin="$(python3 -m site --user-base)/bin/uv"
fi
test -x "${uv_bin}" || {
  echo "uv executable was not found after installation: ${uv_bin}" >&2
  exit 2
}

"${uv_bin}" python install 3.12.16
"${uv_bin}" venv --python 3.12.16 "${venv_path}"
"${uv_bin}" pip sync \
  --python "${venv_path}/bin/python" \
  --torch-backend cu128 \
  "${repo_root}/requirements-ml.lock.txt"

"${venv_path}/bin/python" - <<'PY'
import importlib.metadata as metadata

for package in ("torch", "lerobot", "rosbags", "pyarrow", "opencv-python-headless"):
    print(f"{package}=={metadata.version(package)}")
PY

echo "ML_ENV=${venv_path}"
