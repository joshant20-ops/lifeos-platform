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
    "homeassistant/www/house-status-dev/lifeos-house-status-dev-loader.js",
    "scripts/lifeos-energy-history-live-acceptance.py",
    "scripts/lifeos-deploy-energy-opportunity-api.sh",
}
ENERGY_PREFIXES = ("homelab/live/mnt/docker-data/automation/repos/LifeOS-Energy/app/",)
DOORBELL_ONLY_CHANGED_FUNCTIONS = {"normalize_doorbell", "denormalize_doorbell"}

APP_INPUT = "homeassistant/www/house-status-dev/lifeos-house-status-dev.js"
DOORBELL_SHELL_TEST = "homeassistant/www/house-status-dev/test-doorbell-shell-isolation.js"
DOORBELL_ONLY_PATHS = {APP_INPUT, BUILDER, GOVERNANCE_TEST, DOORBELL_SHELL_TEST,
    "homeassistant/www/house-status-dev/test-doorbell-bootstrap.js",
    "homeassistant/www/house-status-dev/lifeos-house-status-doorbell.js",
    ".github/workflows/house-status-dev-deploy.yml",
    "scripts/lifeos-house-status-energy-scope.py"}
OLD_DOORBELL_SETTER = "  set hass(hass){ this._hass=hass; const host=this._doorbellHost; if(this._mode==='doorbell'&&host?.isConnected){host.__lifeosDoorbellHass=hass;if(host.__lifeosCameraCard)host.__lifeosCameraCard.hass=hass;return;} this.render(); if(this._mode!=='doorbell')this._loadEnergyHistory(); }"
BASE_DOORBELL_SETTER = "  set hass(hass){ this._hass=hass; const mode=this._mode||this.config?.mode||'domestic'; const host=this._doorbellHost; if(mode==='doorbell'&&host?.isConnected){host.__lifeosDoorbellHass=hass;try{if(host.__lifeosCameraCard)host.__lifeosCameraCard.hass=hass;}catch(error){console.warn('House Status Doorbell camera update failed',error);}return;} this.render(); if(mode!=='doorbell')this._loadEnergyHistory(); }"
NEW_DOORBELL_SETTER = "  set hass(hass){ this._hass=hass; const mode=this._mode||this.config?.mode||'domestic'; const host=this._doorbellHost; if(mode==='doorbell'&&host?.isConnected){try{host.hass=hass;}catch(error){console.warn('House Status Doorbell update failed',error);}return;} this.render(); if(mode!=='doorbell')this._loadEnergyHistory(); }"

def _without_doorbell_shell(source: str) -> str | None:
    text = source
    setters = (OLD_DOORBELL_SETTER, BASE_DOORBELL_SETTER, NEW_DOORBELL_SETTER)
    if sum(text.count(setter) for setter in setters) != 1:
        return None
    for setter in setters:
        text = text.replace(setter, "  set hass(hass){/* isolated Doorbell dispatch */}", 1)
    branch_start = "    if(mode==='doorbell'){\n"
    if branch_start in text:
        start = text.index(branch_start)
        end = text.find("    const stamp=o=>", start)
        if end < 0:
            return None
        block = text[start:end]
        required = ("this.dataset.module='doorbell'", "doorbell?.render", "doorbell.render(this._hass)",
                    "doorbell?.mount?.(this._doorbellHost,this._hass)", "this._doorbellHost", "return;")
        doorbell_path = block.split("    const moduleOwner=", 1)[0]
        forbidden = ("LifeOSEnergyModule", "LifeOSHouseModule", "sensor.", "event.",
                     "this._hass.states", "fetch(", "periodWindow(", "_loadEnergyHistory", "_history")
        if (any(token not in block for token in required)
                or any(token in doorbell_path for token in forbidden)
                or doorbell_path.rfind("return;") < 0):
            return None
        text = text[:start] + text[end:]
    owner_blocks = (
        "    const moduleOwner=LifeOSEnergyModule.owns(mode)?'energy':LifeOSHouseModule.owns(mode)?'house':LifeOSDoorbellModule.owns(mode)?'doorbell':'energy';\n    this.dataset.module=moduleOwner;\n",
        "    const moduleOwner=LifeOSEnergyModule.owns(mode)?'energy':LifeOSHouseModule.owns(mode)?'house':'energy';\n    this.dataset.module=moduleOwner;\n",
    )
    for owner_block in owner_blocks:
        text = text.replace(owner_block, "", 1)
    # This selector appears only in the unreachable legacy post-render Doorbell fallback;
    # normalize its old/new host markers after stripping the active early-return branch.
    legacy_selectors = ("querySelector('[data-doorbell-card]')",
                        "querySelector('[data-lifeos-doorbell-camera]')")
    legacy_count = sum(text.count(selector) for selector in legacy_selectors)
    if legacy_count > 1:
        return None
    for selector in legacy_selectors:
        text = text.replace(selector, "querySelector('[isolated-doorbell-host]')", 1)
    return text

def doorbell_shell_only_app_change(old_app: str, new_app: str) -> bool:
    old = _without_doorbell_shell(old_app)
    new = _without_doorbell_shell(new_app)
    return old is not None and new is not None and old == new


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


def energy_acceptance_required(changed_paths, old_builder: str | None, new_builder: str | None,
                              old_app: str | None = None, new_app: str | None = None) -> bool:
    paths = set(changed_paths)
    if any(path in ENERGY_INPUTS or path.startswith(ENERGY_PREFIXES) for path in paths):
        return True
    if APP_INPUT in paths:
        if (not paths.issubset(DOORBELL_ONLY_PATHS) or DOORBELL_SHELL_TEST not in paths
                or old_app is None or new_app is None
                or not doorbell_shell_only_app_change(old_app, new_app)):
            return True

    if BUILDER not in paths:
        return False

    # A packager edit is exempt only with governance coverage and Doorbell-only changes.
    # If the shared app changed, the strict shell normalizer above must prove Energy code is identical.
    if not paths.issubset(DOORBELL_ONLY_PATHS) or GOVERNANCE_TEST not in paths:
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
        old_app = new_app = None
        if APP_INPUT in changed:
            old_app = subprocess.check_output(["git", "show", f"{base}:{APP_INPUT}"], cwd=ROOT, text=True)
            new_app = (ROOT / APP_INPUT).read_text()
        required = energy_acceptance_required(changed, old_builder, new_builder, old_app, new_app)
    except (OSError, subprocess.CalledProcessError):
        # Unknown changes must not bypass the live Energy check.
        required = True
    print("true" if required else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
