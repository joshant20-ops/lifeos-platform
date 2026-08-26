from datetime import datetime, timezone

WATCH_PREFIXES = (
    "public_exposure|",
    "username_exposure|",
    "phone_exposure|",
)

def utc_now_z():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_signal_map(status: dict) -> dict:
    out = {}

    for k, v in (status or {}).items():
        if not isinstance(v, dict):
            continue
        if str(k).startswith(WATCH_PREFIXES):
            out[str(k)] = v.get("confirmed")

    addr = status.get("address_exposure")
    if isinstance(addr, dict):
        out["address_exposure"] = addr.get("confirmed")

    return out


def detect_changes(prev_status: dict, new_status: dict):
    """
    Only log:
      - confirmed False -> confirmed True
      - confirmed True  -> confirmed False
    """
    prev_map = _extract_signal_map(prev_status)
    new_map = _extract_signal_map(new_status)

    changes = []
    keys = sorted(set(prev_map) | set(new_map))

    for key in keys:
        before = prev_map.get(key)
        after = new_map.get(key)

        if before is None or after is None:
            continue

        if before != after:
            changes.append({
                "ts": utc_now_z(),
                "signal": key,
                "before": before,
                "after": after,
            })

    return changes
