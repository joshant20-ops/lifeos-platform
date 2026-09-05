#!/usr/bin/env python3
"""Run existing negative-price detection then project its current result to HA.

No notification or energy-control side effects are introduced here.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str) -> None:
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT, text=True)
    if cp.returncode:
        raise SystemExit(cp.returncode)


run("run-energy-opportunity-detection.py")
run("project-energy-opportunities-to-ha.py")
print("WAVE_A_ENERGY_ATTENTION_RUN=PASS")
