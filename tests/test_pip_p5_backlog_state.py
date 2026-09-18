import importlib.util
from pathlib import Path

P=Path(__file__).parents[1]/"scripts/lifeos-pip-p5-backlog-state.py"
spec=importlib.util.spec_from_file_location("p5",P); p5=importlib.util.module_from_spec(spec); spec.loader.exec_module(p5)

def test_state_is_resumable_and_content_free(tmp_path):
    db=p5.connect(tmp_path/"p5.sqlite3")
    p5.upsert(db,10,"pending_native"); p5.upsert(db,11,"semantic_pending"); p5.checkpoint(db,"cursor",11); db.commit(); db.close()
    db=p5.connect(tmp_path/"p5.sqlite3")
    assert p5.summary(db)=={"pending_native":1,"semantic_pending":1}
    cols={r[1] for r in db.execute("pragma table_info(document_state)")}
    assert cols=={"paperless_id","state","attempts","updated_at"}
    assert db.execute("select value from checkpoint where name='cursor'").fetchone()[0]==11

def test_invalid_state_fails_closed(tmp_path):
    db=p5.connect(tmp_path/"p5.sqlite3")
    import pytest
    with pytest.raises(ValueError): p5.upsert(db,1,"deleted")


def test_inventory_does_not_demote_semantic_terminal_states(tmp_path):
    db=p5.connect(tmp_path/"p5.sqlite3")
    p5.upsert(db,1,"semantic_resolved",increment_attempt=True); p5.upsert(db,2,"review",increment_attempt=True); db.commit()
    p5.inventory_upsert(db,1,"semantic_pending"); p5.inventory_upsert(db,2,"semantic_pending"); db.commit()
    assert db.execute("select state,attempts from document_state where paperless_id=1").fetchone()==("semantic_resolved",1)
    assert db.execute("select state,attempts from document_state where paperless_id=2").fetchone()==("review",1)

def test_semantic_result_is_private_and_durable(tmp_path):
    path=tmp_path/"state"/"p5.sqlite3"; db=p5.connect(path); p5.upsert(db,7,"semantic_pending")
    p5.store_result(db,7,{"summary":"private derived result"},"ollama","test"); p5.upsert(db,7,"semantic_resolved"); db.commit(); db.close()
    assert path.stat().st_mode & 0o777 == 0o600
    db=p5.connect(path); assert db.execute("select provider from semantic_result where paperless_id=7").fetchone()[0]=="ollama"
