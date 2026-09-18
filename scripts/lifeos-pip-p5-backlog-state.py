#!/usr/bin/env python3
"""P5 durable, resumable Paperless-first backlog state."""
from __future__ import annotations
import argparse,json,os,sqlite3,time
from pathlib import Path
DEFAULT_DB=Path.home()/".local/state/lifeos/pip/backlog.sqlite3"
VALID={"pending_native","native_resolved","semantic_pending","semantic_resolved","review","failed"}
def connect(path:Path):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(path.parent,0o700)
 db=sqlite3.connect(path,timeout=30)
 db.execute("""CREATE TABLE IF NOT EXISTS document_state(paperless_id INTEGER PRIMARY KEY,state TEXT NOT NULL CHECK(state IN ('pending_native','native_resolved','semantic_pending','semantic_resolved','review','failed')),attempts INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL)""")
 db.execute("""CREATE TABLE IF NOT EXISTS checkpoint(name TEXT PRIMARY KEY,value INTEGER NOT NULL,updated_at INTEGER NOT NULL)""")
 db.execute("""CREATE TABLE IF NOT EXISTS semantic_result(paperless_id INTEGER PRIMARY KEY,result_json TEXT NOT NULL,provider TEXT NOT NULL,model TEXT,processed_at INTEGER NOT NULL,FOREIGN KEY(paperless_id) REFERENCES document_state(paperless_id))""")
 db.commit()
 try: os.chmod(path,0o600)
 except FileNotFoundError: pass
 return db
def upsert(db,paperless_id:int,state:str,increment_attempt:bool=False):
 if state not in VALID: raise ValueError("invalid_state")
 now=int(time.time()); db.execute("""INSERT INTO document_state(paperless_id,state,attempts,updated_at) VALUES(?,?,?,?) ON CONFLICT(paperless_id) DO UPDATE SET state=excluded.state,attempts=document_state.attempts+excluded.attempts,updated_at=excluded.updated_at""",(paperless_id,state,1 if increment_attempt else 0,now))
def inventory_upsert(db,paperless_id:int,incoming:str):
 if incoming not in {"native_resolved","semantic_pending"}: raise ValueError("invalid_inventory_state")
 row=db.execute("SELECT state FROM document_state WHERE paperless_id=?",(paperless_id,)).fetchone()
 if not row: upsert(db,paperless_id,incoming); return
 current=row[0]
 if incoming=="native_resolved" and current in {"pending_native","semantic_pending"}: upsert(db,paperless_id,"native_resolved")
 elif incoming=="semantic_pending" and current=="pending_native": upsert(db,paperless_id,"semantic_pending")
def store_result(db,paperless_id:int,intelligence:dict,provider:str,model=None):
 payload=json.dumps(intelligence,separators=(",",":"),sort_keys=True)
 now=int(time.time()); db.execute("""INSERT INTO semantic_result(paperless_id,result_json,provider,model,processed_at) VALUES(?,?,?,?,?) ON CONFLICT(paperless_id) DO UPDATE SET result_json=excluded.result_json,provider=excluded.provider,model=excluded.model,processed_at=excluded.processed_at""",(paperless_id,payload,provider,model,now))
def checkpoint(db,name,value):
 now=int(time.time()); db.execute("""INSERT INTO checkpoint(name,value,updated_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",(name,value,now))
def summary(db): return dict(db.execute("SELECT state,count(*) FROM document_state GROUP BY state").fetchall())
def main():
 p=argparse.ArgumentParser();p.add_argument("--db",type=Path,default=DEFAULT_DB);p.add_argument("--summary",action="store_true");a=p.parse_args();db=connect(a.db)
 if a.summary:
  for k,v in sorted(summary(db).items()): print(f"P5_STATE_{k.upper()}={v}")
  print("P5_PRIVATE_CONTENT_LOGGED=NONE");print("P5_DOCUMENT_MUTATION=NONE")
 db.commit()
if __name__=="__main__":main()
