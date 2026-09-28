#!/usr/bin/env python3
"""P6-P10 LifeOS cross-system layer. Authorities stay Gmail/Paperless/accounting."""
from __future__ import annotations
import hashlib,json,os,sqlite3,time
from pathlib import Path
DEFAULT_DB=Path.home()/".local/state/lifeos/pip/cross_system.sqlite3"
DISPOSITIONS={"IGNORE","ACTION","RETAIN","ACTION_AND_RETAIN","REVIEW"}
def connect(path=DEFAULT_DB):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(path.parent,0o700)
 db=sqlite3.connect(path,timeout=30)
 db.executescript("""CREATE TABLE IF NOT EXISTS email_disposition(message_ref TEXT PRIMARY KEY,disposition TEXT NOT NULL,reason_code TEXT NOT NULL,paperless_id INTEGER,action_ref TEXT,updated_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS relationship(id INTEGER PRIMARY KEY,source_system TEXT NOT NULL,source_ref TEXT NOT NULL,target_system TEXT NOT NULL,target_ref TEXT NOT NULL,relation TEXT NOT NULL,provenance TEXT NOT NULL,UNIQUE(source_system,source_ref,target_system,target_ref,relation));
 CREATE TABLE IF NOT EXISTS relationship_proposal(id INTEGER PRIMARY KEY,source_system TEXT NOT NULL,source_ref TEXT NOT NULL,target_system TEXT NOT NULL,target_ref TEXT NOT NULL,relation TEXT NOT NULL,confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),evidence_json TEXT NOT NULL,model TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('REVIEW','REJECTED','ACCEPTED')),provenance TEXT NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(source_system,source_ref,target_system,target_ref,relation));
 CREATE TABLE IF NOT EXISTS evidence_link(ledger_system TEXT NOT NULL,ledger_ref TEXT NOT NULL,paperless_id INTEGER NOT NULL,status TEXT NOT NULL CHECK(status IN ('MATCHED','AMBIGUOUS','MISSING','REVIEW')),provenance TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(ledger_system,ledger_ref,paperless_id));
 CREATE TABLE IF NOT EXISTS service_state(name TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS exception_queue(kind TEXT NOT NULL,ref TEXT NOT NULL,reason TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(kind,ref));""");db.commit()
 try: os.chmod(path,0o600)
 except FileNotFoundError: pass
 return db
def disposition(features):
 if features.get("explicit_action") and features.get("durable_evidence"): return "ACTION_AND_RETAIN"
 if features.get("explicit_action"): return "ACTION"
 if features.get("durable_evidence"): return "RETAIN"
 if features.get("known_noise"): return "IGNORE"
 return "REVIEW"
def record_email(db,message_ref,decision,reason,paperless_id=None,action_ref=None):
 if decision not in DISPOSITIONS: raise ValueError("invalid_disposition")
 db.execute("INSERT INTO email_disposition VALUES(?,?,?,?,?,?) ON CONFLICT(message_ref) DO UPDATE SET disposition=excluded.disposition,reason_code=excluded.reason_code,paperless_id=excluded.paperless_id,action_ref=excluded.action_ref,updated_at=excluded.updated_at",(message_ref,decision,reason,paperless_id,action_ref,int(time.time())));db.commit()
def link(db,ss,sr,ts,tr,relation,provenance="deterministic"):
 db.execute("INSERT OR IGNORE INTO relationship(source_system,source_ref,target_system,target_ref,relation,provenance) VALUES(?,?,?,?,?,?)",(ss,sr,ts,tr,relation,provenance));db.commit()
def evidence(db,ledger_system,ledger_ref,paperless_id,status,provenance):
 db.execute("INSERT INTO evidence_link VALUES(?,?,?,?,?,?) ON CONFLICT(ledger_system,ledger_ref,paperless_id) DO UPDATE SET status=excluded.status,provenance=excluded.provenance,updated_at=excluded.updated_at",(ledger_system,ledger_ref,paperless_id,status,provenance,int(time.time())));db.commit()
def service(db,name,value):
 db.execute("INSERT INTO service_state VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(name,value,int(time.time())));db.commit()
def exception(db,kind,ref,reason):
 db.execute("INSERT OR REPLACE INTO exception_queue VALUES(?,?,?,?)",(kind,ref,reason,int(time.time())));db.commit()

ALLOWED_RELATIONS={"same_subject","supports","supersedes","related_transaction","same_contract","same_asset","same_event"}
def propose_relationship(db,ss,sr,ts,tr,relation,confidence,evidence_refs,model,provenance="local-ai-proposal"):
 if relation not in ALLOWED_RELATIONS: raise ValueError("invalid_relation")
 if ss==ts and str(sr)==str(tr): raise ValueError("self_relationship")
 if not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not 0<=confidence<=1: raise ValueError("invalid_confidence")
 if not isinstance(evidence_refs,list) or not 1<=len(evidence_refs)<=8 or any(not isinstance(x,str) or not x or len(x)>256 for x in evidence_refs): raise ValueError("invalid_evidence")
 status="REVIEW" if confidence>=0.65 else "REJECTED"
 now=int(time.time());payload=json.dumps(evidence_refs,separators=(",",":"),sort_keys=True)
 db.execute("""INSERT INTO relationship_proposal(source_system,source_ref,target_system,target_ref,relation,confidence,evidence_json,model,status,provenance,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_system,source_ref,target_system,target_ref,relation) DO UPDATE SET confidence=excluded.confidence,evidence_json=excluded.evidence_json,model=excluded.model,status=CASE WHEN relationship_proposal.status='ACCEPTED' THEN 'ACCEPTED' ELSE excluded.status END,provenance=excluded.provenance,updated_at=excluded.updated_at""",(ss,str(sr),ts,str(tr),relation,float(confidence),payload,model,status,provenance,now));db.commit();return status
def accept_relationship_proposal(db,proposal_id,reviewer="manual"):
 row=db.execute("SELECT source_system,source_ref,target_system,target_ref,relation FROM relationship_proposal WHERE id=? AND status='REVIEW'",(proposal_id,)).fetchone()
 if not row: raise ValueError("proposal_not_reviewable")
 link(db,*row,provenance=reviewer)
 db.execute("UPDATE relationship_proposal SET status='ACCEPTED',provenance=?,updated_at=? WHERE id=?",(reviewer,int(time.time()),proposal_id));db.commit()
