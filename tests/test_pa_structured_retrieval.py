"""Synthetic contract tests for local structured PA retrieval."""
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
SOURCE=REPO/"governor"/"assistant_bridge.py"

def load_bridge(monkeypatch,tmp_path):
    fake=types.ModuleType("ai_broker")
    fake.BrokerError=type("BrokerError",(RuntimeError,),{})
    fake.generate=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("structured PA query invoked inference"))
    monkeypatch.setitem(sys.modules,"ai_broker",fake)
    spec=importlib.util.spec_from_file_location("lifeos_assistant_bridge_test",SOURCE)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PA_TASKS_FILE=tmp_path/"lifeos_tasks.json"
    return mod

def state(now):
    return {
        "schema":"lifeos_tasks_v3",
        "generated_time":now,
        "tasks":[
            {"id":"task-open","title":"Synthetic home insurance renewal","status":"OPEN","topic":"insurance","due_date":"2025-01-16","observed_at":now,"paperless_evidence":[{"document_id":42,"title":"Synthetic policy schedule"}]},
            {"id":"task-wait","title":"Synthetic service reply","status":"WAITING","observed_at":now-3600,"paperless_evidence":[]},
        ],
        "resolved":[
            {"id":"task-done","title":"Synthetic completed request","status":"DONE","observed_at":now-1800,"paperless_evidence":[]}
        ],
        "attention":{
            "needs_me":[{"id":"task-open","title":"Synthetic home insurance renewal","status":"OPEN","due_date":"2025-01-16","source_refs":["<synthetic@example.test>"]}],
            "waiting_on_others":[{"id":"task-wait","title":"Synthetic service reply","status":"WAITING"}],
            "due_overdue":[{"id":"task-open","title":"Synthetic home insurance renewal","status":"OPEN","due_date":"2025-01-16"}],
            "upcoming":[],
            "recently_completed":[{"id":"task-done","title":"Synthetic completed request","status":"DONE"}],
            "stale_no_progress":[],
        }
    }

def test_supported_queries_use_local_structured_state(monkeypatch,tmp_path):
    mod=load_bridge(monkeypatch,tmp_path)
    now=1736899200
    payload=state(now)
    cases={
        "What needs me?":"Synthetic home insurance renewal",
        "What am I waiting for?":"Synthetic service reply",
        "What changed?":"Synthetic home insurance renewal",
        "What is due soon?":"Synthetic home insurance renewal",
    }
    for question,expected in cases.items():
        result=mod.pa_structured_answer(question,payload=payload,now_ts=now)
        assert result["ok"] is True
        assert result["route"]=="structured_pa_state"
        assert result["privacy"]=="local-only"
        assert expected in result["reply"]

def test_evidence_query_returns_paperless_reference_without_lookup(monkeypatch,tmp_path):
    mod=load_bridge(monkeypatch,tmp_path)
    now=1736899200
    result=mod.pa_structured_answer("What evidence do I have for insurance?",payload=state(now),now_ts=now)
    assert result["route"]=="structured_pa_state"
    assert "Paperless #42" in result["reply"]
    assert "Synthetic policy schedule" in result["reply"]
    assert "structured state only" in result["reply"]

def test_assist_and_chat_fast_paths_do_not_invoke_inference(monkeypatch,tmp_path):
    mod=load_bridge(monkeypatch,tmp_path)
    now=int(time.time())
    mod.PA_TASKS_FILE.write_text(json.dumps(state(now)))
    answer=mod.analyse([{"role":"user","content":"What needs me?"}])
    assert answer["provider"]=="structured_local_state"
    assert answer["privacy"]=="local-only"
    chat=mod.broker_chat({"messages":[{"role":"user","content":"What am I waiting for?"}]})
    assert chat["lifeos_provider"]=="structured_local_state"
    assert chat["lifeos_privacy"]=="local-only"
    assert "Synthetic service reply" in chat["choices"][0]["message"]["content"]

def test_stale_task_state_fails_closed(monkeypatch,tmp_path):
    mod=load_bridge(monkeypatch,tmp_path)
    result=mod.pa_structured_answer("What needs me?",payload=None,now_ts=2000000)
    assert result is not None and result["ok"] is False
    assert result["privacy"]=="local-only"
