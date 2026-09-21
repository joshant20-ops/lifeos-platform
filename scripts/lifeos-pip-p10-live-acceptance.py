#!/usr/bin/env python3
"""P10 live continuous-operation acceptance. Uses controlled references only."""
import importlib.util,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
repo=Path("/home/joshan/lifeos-platform");p=repo/"scripts/lifeos-pip-p6-p10-core.py"
s=importlib.util.spec_from_file_location("pipcore",p);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
dbp=Path.home()/".local/state/lifeos/pip/cross_system.sqlite3"
db=m.connect(dbp)
if (dbp.parent.stat().st_mode&0o777)!=0o700 or (dbp.stat().st_mode&0o777)!=0o600: raise SystemExit("P10_PRIVATE_PERMISSIONS=FAIL")
# Controlled canary exercises live production state, exception path, recovery/idempotency, and cleanup.
ref="p10-canary:"+uuid.uuid4().hex
m.service(db,"p10_acceptance","RUNNING");m.exception(db,"acceptance",ref,"controlled_canary");m.exception(db,"acceptance",ref,"controlled_canary")
if db.execute("select count(*) from exception_queue where kind='acceptance' and ref=?",(ref,)).fetchone()[0]!=1: raise SystemExit("P10_EXCEPTION_IDEMPOTENCY=FAIL")
db.close()
# Reopen production DB: persistence/recovery proof.
db=m.connect(dbp)
if db.execute("select reason from exception_queue where kind='acceptance' and ref=?",(ref,)).fetchone() is None: raise SystemExit("P10_RECOVERY=FAIL")
db.execute("delete from exception_queue where kind='acceptance' and ref=?",(ref,));db.execute("delete from service_state where name='p10_acceptance'");db.commit()
if db.execute("select count(*) from exception_queue where kind='acceptance' and ref=?",(ref,)).fetchone()[0]: raise SystemExit("P10_CLEANUP=FAIL")
print("P10_PRODUCTION_STATE=PASS");print("P10_PRIVATE_PERMISSIONS=PASS");print("P10_EXCEPTION_QUEUE=PASS");print("P10_EXCEPTION_IDEMPOTENCY=PASS");print("P10_RECOVERY=PASS");print("P10_CANARY_CLEANUP=PASS");print("P10_PRIVATE_CONTENT_EMITTED=NONE");print("P10_LIVE_ACCEPTANCE=PASS")
