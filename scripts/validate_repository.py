#!/usr/bin/env python3
"""Run dependency-free preflight checks for the public submission tree."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = (
    ".dockerignore",
    "LICENSE",
    "README.md",
    "REPORT.md",
    "SUBMISSION.md",
    "THIRD_PARTY_NOTICES.md",
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "requirements-ml.lock.txt",
    "docs/REPOSITORY_LAYOUT.md",
    "docs/REPRODUCIBILITY.md",
    "results/artifact_manifest.json",
    "results/grasp_lift_summary.json",
    "scripts/bootstrap_ml_env.sh",
    "src/jev_crane_data_generator/package.xml",
    "src/parameterized_pick_place/package.xml",
    "tests/test_validate_repository.py",
)

GENERATED_ROOT_PATTERNS = (
    re.compile(r"^build(?:_|$)"),
    re.compile(r"^install(?:_|$)"),
    re.compile(r"^log(?:_|$)"),
)

FORBIDDEN_DIRS = {
    "artifacts",
    "checkpoints",
    "datasets",
    "mlruns",
    "outputs",
    "wandb",
}

FORBIDDEN_SUFFIXES = {
    ".db3",
    ".mcap",
    ".mp4",
    ".parquet",
    ".pem",
    ".pt",
    ".safetensors",
}

PRIVATE_KEY_SUFFIXES = {".key", ".p12", ".pfx"}
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".cmake",
    ".example",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
NAMED_SECRET_PATTERN = re.compile(
    r"(?P<name>api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|secret)"
    r"\s*[:=]\s*(?P<value>[^\s#,\)]+)",
    re.I,
)

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SCRIPT_REFERENCE = re.compile(r"(?:python3?|bash)\s+(scripts/[A-Za-z0-9_.-]+)")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REQUIREMENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+==[^\s]+$")
PINNED_BASE_PATTERN = re.compile(
    r"^FROM\s+airobotbook/ros2-desktop-ai-robot-book-humble@sha256:[0-9a-f]{64}\s+AS\s+ros-runtime$",
    re.M,
)
PINNED_JEV_MODEL = "jev-1.14.0"


def is_generated_root(path: Path, root: Path) -> bool:
    try:
        first_part = path.relative_to(root).parts[0]
    except (ValueError, IndexError):
        return False
    return any(pattern.search(first_part) for pattern in GENERATED_ROOT_PATTERNS)


def iter_files(root: Path = ROOT) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and ".git" not in path.relative_to(root).parts
        and not is_generated_root(path, root)
    ]


def check_required(root: Path, findings: list[str]) -> None:
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            findings.append(f"missing required file: {relative}")


def check_artifacts(root: Path, files: list[Path], findings: list[str]) -> None:
    for path in files:
        relative = path.relative_to(root)
        lower_parts = {part.lower() for part in relative.parts}
        if "__pycache__" in lower_parts or path.suffix.lower() == ".pyc":
            findings.append(f"generated cache is present: {relative}")
        if lower_parts & FORBIDDEN_DIRS:
            findings.append(f"forbidden artifact directory: {relative}")
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append(f"populated environment file is present: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES | PRIVATE_KEY_SUFFIXES:
            findings.append(f"forbidden generated or credential artifact: {relative}")


def read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES and not path.name.startswith("."):
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def check_secrets(root: Path, files: list[Path], findings: list[str]) -> None:
    validator = Path(__file__).resolve()
    for path in files:
        if path.resolve() == validator:
            continue
        text = read_text(path)
        if text is None:
            continue
        if path.name == ".env.example":
            for line in text.splitlines():
                if line.startswith("TYPESAFE_API_KEY=") and line != "TYPESAFE_API_KEY=":
                    findings.append(".env.example contains a populated TYPESAFE_API_KEY")
            continue
        if PRIVATE_KEY_PATTERN.search(text):
            findings.append(f"possible credential in {path.relative_to(root)}")
            continue
        for match in NAMED_SECRET_PATTERN.finditer(text):
            name = match.group("name").lower()
            value = match.group("value").strip("'\"")
            if name in value.lower() or value.startswith(("$", "{", "os.", "self.", "args.")):
                continue
            if value in {"", "None", "null", "REPLACE_ME"}:
                continue
            if len(value) >= 8:
                findings.append(f"possible credential in {path.relative_to(root)}")
                break


def check_python(root: Path, files: list[Path], findings: list[str]) -> None:
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as error:
            findings.append(f"Python compile failed for {path.relative_to(root)}: {error}")


def check_markdown_links(root: Path, files: list[Path], findings: list[str]) -> None:
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = unquote(target.split("#", 1)[0])
            if target and not (path.parent / target).resolve().exists():
                findings.append(f"broken local link in {path.relative_to(root)}: {raw_target}")
        for script in SCRIPT_REFERENCE.findall(text):
            if not (root / script).is_file():
                findings.append(f"missing referenced script in {path.relative_to(root)}: {script}")


def check_structured_files(root: Path, findings: list[str]) -> None:
    try:
        env_example = (root / ".env.example").read_text(encoding="utf-8")
        expected = f"TYPESAFE_DEFAULT_MODEL={PINNED_JEV_MODEL}"
        if expected not in env_example.splitlines():
            findings.append(f".env.example does not pin the tested Jev model: {expected}")
    except OSError as error:
        findings.append(f".env.example cannot be read: {error}")

    try:
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        if not PINNED_BASE_PATTERN.search(dockerfile):
            findings.append("Dockerfile does not use the digest-pinned ROS base image")
        if "ARG UV_VERSION=0.13.6" not in dockerfile:
            findings.append("Dockerfile does not pin the tested uv version")
        if "uv python install 3.12.16" not in dockerfile:
            findings.append("Dockerfile does not pin the tested Python version")
        if "--torch-backend cu128" not in dockerfile:
            findings.append("Dockerfile does not pin the tested PyTorch backend")
        if "/workspace/requirements-ml.lock.txt" not in dockerfile:
            findings.append("Dockerfile does not install the frozen ML environment")
    except OSError as error:
        findings.append(f"Dockerfile cannot be read: {error}")

    try:
        dockerignore = (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        for required_pattern in (
            ".env",
            "artifacts/",
            "datasets/",
            "*.key",
            "*.p12",
            "*.pfx",
            "*.pt",
            "*.safetensors",
        ):
            if required_pattern not in dockerignore:
                findings.append(f".dockerignore is missing a sensitive artifact pattern: {required_pattern}")
    except OSError as error:
        findings.append(f".dockerignore cannot be read: {error}")

    try:
        requirement_lines = [
            line.strip()
            for line in (root / "requirements-ml.lock.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(requirement_lines) != 101:
            findings.append(f"ML lock must contain exactly 101 pinned packages, found {len(requirement_lines)}")
        names: set[str] = set()
        pins: dict[str, str] = {}
        for line in requirement_lines:
            if not REQUIREMENT_PATTERN.fullmatch(line):
                findings.append(f"ML lock contains an unpinned or malformed requirement: {line}")
                continue
            name, version = line.split("==", 1)
            normalized_name = name.lower().replace("_", "-")
            if normalized_name in names:
                findings.append(f"ML lock contains a duplicate package: {normalized_name}")
            names.add(normalized_name)
            pins[normalized_name] = version
        for package, version in {
            "lerobot": "0.6.1",
            "torch": "2.11.0+cu128",
            "torchvision": "0.26.0+cu128",
            "numpy": "2.2.6",
            "pyarrow": "26.0.0",
        }.items():
            if pins.get(package) != version:
                findings.append(f"ML lock does not contain the tested pin: {package}=={version}")
    except OSError as error:
        findings.append(f"ML lock cannot be read: {error}")

    try:
        result = json.loads((root / "results/grasp_lift_summary.json").read_text(encoding="utf-8"))
        evaluation = result["evaluation"]
        holdout = result["holdout_dataset"]
        training = result["training"]
        if evaluation["strict_grasp_success_criterion"]:
            findings.append("portable result incorrectly claims a strict grasp criterion")
        if evaluation["population_success_rate_estimate"]:
            findings.append("portable result incorrectly claims a population success rate")
        if evaluation["policy_reinference_inside_chunk"]:
            findings.append("portable result incorrectly claims policy re-inference inside the diagnostic chunk")
        if not evaluation["low_level_joint_feedback_continues"]:
            findings.append("portable result must preserve the low-level feedback-control boundary")
        if not evaluation["start_state_preparation"].strip():
            findings.append("portable result does not describe diagnostic start-state preparation")
        if holdout["episode_ids"] != [700, 701, 702, 703, 710, 711]:
            findings.append("portable result does not identify the fixed six-episode holdout")
        if not holdout["excluded_from_all_training_manifests"]:
            findings.append("portable result does not confirm holdout exclusion from training manifests")
        if holdout["out_of_distribution_claim"]:
            findings.append("portable result incorrectly claims out-of-distribution generalization")
        if training["temporal_ensemble_coeff"] is not None:
            findings.append("portable result must record temporal ensembling as disabled")
        if result["selection_protocol"]["preregistered"]:
            findings.append("portable result incorrectly labels the diagnostic subset as preregistered")
    except (KeyError, json.JSONDecodeError, OSError) as error:
        findings.append(f"invalid portable result: {error}")

    try:
        manifest = json.loads((root / "results/artifact_manifest.json").read_text(encoding="utf-8"))
        if manifest.get("availability") != "local_only":
            findings.append("artifact manifest availability must match the current local-only boundary")
        artifacts = manifest.get("artifacts")
        if not artifacts:
            findings.append("artifact manifest contains no artifacts")
        else:
            roles: set[str] = set()
            for artifact in artifacts:
                role = artifact.get("role")
                if not isinstance(role, str) or not role.strip():
                    findings.append("artifact manifest contains an artifact without a role")
                elif role in roles:
                    findings.append(f"artifact manifest contains a duplicate role: {role}")
                else:
                    roles.add(role)
                size = artifact.get("size_bytes")
                if not isinstance(size, int) or size <= 0:
                    findings.append(f"artifact manifest has an invalid size: {role or '<missing>'}")
                hash_count = 0
                for container in (artifact, artifact.get("metadata", {}), artifact.get("sidecars", {})):
                    if not isinstance(container, dict):
                        findings.append(f"artifact manifest has invalid metadata: {role or '<missing>'}")
                        continue
                    for key, value in container.items():
                        if key == "sha256" or key.endswith("_sha256"):
                            hash_count += 1
                            if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
                                findings.append(f"artifact manifest has an invalid SHA-256: {role or '<missing>'}.{key}")
                if hash_count == 0:
                    findings.append(f"artifact manifest has no hash: {role or '<missing>'}")
    except (json.JSONDecodeError, OSError) as error:
        findings.append(f"invalid artifact manifest: {error}")

    try:
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        if "Apache License" not in license_text or "Version 2.0, January 2004" not in license_text:
            findings.append("top-level LICENSE is not the Apache License 2.0 text")
    except OSError as error:
        findings.append(f"top-level LICENSE cannot be read: {error}")

    for relative in (
        "src/jev_crane_data_generator/package.xml",
        "src/parameterized_pick_place/package.xml",
    ):
        try:
            package_root = ET.parse(root / relative).getroot()
            license_node = package_root.find("license")
            if license_node is None or (license_node.text or "").strip() != "Apache-2.0":
                findings.append(f"package license is not Apache-2.0: {relative}")
            maintainer = package_root.find("maintainer")
            if maintainer is None or ".invalid" in maintainer.attrib.get("email", ""):
                findings.append(f"package maintainer is not publishable: {relative}")
        except (ET.ParseError, OSError) as error:
            findings.append(f"invalid package manifest {relative}: {error}")


def check_release(root: Path, findings: list[str]) -> None:
    submission = (root / "SUBMISSION.md").read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for label in ("Public repository URL", "Fixed commit SHA", "Demonstration video URL"):
        match = re.search(rf"^\| {re.escape(label)} \| `([^`]+)` \|$", submission, re.M)
        if not match:
            findings.append(f"release identifier is missing from SUBMISSION.md: {label}")
        else:
            values[label] = match.group(1)
    repository_url = values.get("Public repository URL", "")
    if not re.fullmatch(r"https://github\.com/[^/\s]+/[^/\s]+/?", repository_url):
        findings.append("public repository URL is not a valid HTTPS GitHub repository URL")
    if not COMMIT_PATTERN.fullmatch(values.get("Fixed commit SHA", "")):
        findings.append("fixed commit SHA is not 40 lowercase hexadecimal characters")
    if not re.fullmatch(r"https://[^\s]+", values.get("Demonstration video URL", "")):
        findings.append("demonstration video URL is not a valid HTTPS URL")


def validate(root: Path = ROOT, release: bool = False) -> list[str]:
    findings: list[str] = []
    files = iter_files(root)
    check_required(root, findings)
    check_artifacts(root, files, findings)
    check_secrets(root, files, findings)
    check_python(root, files, findings)
    check_markdown_links(root, files, findings)
    check_structured_files(root, findings)
    if release:
        check_release(root, findings)
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true", help="also require final submission identifiers")
    args = parser.parse_args()

    files = iter_files(ROOT)
    findings = validate(ROOT, release=args.release)
    if findings:
        print("Repository validation failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    mode = "release" if args.release else "preflight"
    print(f"Repository {mode} validation passed: {len(files)} source files checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
