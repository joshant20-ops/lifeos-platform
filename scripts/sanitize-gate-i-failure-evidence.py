#!/usr/bin/env python3
"""Write bounded, allow-listed Gate I failure evidence without copying raw logs."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ERROR_CODES = frozenset({
    "active_tower_lease_prevents_controller_restart",
    "bridge_not_active",
    "canonical_file_missing",
    "control_topic_absent",
    "homeassistant_health_after_control_adapters",
    "homeassistant_health_before_canonical_verify",
    "installed_bridge_missing",
    "invalid_tower_mac",
    "lifeos_control_storage_missing",
    "must_run_as_root",
    "tower_controller_main_pid_missing",
    "tower_controller_not_active",
    "tower_controller_runtime_idle_grace_not_600",
    "tower_entity_not_used",
    "tower_entity_resolution_missing",
    "tower_mac_does_not_match_canonical",
    "tower_runtime_state_not_accessible",
    "tower_state_topic_absent",
    "tower_switch_discovery_absent",
    "z97_disk_graphs_incomplete",
    "z97_history_graphs_incomplete",
    "z97_renderable_cards_incomplete",
    "z97_view_missing_after_ha_control_deploy",
    "z97_view_not_masonry",
})
SAFE_MARKERS = {
    "GATEWAY_RESULT": {"FAIL", "PASS", "RETRY"},
    "GATEWAY_OPERATION": {"deploy-ha-control-bridge"},
}
INTEGER_MARKERS = {"GATEWAY_CHILD_RC"}
HEX_MARKERS = {"GATEWAY_PLATFORM_HEAD"}
VERSION_MARKERS = {"LIFEOS_DEPLOY_GATEWAY_VERSION"}
MAX_LOG_BYTES = 2_000_000


def build_evidence(log_text: str, exit_code: int) -> dict[str, object]:
    diagnostics: list[str] = []
    gateway: dict[str, str | int] = {}
    for line in log_text.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        if key in {"ERROR", "GATEWAY_ERROR"}:
            code = value.split(":", 1)[0].split(None, 1)[0]
            if code in ERROR_CODES and code not in diagnostics:
                diagnostics.append(code)
        elif key in SAFE_MARKERS and value in SAFE_MARKERS[key]:
            gateway[key] = value
        elif key in INTEGER_MARKERS and re.fullmatch(r"-?\d{1,4}", value):
            gateway[key] = int(value)
        elif key in HEX_MARKERS and re.fullmatch(r"[0-9a-f]{40}", value):
            gateway[key] = value
        elif key in VERSION_MARKERS and re.fullmatch(r"\d{1,3}", value):
            gateway[key] = value
    return {
        "schema_version": 1,
        "operation": "deploy-ha-control-bridge",
        "exit_code": max(-255, min(255, int(exit_code))),
        "diagnostics": diagnostics[:32],
        "gateway": gateway,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: sanitize-gate-i-failure-evidence.py RAW_LOG OUTPUT_JSON EXIT_CODE", file=sys.stderr)
        return 64
    raw_path, output_path, exit_code = Path(argv[1]), Path(argv[2]), int(argv[3])
    with raw_path.open("rb") as source:
        raw = source.read(MAX_LOG_BYTES + 1)
    if len(raw) > MAX_LOG_BYTES:
        raw = raw[:MAX_LOG_BYTES]
    evidence = build_evidence(raw.decode("utf-8", errors="replace"), exit_code)
    output_path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
