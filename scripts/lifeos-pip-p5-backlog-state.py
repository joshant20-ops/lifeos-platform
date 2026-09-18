#!/usr/bin/env python3
"""P5 durable, resumable Paperless-first backlog state.

Stores only local orchestration state. Paperless remains document authority.
No OCR/content/title/taxonomy is copied into this database and no document is
deleted or mutated here.
"""
from __future__ import annotations
import argparse, sqlite3, time
from pathlib import Path

DEFAULT_DB=Path.home()/".local/state/lifeos/pip/backlog.sqlite3"
VALID={"pending_native","native_resolved","semantic_pending","semantic_resolved","review","failed"}

def connect(path: Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS document_state(
      paperless_id INTEGER PRIMARY KEY,
      state TEXT NOT NULL CHECK(state IN ('pending_native','native_resolved','semantic_pending','semantic_resolved','review','failed')),
      attempts INTEGER NOT NULL DEFAULT 0,
      updated_at INTEGER NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS checkpoint(
      name TEXT PRIMARY KEY, value INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )""")
    return db

def upsert(db, paperless_id:int, state:str):
    if state not in VALID: raise ValueError("invalid_state")
    now=int(time.time())
    db.execute("""INSERT INTO document_state(paperless_id,state,updated_at) VALUES(?,?,?)
      ON CONFLICT(paperless_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at""",(paperless_id,state,now))

def checkpoint(db,name:str,value:int):
    now=int(time.time())
    db.execute("""INSERT INTO checkpoint(name,value,updated_at) VALUES(?,?,?)
      ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",(name,value,now))

def summary(db):
    return dict(db.execute("SELECT state,count(*) FROM document_state GROUP BY state").fetchall())

def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",type=Path,default=DEFAULT_DB)
    p.add_argument("--summary",action="store_true")
    a=p.parse_args(); db=connect(a.db)
    if a.summary:
        for k,v in sorted(summary(db).items()): print(f"P5_STATE_{k.upper()}={v}")
        print("P5_PRIVATE_CONTENT_STORED=NONE")
        print("P5_DOCUMENT_MUTATION=NONE")
    db.commit()

if __name__=="__main__": main()
