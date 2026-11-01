#!/usr/bin/env python3
"""Serve a trained ACT policy to a ROS 2 controller over localhost HTTP."""

import argparse
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import torch
from lerobot.policies import make_pre_post_processors
from lerobot.policies.act.modeling_act import ACTPolicy


class PolicyRuntime:
    def __init__(
        self,
        checkpoint: str,
        device: str,
        task: str,
        n_action_steps: int | None = None,
    ):
        self.device = device
        self.task = task
        self.policy = ACTPolicy.from_pretrained(
            checkpoint,
            local_files_only=True,
        ).to(device).eval()
        if n_action_steps is not None:
            if not 1 <= n_action_steps <= self.policy.config.chunk_size:
                raise ValueError(
                    "n_action_steps must be between 1 and "
                    f"{self.policy.config.chunk_size}, got {n_action_steps}"
                )
            self.policy.config.n_action_steps = n_action_steps
        self.n_action_steps = self.policy.config.n_action_steps
        self.preprocessor, self.postprocessor = make_pre_post_processors(
            policy_cfg=self.policy.config,
            pretrained_path=checkpoint,
            preprocessor_overrides={"device_processor": {"device": device}},
        )
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.policy.reset()

    def predict(self, image_bytes: bytes, state: list[float]) -> list[float]:
        if len(state) != 5:
            raise ValueError(f"Expected five joint values, got {len(state)}")
        bgr = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("JPEG decode failed")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255.0)
        observation = {
            "observation.images.front": image,
            "observation.state": torch.tensor(state, dtype=torch.float32),
            "task": self.task,
        }
        with self.lock, torch.inference_mode():
            batch = self.preprocessor(observation)
            action = self.policy.select_action(batch)
            action = self.postprocessor(action).squeeze(0).cpu()
        if not torch.isfinite(action).all():
            raise RuntimeError("Policy returned a non-finite action")
        return action.tolist()


def make_handler(runtime: PolicyRuntime):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            self.reply(
                200,
                {
                    "status": "ok",
                    "n_action_steps": runtime.n_action_steps,
                },
            )

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                if self.path == "/reset":
                    runtime.reset()
                    self.reply(200, {"status": "reset"})
                    return
                if self.path != "/predict":
                    self.send_error(404)
                    return
                started = time.perf_counter()
                image_bytes = base64.b64decode(payload["image_jpeg"])
                action = runtime.predict(image_bytes, payload["state"])
                self.reply(
                    200,
                    {
                        "action": action,
                        "latency_ms": (time.perf_counter() - started) * 1000.0,
                    },
                )
            except Exception as exc:
                self.reply(500, {"error": str(exc)})

        def reply(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--task", default="pick_wood_cube_and_place_right")
    parser.add_argument("--n-action-steps", type=int)
    args = parser.parse_args()

    runtime = PolicyRuntime(
        args.checkpoint,
        args.device,
        args.task,
        args.n_action_steps,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(runtime))
    print(
        f"ACT inference server listening on http://{args.host}:{args.port} "
        f"with n_action_steps={runtime.n_action_steps}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
