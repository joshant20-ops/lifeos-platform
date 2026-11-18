"""Bounded health sampling for maintenance; no network or service mutations."""
import threading
import time


class HealthUnavailable(RuntimeError):
    pass


class HealthGate:
    """Latch any unhealthy result until a new maintenance session is started.

    probe must itself have bounded I/O timeouts. A hung probe cannot keep a
    previous success usable: guard rejects stale samples using monotonic time.
    """
    def __init__(self, probe, *, interval=1.0, max_age=3.0, clock=time.monotonic):
        if interval <= 0 or max_age <= interval:
            raise ValueError("invalid_sampling_limits")
        self.probe = probe
        self.interval = interval
        self.max_age = max_age
        self.clock = clock
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.failed = False
        self.observed = None
        self.thread = None
        self.failure_reason = None
        self.failure_checks = {}
        self.failure_duration_ms = None

    def sample(self):
        started = self.clock()
        checks = {}
        probe_error = False
        try:
            checks = self.probe()
            healthy = bool(checks) and all(value is True for value in checks.values())
        except Exception:
            healthy = False
            probe_error = True
        duration = self.clock() - started
        with self.lock:
            # A slow successful response is not fresh evidence.
            failed = not healthy or duration >= self.max_age
            if failed and self.failure_reason is None:
                self.failure_reason = "PROBE_ERROR" if probe_error else (
                    "SLOW_PROBE" if healthy else "FAILED_CHECKS")
                self.failure_checks = {
                    key: value is True for key, value in checks.items()
                } if isinstance(checks, dict) else {}
                self.failure_duration_ms = max(0, round(duration * 1000))
            self.failed |= failed
            self.observed = started

    def diagnostics(self, allowed_checks):
        """Return fixed failure states and caller-allowlisted booleans only."""
        with self.lock:
            reason = self.failure_reason
            if reason is None:
                if self.observed is None:
                    reason = "NOT_SAMPLED"
                elif self.clock() - self.observed >= self.max_age:
                    reason = "STALE_SAMPLE"
                elif self.stopped.is_set():
                    reason = "CLOSED"
                else:
                    reason = "HEALTHY"
            return {
                "reason": reason,
                "failed_checks": sorted(key for key in allowed_checks
                                        if key in self.failure_checks and not self.failure_checks[key]),
                "first_failure_duration_ms": self.failure_duration_ms,
            }

    def guard(self):
        with self.lock:
            if (self.failed or self.observed is None or self.stopped.is_set()
                    or self.clock() - self.observed >= self.max_age):
                if self.failure_reason is None:
                    self.failure_reason = "NOT_SAMPLED" if self.observed is None else (
                        "CLOSED" if self.stopped.is_set() else "STALE_SAMPLE")
                raise HealthUnavailable("maintenance_health_unavailable")

    def start(self):
        if self.thread is not None or self.stopped.is_set():
            raise HealthUnavailable("health_session_not_reusable")
        self.sample()
        self.guard()
        def monitor():
            while not self.stopped.wait(self.interval):
                self.sample()
        self.thread = threading.Thread(target=monitor, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=self.max_age)

