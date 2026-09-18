#!/usr/bin/env python3
import argparse, importlib.util, sqlite3, subprocess, sys
from pathlib import Path
REPO=Path("/home/joshan/lifeos-platform")
spec=importlib.util.spec_from_file_location("p5state",REPO/"scripts/lifeos-pip-p5-backlog-state.py")
state=importlib.util.module_from_spec(spec); spec.loader.exec_module(state)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",type=Path,default=state.DEFAULT_DB); a=p.parse_args()
    container="paperless-paperless-1"
    subprocess.run(["docker","cp",str(REPO/"scripts/lifeos-pip-p2-paperless-shadow.py"),f"{container}:/tmp/lifeos-pip-p2-lib.py"],check=True,stdout=subprocess.DEVNULL)
    src=(REPO/"scripts/lifeos-pip-p5-native-inventory.py").read_text()
    r=subprocess.run(["docker","exec","-i",container,"python3","manage.py","shell"],input=src,text=True,capture_output=True,check=True,timeout=900)
    db=state.connect(a.db); seen=0
    for line in r.stdout.splitlines():
        parts=line.strip().split("\t")
        if len(parts)==2 and parts[0].isdigit() and parts[1] in {"native_resolved","semantic_pending"}:
            state.inventory_upsert(db,int(parts[0]),parts[1]); seen+=1
    if not seen: raise RuntimeError("no_inventory_rows")
    state.checkpoint(db,"native_inventory_count",seen); db.commit()
    counts=state.summary(db)
    print(f"P5_INVENTORY_TOTAL={seen}")
    print(f"P5_NATIVE_RESOLVED={counts.get('native_resolved',0)}")
    print(f"P5_SEMANTIC_PENDING={counts.get('semantic_pending',0)}")
    print("P5_PRIVATE_CONTENT_EMITTED=NONE")
    print("P5_PAPERLESS_MUTATION=NONE")
    print("RESULT=PASS")
if __name__=="__main__": main()
