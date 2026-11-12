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

    def sample(self):
        started = self.clock()
        try:
            checks = self.probe()
            healthy = bool(checks) and all(value is True for value in checks.values())
        except Exception:
            healthy = False
        with self.lock:
            # A slow successful response is not fresh evidence.
            self.failed |= not healthy or self.clock() - started >= self.max_age
            self.observed = started

    def guard(self):
        with self.lock:
            if (self.failed or self.observed is None or self.stopped.is_set()
                    or self.clock() - self.observed >= self.max_age):
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
