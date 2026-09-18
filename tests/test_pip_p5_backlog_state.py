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
