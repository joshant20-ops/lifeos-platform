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



def validate_period(
    base_url: str,
    name: str,
    start_date: date,
    end_date: date,
    expected_buckets: int,
    zone: ZoneInfo,
    bucket_mode: str,
    allow_partial: bool = False,
) -> dict:
    start = datetime.combine(start_date, time.min, tzinfo=zone)
    end = datetime.combine(end_date, time.min, tzinfo=zone)
    start_epoch, end_epoch = int(start.timestamp()), int(end.timestamp())
    query = urlencode({"start": start_epoch, "end": end_epoch, "granularity": "30m"})
    result = get_json(base_url, "/api/energy/rollups?" + query)
    points = result.get("points")
    expected_slots = int((end_epoch - start_epoch) / 1800)
    if result.get("timezone") != "Europe/London":
        raise RuntimeError(f"{name} rollup timezone is not Europe/London")
    count = len(points) if isinstance(points, list) else 0
    if not isinstance(points, list) or count > expected_slots or (
        not allow_partial and count != expected_slots
    ):
        raise RuntimeError(f"{name} rollup returned {count}/{expected_slots} half-hours")

    expected_coverage = round(100 * count / expected_slots, 1) if expected_slots else 100.0
    coverage = float(result.get("coverage_percent", 0))
    if abs(coverage - expected_coverage) > 0.2:
        raise RuntimeError(
            f"{name} reported coverage does not match returned intervals: "
            f"reported={coverage}% expected={expected_coverage}%"
        )
    is_partial = count < expected_slots
    if is_partial and (not allow_partial or result.get("complete") is not False):
        raise RuntimeError(
            f"{name} rollup is incomplete without an allowed partial-data state: "
            f"coverage={coverage}% complete={result.get('complete')}"
        )
    if not is_partial and result.get("complete") is not True:
        raise RuntimeError(f"{name} complete interval set is not marked complete")
    if result.get("missing_price_slots") != 0:
        raise RuntimeError(
            f"{name} rollup has missing Octopus prices: "
            f"{result.get('missing_price_slots')}"
        )
    if any(
        point.get("domestic_import_cost_gbp") is None
        or point.get("import_p_per_kwh") is None
        for point in points
    ):
        raise RuntimeError(f"{name} rollup has missing Enphase cost or Octopus price")
    sample_coverage = [
        float(point.get("sample_coverage_percent", 0)) for point in points
    ]
    mean_sample_coverage = sum(sample_coverage) / len(sample_coverage)
    if mean_sample_coverage < 90:
        raise RuntimeError(
            f"{name} Enphase sample coverage below 90%: "
            f"{mean_sample_coverage:.1f}%"
        )

    buckets: dict[str, dict[str, float]] = {}
    for point in points:
        stamp = int(point["timestamp"])
        if stamp < start_epoch or stamp >= end_epoch or stamp % 1800:
            raise RuntimeError(f"{name} rollup contains an invalid UTC boundary")
        local = datetime.fromtimestamp(stamp, zone)
        if datetime.fromisoformat(point["local_from"]) != local:
            raise RuntimeError(f"{name} local tariff boundary offset is invalid")
        if bucket_mode == "month":
            bucket_date = local.date() - timedelta(days=local.date().weekday())
            key = bucket_date.isoformat()
        elif bucket_mode == "year":
            key = local.strftime("%Y-%m")
        else:
            key = local.date().isoformat()
        bucket = buckets.setdefault(key, {"usage": 0.0, "cost": 0.0, "count": 0})
        bucket["usage"] += float(point["domestic_import_kwh"])
        bucket["cost"] += float(point["domestic_import_cost_gbp"])
        bucket["count"] += 1

    if bucket_mode == "year" and allow_partial:
        # Historical Enphase collection began after the start of this calendar
        # year. Validate each month that has source data; the API's coverage and
        # complete fields must continue to disclose absent earlier intervals.
        if len(buckets) < 3:
            raise RuntimeError(
                f"{name} history covers only {len(buckets)} month buckets; "
                "at least three are required to validate Year aggregation"
            )
        expected_buckets = len(buckets)
    if expected_buckets is None or len(buckets) != expected_buckets:
        raise RuntimeError(
            f"{name} dashboard aggregation produced {len(buckets)}/"
            f"{expected_buckets} expected buckets"
        )
    if any(
        bucket["count"] <= 0 or bucket["usage"] < 0 or bucket["cost"] < 0
        for bucket in buckets.values()
    ):
        raise RuntimeError(f"{name} dashboard aggregation contains an invalid bucket")

    usage = sum(bucket["usage"] for bucket in buckets.values())
    cost = sum(bucket["cost"] for bucket in buckets.values())
    print(
        f"ENERGY_HISTORY_{name.upper()}_VIEW=PASS "
        f"period={start_date.isoformat()}..{end_date.isoformat()} "
        f"half_hours={len(points)}/{expected_slots} buckets={len(buckets)} "
        f"coverage_percent={coverage:.1f} missing_half_hours={expected_slots-count} "
        f"partial={str(is_partial).lower()} "
        f"domestic_import_kwh={usage:.3f} cost_gbp={cost:.2f} "
        f"mean_sample_coverage_percent={mean_sample_coverage:.1f}"
    )
    return result

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
    coverages = [float(p.get("sample_coverage_percent", 0)) for p in points]
    mean_coverage = sum(coverages) / len(coverages)
    if mean_coverage < 90:
        low_coverage = [
            p for p in points if float(p.get("sample_coverage_percent", 0)) < 80
        ]
        details = ", ".join(
            f"{datetime.fromtimestamp(int(p['timestamp']), zone).isoformat()}:"
            f"{p.get('sample_count', 0)} samples/"
            f"{p.get('sample_coverage_percent', 0)}%"
            for p in low_coverage[:12]
        )
        raise RuntimeError(
            "Enphase mean sample coverage below 90%: "
            f"mean={mean_coverage:.1f}%, min={min(coverages):.1f}%; "
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

    low_sample_slots = sum(1 for value in coverages if value < 80)
    validate_period(
        args.base_url, "day", date(2026, 9, 29), date(2026, 9, 30), 1, zone, "day"
    )
    validate_period(
        args.base_url, "week", date(2026, 9, 28), date(2026, 10, 5), 7, zone, "week"
    )
    validate_period(
        args.base_url, "month", date(2026, 9, 1), date(2026, 10, 1), 5, zone, "month"
    )
    current_year_end = datetime.now(zone).date() + timedelta(days=1)
    validate_period(
        args.base_url, "year", date(2026, 1, 1), current_year_end,
        None, zone, "year", allow_partial=True,
    )

    print(
        "ENERGY_HISTORY_WEEK_COMPARISON=PASS "
        f"week={week_start.isoformat()} half_hours={len(points)} "
        f"Enphase_domestic_import_kwh={rollup_usage:.3f} "
        f"Octopus_domestic_import_cost_gbp={rollup_cost:.2f} "
        f"coverage_percent={rollups['coverage_percent']} "
        f"Enphase_mean_sample_coverage_percent={mean_coverage:.1f} "
        f"Enphase_low_sample_slots={low_sample_slots}"
    )
    print("ENERGY_HISTORY_API_LIVE_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
