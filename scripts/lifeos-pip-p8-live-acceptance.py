#!/usr/bin/env python3
import importlib.util,subprocess,uuid
from pathlib import Path
repo=Path("/home/joshan/lifeos-platform");p=repo/"scripts/lifeos-pip-p6-p10-core.py"
s=importlib.util.spec_from_file_location("pipcore",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);db=m.connect()
cmd=["docker","exec","-i","paperless-paperless-1","python3","manage.py","shell"]
query="from documents.models import Document; print(Document.objects.order_by('id').values_list('id',flat=True).first() or '')"
r=subprocess.run(cmd,input=query,capture_output=True,text=True,timeout=60)
lines=[x.strip() for x in r.stdout.splitlines() if x.strip()]
ids=[x for x in lines if x.isdigit()]
print(f"P8_PAPERLESS_CMD_RC={r.returncode}")
print(f"P8_PAPERLESS_STDOUT_LINES={len(lines)}")
print(f"P8_PAPERLESS_NUMERIC_LINES={len(ids)}")
print(f"P8_PAPERLESS_STDERR_PRESENT={'YES' if r.stderr.strip() else 'NO'}")
if r.returncode: raise SystemExit("P8_PAPERLESS_AUTHORITY_READ=COMMAND_FAIL")
if not ids: raise SystemExit("P8_PAPERLESS_AUTHORITY_READ=PARSE_FAIL")
pid=int(ids[-1]);marker="p8-canary:"+uuid.uuid4().hex
m.link(db,"lifeos_canary",marker,"paperless",str(pid),"evidence","p8_live_acceptance");m.link(db,"lifeos_canary",marker,"paperless",str(pid),"evidence","p8_live_acceptance")
if db.execute("select count(*) from relationship where source_system=? and source_ref=?",("lifeos_canary",marker)).fetchone()[0]!=1: raise SystemExit("P8_IDEMPOTENCY=FAIL")
r2=subprocess.run(cmd,input=query,capture_output=True,text=True,timeout=60)
ids2=[x.strip() for x in r2.stdout.splitlines() if x.strip().isdigit()]
if r2.returncode or not ids2 or ids2[-1]!=str(pid): raise SystemExit("P8_AUTHORITY_PRESERVED=FAIL")
db.execute("delete from relationship where source_system=? and source_ref=?",("lifeos_canary",marker));db.commit()
print("P8_LIVE_DB=PASS");print("P8_REAL_PAPERLESS_REFERENCE=PASS");print("P8_IDEMPOTENCY=PASS");print("P8_AUTHORITY_PRESERVED=PASS");print("P8_SOURCE_MUTATION=NONE");print("P8_CANARY_CLEANUP=PASS");print("P8_LIVE_ACCEPTANCE=PASS")
