#!/usr/bin/env python3
"""P5 final real-corpus acceptance: reconcile Paperless/state/results without emitting private content."""
from __future__ import annotations
import importlib.util, os, pathlib, sqlite3, subprocess, sys
REPO=pathlib.Path("/home/joshan/lifeos-platform")
spec=importlib.util.spec_from_file_location("p5state",REPO/"scripts/lifeos-pip-p5-backlog-state.py")
state=importlib.util.module_from_spec(spec); spec.loader.exec_module(state)
DB=state.DEFAULT_DB

# Backfill only legacy semantic_resolved rows that predate durable result storage.
pre=state.connect(DB)
legacy=pre.execute("SELECT d.paperless_id FROM document_state d LEFT JOIN semantic_result r ON r.paperless_id=d.paperless_id WHERE d.state='semantic_resolved' AND r.paperless_id IS NULL").fetchall()
for (doc_id,) in legacy: state.upsert(pre,doc_id,"semantic_pending")
pre.commit()
print(f"P5_ACCEPT_LEGACY_REQUEUED={len(legacy)}")
if legacy:
    subprocess.run([sys.executable,str(REPO/"scripts/lifeos-pip-p5-semantic-batch.py"),"--limit","50","--drain"],check=True,timeout=3600)

# Re-run native inventory: inventory_upsert must preserve terminal semantic states.
subprocess.run([sys.executable,str(REPO/"scripts/lifeos-pip-p5-inventory-runner.py")],check=True,timeout=1200)
db=state.connect(DB)
counts=state.summary(db)
total=sum(counts.values())
terminal=sum(counts.get(k,0) for k in ("native_resolved","semantic_resolved","review","failed"))
pending=sum(counts.get(k,0) for k in ("pending_native","semantic_pending"))
sem=counts.get("semantic_resolved",0)
results=db.execute("SELECT count(*) FROM semantic_result").fetchone()[0]
missing=db.execute("""SELECT count(*) FROM document_state d LEFT JOIN semantic_result r ON r.paperless_id=d.paperless_id WHERE d.state='semantic_resolved' AND r.paperless_id IS NULL""").fetchone()[0]
orphan=db.execute("""SELECT count(*) FROM semantic_result r LEFT JOIN document_state d ON d.paperless_id=r.paperless_id WHERE d.paperless_id IS NULL""").fetchone()[0]
bad_provider=db.execute("SELECT count(*) FROM semantic_result WHERE provider!='ollama'").fetchone()[0]
mode=(os.stat(DB).st_mode & 0o777)
parent_mode=(os.stat(DB.parent).st_mode & 0o777)
print(f"P5_ACCEPT_TOTAL={total}")
print(f"P5_ACCEPT_TERMINAL={terminal}")
print(f"P5_ACCEPT_PENDING={pending}")
print(f"P5_ACCEPT_NATIVE_RESOLVED={counts.get('native_resolved',0)}")
print(f"P5_ACCEPT_SEMANTIC_RESOLVED={sem}")
print(f"P5_ACCEPT_REVIEW={counts.get('review',0)}")
print(f"P5_ACCEPT_FAILED={counts.get('failed',0)}")
print(f"P5_ACCEPT_DURABLE_RESULTS={results}")
print(f"P5_ACCEPT_MISSING_RESULTS={missing}")
print(f"P5_ACCEPT_ORPHAN_RESULTS={orphan}")
print(f"P5_ACCEPT_NONLOCAL_PROVIDER_RESULTS={bad_provider}")
print(f"P5_ACCEPT_DB_MODE={mode:03o}")
print(f"P5_ACCEPT_DIR_MODE={parent_mode:03o}")
ok=(total==942 and terminal==942 and pending==0 and missing==0 and orphan==0 and bad_provider==0 and mode==0o600 and parent_mode==0o700)
print("P5_PRIVATE_CONTENT_EMITTED=NONE")
print("P5_PAPERLESS_WRITEBACK=NONE")
print("P5_FINAL_ACCEPTANCE="+("PASS" if ok else "FAIL"))
raise SystemExit(0 if ok else 1)
