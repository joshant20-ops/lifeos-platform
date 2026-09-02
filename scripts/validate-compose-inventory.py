#!/usr/bin/env python3
"""Fail closed when LifeOS Compose desired state and its deployment manifest diverge."""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ansible/vars/compose_projects.json"
DESIRED_ROOT = ROOT / "ansible/desired/compose"


def fail(errors: list[str]) -> None:
    print("COMPOSE_INVENTORY=FAIL")
    for error in errors:
        print(f"ERROR: {error}")
    raise SystemExit(1)


def main() -> int:
    errors: list[str] = []

    try:
        data = json.loads(MANIFEST.read_text())
    except Exception as exc:
        fail([f"cannot parse {MANIFEST.relative_to(ROOT)}: {exc}"])

    projects = data.get("compose_projects")
    files = data.get("compose_files")
    if not isinstance(projects, list):
        errors.append("compose_projects must be a list")
        projects = []
    if not isinstance(files, list):
        errors.append("compose_files must be a list")
        files = []

    project_by_name: dict[str, dict] = {}
    file_by_name: dict[str, dict] = {}

    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            errors.append(f"compose_projects[{index}] is not an object")
            continue
        name = item.get("project")
        if not isinstance(name, str) or not name:
            errors.append(f"compose_projects[{index}] has invalid project name")
            continue
        if name in project_by_name:
            errors.append(f"duplicate compose_projects entry: {name}")
        project_by_name[name] = item

    for index, item in enumerate(files):
        if not isinstance(item, dict):
            errors.append(f"compose_files[{index}] is not an object")
            continue
        name = item.get("project")
        if not isinstance(name, str) or not name:
            errors.append(f"compose_files[{index}] has invalid project name")
            continue
        if name in file_by_name:
            errors.append(f"duplicate compose_files entry: {name}")
        file_by_name[name] = item

    project_names = set(project_by_name)
    file_names = set(file_by_name)
    if project_names != file_names:
        for name in sorted(project_names - file_names):
            errors.append(f"project missing compose_files entry: {name}")
        for name in sorted(file_names - project_names):
            errors.append(f"compose_files entry missing project: {name}")

    actual: dict[str, list[pathlib.Path]] = {}
    if not DESIRED_ROOT.is_dir():
        errors.append(f"missing desired Compose root: {DESIRED_ROOT.relative_to(ROOT)}")
    else:
        for directory in sorted(DESIRED_ROOT.iterdir()):
            if not directory.is_dir():
                continue
            yamls = sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml"))
            if yamls:
                actual[directory.name] = yamls

    actual_names = set(actual)
    for name in sorted(actual_names - project_names):
        errors.append(f"desired Compose project missing from manifest: {name}")
    for name in sorted(project_names - actual_names):
        errors.append(f"manifest project has no desired Compose YAML directory: {name}")

    for name, item in project_by_name.items():
        desired_files = item.get("desired_files")
        if not isinstance(desired_files, list) or not desired_files:
            errors.append(f"{name}: desired_files must be a non-empty list")
            continue
        for rel in desired_files:
            if not isinstance(rel, str) or not rel:
                errors.append(f"{name}: invalid desired_files path")
                continue
            path = ROOT / "ansible" / rel
            if not path.is_file():
                errors.append(f"{name}: desired file does not exist: ansible/{rel}")

    for name, item in file_by_name.items():
        rel = item.get("desired_rel")
        if not isinstance(rel, str) or not rel:
            errors.append(f"{name}: desired_rel is missing or invalid")
            continue
        path = ROOT / "ansible" / rel
        if not path.is_file():
            errors.append(f"{name}: desired_rel does not exist: ansible/{rel}")

        project_item = project_by_name.get(name)
        if project_item and rel not in project_item.get("desired_files", []):
            errors.append(
                f"{name}: compose_files desired_rel is not declared in compose_projects desired_files: {rel}"
            )

    if errors:
        fail(errors)

    print("COMPOSE_INVENTORY=PASS")
    print(f"PROJECTS={len(project_names)}")
    print(f"DESIRED_PROJECTS={len(actual_names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
