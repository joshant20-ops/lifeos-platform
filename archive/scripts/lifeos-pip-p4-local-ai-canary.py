#!/usr/bin/env python3
"""P4 local-only semantic canary for Paperless-native exceptions.

Selects stable IDs locally using the accepted P2 evaluator, then invokes the
existing governed Paperless semantic bridge for a tiny bounded canary.
Only aggregate validation results are emitted to CI.
"""
import json, subprocess, sys
LIMIT=3
repo="/home/joshan/lifeos-platform"
container="paperless-paperless-1"

selector = r'''
p2_source=open("/tmp/lifeos-pip-p2-lib.py").read()
p2_library=p2_source.rsplit("\\nmain()",1)[0]
exec(p2_library,globals())
documents=list(Document.objects.order_by("pk").select_related("correspondent","document_type","storage_path").prefetch_related("tags"))
sample,_=representative_sample(documents)
classifier=load_classifier()
dimensions=((Correspondent,),(DocumentType,),(Tag,),(StoragePath,))
rules={m:explicit_rules(m) for (m,) in dimensions}
autos={m:list(m.objects.filter(matching_algorithm=MatchingModel.MATCH_AUTO).order_by("pk")) for (m,) in dimensions}
def resolved(d):
    for (m,) in dimensions:
        if native_matches(rules[m],d): return True
    if classifier:
        if autos[Correspondent] and any(r.pk==classifier.predict_correspondent(d.suggestion_content) for r in autos[Correspondent]): return True
        if autos[DocumentType] and any(r.pk==classifier.predict_document_type(d.suggestion_content) for r in autos[DocumentType]): return True
        if autos[Tag]:
            p=set(classifier.predict_tags(d.suggestion_content))
            if any(r.pk in p for r in autos[Tag]): return True
        if autos[StoragePath] and any(r.pk==classifier.predict_storage_path(d.suggestion_content) for r in autos[StoragePath]): return True
    return False
print(",".join(str(d.pk) for d in sample if not resolved(d)))
'''
subprocess.run(["docker","cp",f"{repo}/scripts/lifeos-pip-p2-paperless-shadow.py",f"{container}:/tmp/lifeos-pip-p2-lib.py"],check=True,stdout=subprocess.DEVNULL)
r=subprocess.run(["docker","exec","-i",container,"python3","manage.py","shell"],input=selector,text=True,capture_output=True,check=True,timeout=60)
ids=[]
for line in reversed(r.stdout.splitlines()):
    line=line.strip()
    if line and all(x.isdigit() for x in line.split(",")):
        ids=[int(x) for x in line.split(",")][:LIMIT]; break
if not ids:
    raise SystemExit("P4_CANARY_FAIL=no_exception_ids")
valid=0
for doc_id in ids:
    p=subprocess.run([sys.executable,f"{repo}/homelab/live/home/joshan/automation/lifeos_paperless_local_ai.py",str(doc_id)],capture_output=True,text=True,timeout=180)
    if p.returncode: continue
    try: obj=json.loads(p.stdout)
    except Exception: continue
    intel=obj.get("intelligence")
    if obj.get("privacy")=="local_only" and obj.get("paperless_writeback_performed") is False and isinstance(intel,dict):
        valid+=1
print(f"P4_AI_CANARY_SELECTED={len(ids)}")
print(f"P4_AI_VALID_STRUCTURED={valid}")
print("P4_AI_PRIVACY=LOCAL_ONLY")
print("P4_AI_PAPERLESS_WRITEBACK=NONE")
print("P4_AI_PRIVATE_CONTENT_EMITTED=NONE")
print("RESULT="+("PASS" if valid==len(ids) else "FAIL"))
raise SystemExit(0 if valid==len(ids) else 1)
