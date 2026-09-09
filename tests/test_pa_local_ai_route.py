import importlib.util
import json
import sys
import types
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "homelab/live/home/joshan/automation/z97_job_submitter.py"
)


def load_bridge(tmp_path, monkeypatch):
    fake = types.ModuleType("governor.ai_broker")
    fake.OLLAMA_MODEL = "synthetic-model"
    fake._ollama = lambda prompt, model: json.dumps({
        "event_date": "2099-10-15",
        "event_time": "14:00",
        "action_due": "2099-10-13",
        "evidence": "SYNTHETIC-PAPERLESS-0001",
        "writes_performed": False,
    })

    governor = types.ModuleType("governor")
    governor.ai_broker = fake

    monkeypatch.setitem(sys.modules, "governor", governor)
    monkeypatch.setitem(sys.modules, "governor.ai_broker", fake)

    spec = importlib.util.spec_from_file_location("pa_bridge_test", SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.OUTBOX = tmp_path / "outbox"
    mod.RESULTS = tmp_path / "results"
    mod.LOGS = tmp_path / "logs"

    for p in (mod.OUTBOX, mod.RESULTS, mod.LOGS):
        p.mkdir()

    return mod


def test_pa_uses_local_broker_not_z97(monkeypatch, tmp_path):
    mod = load_bridge(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("PA attempted SSH/SCP/Engineer-VM execution")

    monkeypatch.setattr(mod, "run", forbidden)

    result = mod.submit(
        "pa",
        "synthetic appointment",
        wait=True,
    )

    assert result["ok"] is True
    assert result["route"] == "local_ai_broker"
    assert result["response"]["event_date"] == "2099-10-15"
    assert result["response"]["action_due"] == "2099-10-13"
    assert result["response"]["writes_performed"] is False
