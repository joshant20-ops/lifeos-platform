#!/usr/bin/env python3
"""Project current EnergyOpportunity records into one deterministic HA attention record.

This is presentation glue only. It does not detect prices, notify people or control energy hardware.
The existing EnergyOpportunity opportunity_id remains the provenance/deduplication identity.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path.home() / ".local/state/lifeos/current-energy-opportunities.json"
DEFAULT_OUTPUT = Path("/opt/stacks/homeassistant/config/lifeos_energy_opportunity_attention.json")


def build_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [x for x in records if isinstance(x, dict) and x.get("opportunity_id")]
    valid.sort(key=lambda x: (str(x.get("start", "")), str(x.get("opportunity_id", ""))))
    ids = list(dict.fromkeys(str(x["opportunity_id"]) for x in valid))
    if not valid:
        return {
            "state": "clear",
            "count": 0,
            "attention_id": "",
            "opportunity_ids": [],
            "kind": "energy_opportunity",
            "severity": "info",
            "summary": "No negative-price energy opportunity",
        }
    first = valid[0]
    minimums = [float(x["minimum_price_p_per_kwh"]) for x in valid if x.get("minimum_price_p_per_kwh") is not None]
    minimum = min(minimums) if minimums else None
    start = str(first.get("start", ""))
    end = str(first.get("end", ""))
    summary = f"Negative-price electricity opportunity: {len(valid)} period"
    if len(valid) != 1:
        summary += "s"
    if minimum is not None:
        summary += f", minimum {minimum:g} p/kWh"
    return {
        "state": "attention",
        "count": len(valid),
        "attention_id": str(first["opportunity_id"]),
        "opportunity_ids": ids,
        "kind": "energy_opportunity",
        "severity": str(first.get("severity") or "opportunity"),
        "summary": summary,
        "start": start,
        "end": end,
        "minimum_price_p_per_kwh": minimum,
        "source": str(first.get("source") or ""),
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(rendered)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    records = json.loads(args.input.read_text()) if args.input.exists() else []
    if not isinstance(records, list):
        raise SystemExit("energy opportunity input must be a JSON list")
    projection = build_projection(records)
    atomic_write(args.output, projection)
    print("ENERGY_ATTENTION_PROJECTION=PASS")
    print("STATE=" + projection["state"])
    print("COUNT=" + str(projection["count"]))
    print("ATTENTION_ID=" + (projection["attention_id"] or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
