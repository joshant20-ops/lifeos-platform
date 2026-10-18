#!/usr/bin/env python3
"""Fail-closed scope classifier for the Pi's long-range Energy preflight."""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = "homeassistant/build-house-status-release.py"
GOVERNANCE_TEST = "homeassistant/test-house-status-release-governance.py"
ENERGY_INPUTS = {
    "homeassistant/www/house-status-dev/lifeos-house-status-dev.js",
    "homeassistant/www/house-status-dev/lifeos-house-status-dev-loader.js",
    "scripts/lifeos-energy-history-live-acceptance.py",
    "scripts/lifeos-deploy-energy-opportunity-api.sh",
}
ENERGY_PREFIXES = ("homelab/live/mnt/docker-data/automation/repos/LifeOS-Energy/app/",)
DOORBELL_ONLY_CHANGED_FUNCTIONS = {"normalize_doorbell", "denormalize_doorbell"}


def _builder_without_doorbell_functions(source: str) -> str:
    tree = ast.parse(source)
    tree.body = [
        node for node in tree.body
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in DOORBELL_ONLY_CHANGED_FUNCTIONS
        )
    ]
    return ast.dump(tree, include_attributes=False)


def energy_acceptance_required(changed_paths, old_builder: str | None, new_builder: str | None) -> bool:
    paths = set(changed_paths)
    if any(path in ENERGY_INPUTS or path.startswith(ENERGY_PREFIXES) for path in paths):
        return True

    if BUILDER not in paths:
        return False

    # A packager edit is exempt only when the PR also adds the governance regression
    # and every change is limited to those two files and the Doorbell-only functions.
    if not paths.issubset({BUILDER, GOVERNANCE_TEST}) or GOVERNANCE_TEST not in paths:
        return True
    if old_builder is None or new_builder is None:
        return True
    try:
        return _builder_without_doorbell_functions(old_builder) != _builder_without_doorbell_functions(new_builder)
    except (SyntaxError, TypeError, ValueError):
        return True


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: lifeos-house-status-energy-scope.py BASE_SHA HEAD_SHA", file=sys.stderr)
        return 2
    base, head = sys.argv[1:]
    try:
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", base, head], cwd=ROOT, text=True
        ).splitlines()
        old_builder = subprocess.check_output(
            ["git", "show", f"{base}:{BUILDER}"], cwd=ROOT, text=True
        )
        new_builder = (ROOT / BUILDER).read_text()
        required = energy_acceptance_required(changed, old_builder, new_builder)
    except (OSError, subprocess.CalledProcessError):
        # Unknown changes must not bypass the live Energy check.
        required = True
    print("true" if required else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
