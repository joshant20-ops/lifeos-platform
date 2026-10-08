import importlib.util
import pathlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wake_aware_gateway", ROOT / "governor" / "openhands_local_ai_gateway.py")
GATEWAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATEWAY)


def test_health_asleep_is_read_only(monkeypatch):
    monkeypatch.setattr(GATEWAY, "tower_accessible", lambda: False)
    monkeypatch.setattr(GATEWAY, "ollama_ready", lambda: False)
    monkeypatch.setattr(GATEWAY.BROKER, "_publish_lease", lambda *a, **k: (_ for _ in ()).throw(AssertionError("health woke Tower")))
    status = GATEWAY.health_status()
    assert status["status"] == "degraded"
    assert status["compute"] == "asleep"
    assert status["degraded_reason"] == "COMPUTE_ASLEEP"


def test_cold_concurrent_requests_coalesce_to_one_wake(monkeypatch, capsys):
    awake = threading.Event()
    leases = []
    monkeypatch.setattr(GATEWAY, "WAKE_TIMEOUT", 1)
    monkeypatch.setattr(GATEWAY, "tower_accessible", lambda: awake.is_set())
    monkeypatch.setattr(GATEWAY, "ollama_ready", lambda: awake.is_set())

    def publish(state, **kwargs):
        if state == "active":
            leases.append(state)
            if len(leases) == 1:
                threading.Timer(0.03, awake.set).start()
    monkeypatch.setattr(GATEWAY.BROKER, "_publish_lease", publish)

    def request():
        with GATEWAY.REQUEST_LOCK:
            GATEWAY.ensure_tower()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request) for _ in range(2)]
        for future in futures:
            future.result(timeout=2)
    assert len(leases) == 2
    assert capsys.readouterr().out.count("TOWER_WAKE_REQUEST=LEASE") == 1


def test_cold_request_has_bounded_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(GATEWAY, "WAKE_TIMEOUT", 0.02)
    monkeypatch.setattr(GATEWAY, "tower_accessible", lambda: False)
    monkeypatch.setattr(GATEWAY, "ollama_ready", lambda: False)
    monkeypatch.setattr(GATEWAY.BROKER, "_publish_lease", lambda state, **kwargs: calls.append(state))
    monkeypatch.setattr(GATEWAY.time, "sleep", lambda _: None)
    started = time.monotonic()
    try:
        GATEWAY.ensure_tower()
    except RuntimeError as error:
        assert "bounded wake timeout" in str(error)
    else:
        raise AssertionError("cold request did not time out")
    assert time.monotonic() - started < 1
    assert calls == ["active"]
