#!/usr/bin/env python3
"""Live DEV Energy History acceptance against Enphase cache and Octopus rates."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo


def get_json(base_url: str, path: str) -> dict:
    try:
        with urlopen(base_url.rstrip("/") + path, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} for {path}")
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed for {path}: {type(exc).__name__}") from exc


def epoch(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8110")
    parser.add_argument("--week-start", default="2026-09-28")
    args = parser.parse_args()

    week_start = date.fromisoformat(args.week_start)
    zone = ZoneInfo("Europe/London")
    start = datetime.combine(week_start, time.min, tzinfo=zone)
    end = datetime.combine(week_start + timedelta(days=7), time.min, tzinfo=zone)
    start_epoch, end_epoch = int(start.timestamp()), int(end.timestamp())
    query = urlencode({"start": start_epoch, "end": end_epoch, "granularity": "30m"})
    rollups = get_json(args.base_url, "/api/energy/rollups?" + query)
    points = rollups.get("points")
    if not isinstance(points, list) or not points:
        raise RuntimeError("week rollup has no Enphase history points")
    if rollups.get("timezone") != "Europe/London":
        raise RuntimeError("rollup response timezone is not Europe/London")
    expected = int((end_epoch - start_epoch) / 1800)
    if len(points) != expected or rollups.get("coverage_percent", 0) < 99:
        raise RuntimeError(
            f"week coverage incomplete: {len(points)}/{expected} half-hours "
            f"({rollups.get('coverage_percent')}%)"
        )
    if rollups.get("missing_price_slots") != 0:
        raise RuntimeError(
            f"Octopus rates missing for {rollups.get('missing_price_slots')} half-hours"
        )
    low_coverage = [
        p for p in points if float(p.get("sample_coverage_percent", 0)) < 80
    ]
    if low_coverage:
        coverages = [float(p.get("sample_coverage_percent", 0)) for p in points]
        details = ", ".join(
            f"{datetime.fromtimestamp(int(p['timestamp']), zone).isoformat()}:"
            f"{p.get('sample_count', 0)} samples/"
            f"{p.get('sample_coverage_percent', 0)}%"
            for p in low_coverage[:12]
        )
        raise RuntimeError(
            "Enphase sample coverage below 80% in "
            f"{len(low_coverage)}/{len(points)} half-hours "
            f"(min={min(coverages):.1f}%, mean={sum(coverages)/len(coverages):.1f}%); "
            f"first low-coverage slots: {details}"
        )
    if any(p.get("domestic_import_cost_gbp") is None for p in points):
        raise RuntimeError("domestic import cost is missing for a priced half-hour")

    # Compare rollups with the independent interval-report integration of the
    # same Enphase Envoy cache and tariff-native Octopus slots.
    now = datetime.now(zone)
    hours = int((now.timestamp() - start_epoch) / 3600) + 2
    if not 1 <= hours <= 840:
        raise RuntimeError("requested acceptance week is outside report API history")
    report = get_json(args.base_url, "/api/energy/report?hours=" + str(hours))
    report_rows = {
        epoch(row["valid_from"]): row
        for row in report.get("intervals", [])
        if start_epoch <= epoch(row["valid_from"]) < end_epoch
    }
    if len(report_rows) != expected:
        raise RuntimeError(f"interval report returned {len(report_rows)}/{expected} slots")
    report_usage = sum(float(row["domestic_import_kwh"]) for row in report_rows.values())
    rollup_usage = sum(float(point["domestic_import_kwh"]) for point in points)
    usage_tolerance = max(0.25, report_usage * 0.02)
    if abs(rollup_usage - report_usage) > usage_tolerance:
        raise RuntimeError(
            f"Enphase usage mismatch: rollup={rollup_usage:.3f}kWh "
            f"report={report_usage:.3f}kWh tolerance={usage_tolerance:.3f}kWh"
        )
    report_cost = sum(float(row["domestic_import_cost_gbp"]) for row in report_rows.values())
    rollup_cost = sum(float(point["domestic_import_cost_gbp"]) for point in points)
    cost_tolerance = max(0.08, report_cost * 0.02)
    if abs(rollup_cost - report_cost) > cost_tolerance:
        raise RuntimeError(
            f"Octopus cost mismatch: rollup=£{rollup_cost:.2f} "
            f"report=£{report_cost:.2f} tolerance=£{cost_tolerance:.2f}"
        )
    for point in points:
        reference = report_rows.get(int(point["timestamp"]))
        if reference is None or abs(
            float(point["import_p_per_kwh"]) - float(reference["import_p_per_kwh"])
        ) > 0.001:
            raise RuntimeError("Octopus half-hour price differs from interval report")

    print(
        "ENERGY_HISTORY_WEEK_COMPARISON=PASS "
        f"week={week_start.isoformat()} half_hours={len(points)} "
        f"Enphase_domestic_import_kwh={rollup_usage:.3f} "
        f"Octopus_domestic_import_cost_gbp={rollup_cost:.2f} "
        f"coverage_percent={rollups['coverage_percent']}"
    )
    print("ENERGY_HISTORY_API_LIVE_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
