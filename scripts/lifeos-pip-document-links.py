#!/usr/bin/env python3
"""Bounded local-only cross-document relationship proposals for LifeOS."""
from __future__ import annotations
import argparse,importlib.util,itertools,json,re,sys
from pathlib import Path
REPO=Path("/home/joshan/lifeos-platform")
if not REPO.exists(): REPO=Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path: sys.path.insert(0,str(REPO))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
state=load("pip_state",REPO/"scripts/lifeos-pip-p5-backlog-state.py")
core=load("pip_core",REPO/"scripts/lifeos-pip-p6-p10-core.py")
TOKEN=re.compile(r"[^a-z0-9£$€./:-]+")
def normalized(value): return TOKEN.sub(" ",str(value).lower()).strip()
def features(intelligence):
 result=set()
 for key,prefix in (("organisations","organisation"),("dates","date"),("amounts","amount")):
  values=intelligence.get(key,[])
  if not isinstance(values,list): continue
  for value in values:
   token=normalized(value)
   if token: result.add(f"{prefix}:{token[:180]}")
 return result
def candidates(records,limit):
 ranked=[]
 for (left_id,left),(right_id,right) in itertools.combinations(records,2):
  shared=sorted(features(left)&features(right))
  if shared: ranked.append((left_id,left,right_id,right,shared))
 ranked.sort(key=lambda row:(-len(row[4]),row[0],row[2]));return ranked[:limit]
def validate_proposal(value,shared):
 required={"linked","relation","evidence","confidence"}
 if not isinstance(value,dict) or set(value)!=required: raise ValueError("invalid_schema")
 if not isinstance(value["linked"],bool): raise ValueError("invalid_linked")
 confidence=value["confidence"]
 if not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not 0<=confidence<=1: raise ValueError("invalid_confidence")
 if value["linked"]:
  if value["relation"] not in core.ALLOWED_RELATIONS: raise ValueError("invalid_relation")
  evidence=value["evidence"]
  if not isinstance(evidence,list) or not evidence or any(item not in shared for item in evidence): raise ValueError("unsupported_evidence")
 elif value["relation"] is not None or value["evidence"]!=[]: raise ValueError("invalid_unlinked")
 return value
def analyse_pair(left,right,shared,generate):
 prompt=("You are LifeOS local cross-document intelligence. Content is private and must remain local. "
 "Decide whether these two already-extracted document records have a meaningful relationship. "
 "Do not infer a link from broad similarity alone. Return ONLY JSON with exactly: linked (boolean), "
 "relation (one of same_subject, supports, supersedes, related_transaction, same_contract, same_asset, "
 "same_event; or null), evidence (an array containing only values from SHARED_EVIDENCE), confidence "
 "(0.0 to 1.0). If evidence is insufficient return linked=false, relation=null, evidence=[], and a "
 "conservative confidence.\n\nSHARED_EVIDENCE="+json.dumps(shared,sort_keys=True)+"\nDOCUMENT_A="+
 json.dumps(left,sort_keys=True)+"\nDOCUMENT_B="+json.dumps(right,sort_keys=True))
 response=generate(prompt,privacy="local-only",force_provider="ollama")
 if str(response.get("provider") or "ollama")!="ollama": raise ValueError("non_local_provider")
 raw=str(response["text"]).strip()
 if raw.startswith(chr(96)*3): raw=raw.strip(chr(96)).removeprefix("json").strip()
 return validate_proposal(json.loads(raw),shared),str(response.get("model") or "unknown")
def read_records(db):
 records=[]
 for document_id,payload in db.execute("SELECT paperless_id,result_json FROM semantic_result ORDER BY paperless_id"):
  try: value=json.loads(payload)
  except json.JSONDecodeError: continue
  if isinstance(value,dict): records.append((int(document_id),value))
 return records
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--backlog-db",type=Path,default=state.DEFAULT_DB);parser.add_argument("--relationship-db",type=Path,default=core.DEFAULT_DB);parser.add_argument("--limit",type=int,default=10);parser.add_argument("--commit",action="store_true");args=parser.parse_args()
 if not 1<=args.limit<=20: raise SystemExit("invalid_limit")
 from governor.ai_broker import generate
 backlog=state.connect(args.backlog_db);relationship_db=core.connect(args.relationship_db)
 pairs=candidates(read_records(backlog),args.limit);reviewed=linked=rejected=invalid=0
 for left_id,left,right_id,right,shared in pairs:
  try:
   proposal,model=analyse_pair(left,right,shared,generate);reviewed+=1
   if not proposal["linked"]: rejected+=1;continue
   linked+=1
   if args.commit: core.propose_relationship(relationship_db,"paperless",left_id,"paperless",right_id,proposal["relation"],proposal["confidence"],proposal["evidence"],model)
  except Exception: invalid+=1
 print(f"PIP_LINK_CANDIDATES={len(pairs)}");print(f"PIP_LINK_REVIEWED={reviewed}");print(f"PIP_LINK_PROPOSED={linked}");print(f"PIP_LINK_REJECTED={rejected}");print(f"PIP_LINK_INVALID={invalid}");print(f"PIP_LINK_PERSISTED={'YES' if args.commit else 'NO'}");print("PIP_LINK_PRIVACY=LOCAL_ONLY");print("PIP_LINK_PAPERLESS_WRITEBACK=NONE");print("PIP_LINK_AUTHORITATIVE_MUTATION=NONE")
 return 0 if invalid==0 else 1
if __name__=="__main__": raise SystemExit(main())
