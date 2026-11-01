from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


VALIDATOR_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("validate_repository", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def make_minimum_tree(root: Path) -> None:
    for relative in VALIDATOR.REQUIRED_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith("package.xml"):
            path.write_text(
                '<package format="3"><name>x</name><version>0.1.0</version>'
                '<description>x</description><maintainer email="u@users.noreply.github.com">u</maintainer>'
                '<license>Apache-2.0</license></package>',
                encoding="utf-8",
            )
        elif relative == "results/grasp_lift_summary.json":
            path.write_text(
                json.dumps(
                    {
                        "evaluation": {
                            "strict_grasp_success_criterion": False,
                            "population_success_rate_estimate": False,
                            "policy_reinference_inside_chunk": False,
                            "low_level_joint_feedback_continues": True,
                            "start_state_preparation": "fixture preparation",
                        },
                        "holdout_dataset": {
                            "episode_ids": [700, 701, 702, 703, 710, 711],
                            "excluded_from_all_training_manifests": True,
                            "out_of_distribution_claim": False,
                        },
                        "training": {"temporal_ensemble_coeff": None},
                        "selection_protocol": {"preregistered": False},
                    }
                ),
                encoding="utf-8",
            )
        elif relative == "results/artifact_manifest.json":
            path.write_text(
                json.dumps(
                    {
                        "availability": "local_only",
                        "artifacts": [{"role": "x", "size_bytes": 1, "sha256": "a" * 64}],
                    }
                ),
                encoding="utf-8",
            )
        elif relative == "LICENSE":
            path.write_text("Apache License\nVersion 2.0, January 2004\n", encoding="utf-8")
        elif relative == ".env.example":
            path.write_text("TYPESAFE_API_KEY=\n", encoding="utf-8")
        elif relative == ".dockerignore":
            path.write_text(
                ".env\nartifacts/\ndatasets/\n*.key\n*.p12\n*.pfx\n*.pt\n*.safetensors\n",
                encoding="utf-8",
            )
        elif relative == "Dockerfile":
            path.write_text(
                "FROM airobotbook/ros2-desktop-ai-robot-book-humble@sha256:"
                + "a" * 64
                + " AS ros-runtime\n"
                "ARG UV_VERSION=0.13.6\n"
                "RUN uv python install 3.12.16 && uv pip sync --torch-backend cu128 "
                "/workspace/requirements-ml.lock.txt\n",
                encoding="utf-8",
            )
        elif relative == "requirements-ml.lock.txt":
            required = [
                "lerobot==0.6.1",
                "torch==2.11.0+cu128",
                "torchvision==0.26.0+cu128",
                "numpy==2.2.6",
                "pyarrow==26.0.0",
            ]
            filler = [f"fixture-package-{index:03d}==1.0.0" for index in range(96)]
            path.write_text("\n".join(required + filler) + "\n", encoding="utf-8")
        else:
            path.write_text("placeholder\n", encoding="utf-8")


class RepositoryValidatorTests(unittest.TestCase):
    def run_fixture(self, relative: str, content: bytes | str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_minimum_tree(root)
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
            return VALIDATOR.validate(root)

    def test_minimum_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_minimum_tree(root)
            self.assertEqual([], VALIDATOR.validate(root))

    def test_populated_dotenv_is_rejected(self) -> None:
        key_name = "TYPESAFE_" + "API_KEY"
        findings = self.run_fixture(".env", f"{key_name}=not-a-real-value\n")
        self.assertTrue(any("environment file" in finding for finding in findings))

    def test_private_key_is_rejected(self) -> None:
        marker = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-key\n"
        findings = self.run_fixture("private.pem", marker)
        self.assertTrue(any("credential artifact" in finding for finding in findings))

    def test_generic_text_secret_is_rejected(self) -> None:
        label = "access_" + "token"
        findings = self.run_fixture("notes.txt", f"{label}=not-a-real-token\n")
        self.assertTrue(any("possible credential" in finding for finding in findings))

    def test_dataset_parquet_is_rejected(self) -> None:
        findings = self.run_fixture("datasets/sample.parquet", b"PAR1")
        self.assertTrue(any("artifact directory" in finding for finding in findings))

    def test_generated_build_root_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_minimum_tree(root)
            generated = root / "build_jev" / "cache.pyc"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(b"generated")
            self.assertEqual([], VALIDATOR.validate(root))

    def test_git_metadata_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_minimum_tree(root)
            metadata = root / ".git" / "objects" / "secret-like-file.txt"
            metadata.parent.mkdir(parents=True)
            label = "access_" + "token"
            metadata.write_text(f"{label}=git-internal-fixture\n", encoding="utf-8")
            self.assertNotIn(metadata, VALIDATOR.iter_files(root))
            self.assertEqual([], VALIDATOR.validate(root))

    def test_invalid_artifact_hash_and_size_are_rejected(self) -> None:
        manifest = json.dumps(
            {
                "availability": "local_only",
                "artifacts": [{"role": "x", "size_bytes": -1, "sha256": "not-a-sha256"}],
            }
        )
        findings = self.run_fixture("results/artifact_manifest.json", manifest)
        self.assertTrue(any("invalid size" in finding for finding in findings))
        self.assertTrue(any("invalid SHA-256" in finding for finding in findings))

    def test_placeholder_license_is_rejected(self) -> None:
        findings = self.run_fixture("LICENSE", "placeholder\n")
        self.assertTrue(any("Apache License 2.0 text" in finding for finding in findings))

    def test_overstated_holdout_boundary_is_rejected(self) -> None:
        result = json.dumps(
            {
                "evaluation": {
                    "strict_grasp_success_criterion": False,
                    "population_success_rate_estimate": False,
                    "policy_reinference_inside_chunk": True,
                    "low_level_joint_feedback_continues": True,
                    "start_state_preparation": "fixture preparation",
                },
                "holdout_dataset": {
                    "episode_ids": [700, 701, 702, 703, 710, 711],
                    "excluded_from_all_training_manifests": True,
                    "out_of_distribution_claim": True,
                },
                "training": {"temporal_ensemble_coeff": None},
                "selection_protocol": {"preregistered": False},
            }
        )
        findings = self.run_fixture("results/grasp_lift_summary.json", result)
        self.assertTrue(any("re-inference" in finding for finding in findings))
        self.assertTrue(any("out-of-distribution" in finding for finding in findings))

    def test_mutable_container_base_is_rejected(self) -> None:
        findings = self.run_fixture(
            "Dockerfile",
            "FROM airobotbook/ros2-desktop-ai-robot-book-humble:latest AS ros-runtime\n",
        )
        self.assertTrue(any("digest-pinned ROS base image" in finding for finding in findings))

    def test_incomplete_ml_lock_is_rejected(self) -> None:
        findings = self.run_fixture("requirements-ml.lock.txt", "torch==2.11.0+cu128\n")
        self.assertTrue(any("exactly 101 pinned packages" in finding for finding in findings))
        self.assertTrue(any("tested pin: lerobot==0.6.1" in finding for finding in findings))

    def test_release_identifiers_are_format_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_minimum_tree(root)
            (root / "SUBMISSION.md").write_text(
                "| Item | Value |\n| --- | --- |\n"
                "| Public repository URL | `x` |\n"
                "| Fixed commit SHA | `x` |\n"
                "| Demonstration video URL | `x` |\n",
                encoding="utf-8",
            )
            findings = VALIDATOR.validate(root, release=True)
            self.assertTrue(any("GitHub repository URL" in finding for finding in findings))
            self.assertTrue(any("40 lowercase hexadecimal" in finding for finding in findings))
            self.assertTrue(any("video URL" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
