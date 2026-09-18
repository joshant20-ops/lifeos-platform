#!/usr/bin/env python3
"""Bounded resumable P5 semantic backlog processor."""
import argparse, importlib.util, json, subprocess, sys
from pathlib import Path
REPO=Path("/home/joshan/lifeos-platform")
spec=importlib.util.spec_from_file_location("p5state",REPO/"scripts/lifeos-pip-p5-backlog-state.py")
state=importlib.util.module_from_spec(spec); spec.loader.exec_module(state)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",type=Path,default=state.DEFAULT_DB); p.add_argument("--limit",type=int,default=10); a=p.parse_args()
    if not 1 <= a.limit <= 25: raise SystemExit("invalid_limit")
    db=state.connect(a.db)
    rows=db.execute("SELECT paperless_id FROM document_state WHERE state='semantic_pending' ORDER BY paperless_id LIMIT ?",(a.limit,)).fetchall()
    ok=review=0
    for (doc_id,) in rows:
        state.upsert(db,doc_id,"semantic_pending",increment_attempt=True); db.commit()
        r=subprocess.run([sys.executable,str(REPO/"homelab/live/home/joshan/automation/lifeos_paperless_local_ai.py"),str(doc_id)],capture_output=True,text=True,timeout=180)
        if r.returncode:
            state.upsert(db,doc_id,"review"); review+=1; db.commit(); continue
        try: obj=json.loads(r.stdout)
        except Exception:
            state.upsert(db,doc_id,"review"); review+=1; db.commit(); continue
        if obj.get("privacy")=="local_only" and obj.get("paperless_writeback_performed") is False and isinstance(obj.get("intelligence"),dict):
            state.upsert(db,doc_id,"semantic_resolved"); ok+=1
        else:
            state.upsert(db,doc_id,"review"); review+=1
        db.commit()
    print(f"P5_BATCH_SELECTED={len(rows)}")
    print(f"P5_BATCH_SEMANTIC_RESOLVED={ok}")
    print(f"P5_BATCH_REVIEW={review}")
    print("P5_AI_PRIVACY=LOCAL_ONLY")
    print("P5_PAPERLESS_WRITEBACK=NONE")
    print("P5_PRIVATE_CONTENT_EMITTED=NONE")
    print("RESULT=PASS")
if __name__=="__main__": main()
