"""Run the fixed allocation probe while the existing Tier 0 health gate is fresh."""

import os
import signal
import time

from governor.mqtt_live_rotation import connection_inputs, health_checks, RotationStopped
from governor.storage_health_gate import HealthUnavailable
from scripts.lifeos_storage_allocated_audit import main as audit


def main():
    if os.geteuid() != 0:
        print("STORAGE_ALLOCATION=FIXED_ROOT_GATEWAY_REQUIRED")
        return 2
    try:
        resolver, public = connection_inputs()
        next_probe = 0

        def guard(*, force=False, process=None):
            nonlocal next_probe
            started = time.monotonic()
            if not force and started < next_probe:
                return
            if process is not None:
                process.send_signal(signal.SIGSTOP)
            checks = health_checks(resolver, public)
            if (not checks or not all(value is True for value in checks.values())
                    or time.monotonic() - started >= 16):
                raise HealthUnavailable("maintenance_health_unavailable")
            next_probe = started + 8
            if process is not None:
                process.send_signal(signal.SIGCONT)

        guard()
        result = audit(guard=guard)
        guard(force=True)
        print("STORAGE_ALLOCATION_TIER0=PASS")
        return result
    except (HealthUnavailable, RotationStopped, OSError, ValueError, KeyError):
        print("STORAGE_ALLOCATION_TIER0=UNAVAILABLE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
