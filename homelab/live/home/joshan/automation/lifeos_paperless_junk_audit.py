#!/usr/bin/env python3
"""Read-only, resumable local Paperless junk audit."""
from __future__ import annotations
import json, pathlib, subprocess, sys
from collections import Counter
REPO=pathlib.Path('/home/joshan/lifeos-platform'); sys.path.insert(0,str(REPO)) if str(REPO) not in sys.path else None
from governor.ai_broker import OLLAMA_MODEL, _ollama
CONTAINER='paperless-paperless-1'; SNIPPET=2500; AI_BATCH=8; RUN_LIMIT=64
STATE=pathlib.Path('/home/joshan/automation/state/paperless-junk-audit.json')
VALID={'KEEP','LIKELY_JUNK','REVIEW'}

def read_docs():
 code=f'''\nimport json\nfrom documents.models import Document\nfor d in Document.objects.order_by("id"):\n print(json.dumps({{"id":d.id,"title":d.title or "","content":(d.content or "")[:{SNIPPET}]}}))\n'''
 p=subprocess.run(['docker','exec',CONTAINER,'python3','manage.py','shell','-c',code],capture_output=True,text=True,timeout=120)
 if p.returncode: raise RuntimeError('paperless_read_failed')
 out=[]
 for line in p.stdout.splitlines():
  try: x=json.loads(line.strip())
  except Exception: continue
  if isinstance(x,dict) and isinstance(x.get('id'),int): out.append(x)
 return out

def parse(raw):
 raw=raw.strip()
 if raw.startswith('```'): raw=raw.strip('`').removeprefix('json').strip()
 return json.loads(raw)

def classify(batch):
 prompt='''You are LifeOS local document hygiene. Private data must remain local. Classify EACH document KEEP, LIKELY_JUNK, or REVIEW. LIKELY_JUNK only for obvious spam/advertising/promotions/meaningless captures/transient material with no durable evidential value. KEEP plausible durable personal/household records, receipts, invoices, contracts, policies, certificates, official correspondence, bookings, warranties, tax/bank/pension/property/employment records. Err toward KEEP or REVIEW. Return ONLY JSON array objects {"id":integer,"classification":"KEEP|LIKELY_JUNK|REVIEW","confidence":number}.\nDOCUMENTS:\n'''+json.dumps([{'id':d['id'],'title':d['title'],'content':d['content']} for d in batch],ensure_ascii=False)
 data=parse(_ollama(prompt,OLLAMA_MODEL)); expected={d['id'] for d in batch}; got=set(); out=[]
 if not isinstance(data,list): raise ValueError('not_array')
 for x in data:
  i=x.get('id'); c=x.get('classification'); q=x.get('confidence')
  if i not in expected or i in got or c not in VALID or not isinstance(q,(int,float)) or not 0<=float(q)<=1: raise ValueError('schema')
  got.add(i); out.append({'id':i,'classification':c,'confidence':float(q)})
 if got!=expected: raise ValueError('missing')
 return out

def load_state():
 try:
  x=json.loads(STATE.read_text()); return x if isinstance(x,dict) else {}
 except Exception: return {}

def save_state(s):
 STATE.parent.mkdir(parents=True,exist_ok=True); tmp=STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(s,separators=(',',':'))); tmp.replace(STATE)

def main():
 docs=read_docs(); ids={d['id'] for d in docs}; state=load_state(); results={int(k):v for k,v in state.get('results',{}).items() if int(k) in ids}; failures=int(state.get('failures',0))
 pending=[d for d in docs if d['id'] not in results][:RUN_LIMIT]
 for n in range(0,len(pending),AI_BATCH):
  batch=pending[n:n+AI_BATCH]
  try: rows=classify(batch)
  except Exception:
   failures+=1; rows=[{'id':d['id'],'classification':'REVIEW','confidence':0.0} for d in batch]
  for r in rows: results[r['id']]=r
  save_state({'results':{str(k):v for k,v in results.items()},'failures':failures})
 counts=Counter(v['classification'] for v in results.values()); remaining=len(docs)-len(results)
 print(f'PAPERLESS_DOCUMENTS={len(docs)}'); print(f'PROCESSED={len(results)}'); print(f'REMAINING={remaining}'); print(f'KEEP={counts["KEEP"]}'); print(f'LIKELY_JUNK={counts["LIKELY_JUNK"]}'); print(f'REVIEW={counts["REVIEW"]}'); print(f'AUDIT_FAILURES={failures}')
 print('LIKELY_JUNK_IDS='+','.join(str(k) for k,v in results.items() if v['classification']=='LIKELY_JUNK'))
 print('REVIEW_IDS='+','.join(str(k) for k,v in results.items() if v['classification']=='REVIEW'))
 print('PAPERLESS_MUTATION=NONE'); print('PRIVACY_LOCAL_ONLY=PASS'); print('AUDIT_COMPLETE='+('YES' if remaining==0 else 'NO')); print('RESULT=PASS')
 return 0
if __name__=='__main__': raise SystemExit(main())
