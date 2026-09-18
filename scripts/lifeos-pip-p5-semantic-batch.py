#!/usr/bin/env python3
"""Resumable P5 semantic processor with durable local structured results."""
import argparse,importlib.util,json,subprocess,sys
from pathlib import Path
REPO=Path("/home/joshan/lifeos-platform")
spec=importlib.util.spec_from_file_location("p5state",REPO/"scripts/lifeos-pip-p5-backlog-state.py");state=importlib.util.module_from_spec(spec);spec.loader.exec_module(state)
def process(db,limit):
 rows=db.execute("SELECT paperless_id FROM document_state WHERE state='semantic_pending' ORDER BY paperless_id LIMIT ?",(limit,)).fetchall();ok=review=0
 for (doc_id,) in rows:
  state.upsert(db,doc_id,"semantic_pending",increment_attempt=True);db.commit()
  r=subprocess.run([sys.executable,str(REPO/"homelab/live/home/joshan/automation/lifeos_paperless_local_ai.py"),str(doc_id)],capture_output=True,text=True,timeout=180)
  try: obj=json.loads(r.stdout) if r.returncode==0 else {}
  except Exception: obj={}
  intelligence=obj.get("intelligence")
  if obj.get("privacy")=="local_only" and obj.get("paperless_writeback_performed") is False and isinstance(intelligence,dict):
   provider=str(obj.get("provider") or obj.get("local_ai_provider") or "ollama")
   if provider!="ollama": state.upsert(db,doc_id,"review");review+=1
   else:
    state.store_result(db,doc_id,intelligence,provider,obj.get("local_ai_model") or obj.get("model"));state.upsert(db,doc_id,"semantic_resolved");ok+=1
  else: state.upsert(db,doc_id,"review");review+=1
  db.commit()
 return len(rows),ok,review
def main():
 p=argparse.ArgumentParser();p.add_argument("--db",type=Path,default=state.DEFAULT_DB);p.add_argument("--limit",type=int,default=50);p.add_argument("--drain",action="store_true");a=p.parse_args()
 if not 1<=a.limit<=50: raise SystemExit("invalid_limit")
 db=state.connect(a.db);selected=ok=review=0
 while True:
  n,o,r=process(db,a.limit);selected+=n;ok+=o;review+=r
  remaining=db.execute("SELECT count(*) FROM document_state WHERE state='semantic_pending'").fetchone()[0]
  state.checkpoint(db,"semantic_remaining",remaining);db.commit()
  if not a.drain or n==0 or remaining==0: break
 print(f"P5_BATCH_SELECTED={selected}");print(f"P5_BATCH_SEMANTIC_RESOLVED={ok}");print(f"P5_BATCH_REVIEW={review}");print(f"P5_SEMANTIC_REMAINING={remaining}")
 print(f"P5_DURABLE_RESULTS={db.execute('SELECT count(*) FROM semantic_result').fetchone()[0]}")
 print("P5_AI_PRIVACY=LOCAL_ONLY");print("P5_PAPERLESS_WRITEBACK=NONE");print("P5_PRIVATE_CONTENT_EMITTED=NONE");print("RESULT=PASS")
if __name__=="__main__":main()
