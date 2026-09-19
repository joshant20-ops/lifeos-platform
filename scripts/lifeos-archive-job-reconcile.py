#!/usr/bin/env python3
"""Reconcile archived Governor job records into failure families.
Sanitised aggregate output only; never emits request/evidence content.
"""
from __future__ import annotations
import json, pathlib, collections, re, sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
RECORDS=ROOT/"governor"/"job_records"

def family(o):
    status=str(o.get("final_status","UNKNOWN")).upper()
    term=o.get("terminal_outcome") or {}
    kind=str(term.get("kind","")).upper()
    failure=o.get("failure") or {}
    reason=str(failure.get("reason") or term.get("reason") or "").lower()
    stage=str(o.get("stage") or "").lower()
    if status=="PASS" or kind=="PASS": return "PASS"
    if "repeated deterministic failure" in reason or kind=="REPEATED_FAILURE": return "REPEATED_DETERMINISTIC_FAILURE"
    if "maximum iterations" in reason or kind=="ITERATION_LIMIT": return "ITERATION_LIMIT"
    if any(x in reason for x in ("verifier","verification")) or "verif" in stage: return "VERIFIER_FAILURE"
    if any(x in reason for x in ("read-only","readonly","permission","protected","sudo","credential","auth")): return "AUTHORITY_OR_PERMISSION"
    if any(x in reason for x in ("unavailable","connection","timeout","refused","wake","offline","ssh")): return "DEPENDENCY_OR_READINESS"
    if status=="BLOCKED" or kind=="BLOCKED": return "BLOCKED_OTHER"
    return "OTHER_NONPASS"

def main():
    files=sorted(RECORDS.glob("*.json"))
    counts=collections.Counter()
    ids=collections.defaultdict(list)
    malformed=[]
    for p in files:
        try: o=json.loads(p.read_text())
        except Exception:
            malformed.append(p.stem); continue
        f=family(o); counts[f]+=1; ids[f].append(str(o.get("job_id") or p.stem))
    nonpass=sum(v for k,v in counts.items() if k!="PASS")
    biggest=max(((v,k) for k,v in counts.items() if k!="PASS"), default=(0,"NONE"))
    print(f"ARCHIVE_RECORDS={len(files)}")
    print(f"ARCHIVE_MALFORMED={len(malformed)}")
    for k in sorted(counts): print(f"ARCHIVE_FAMILY_{k}={counts[k]}")
    print(f"ARCHIVE_NONPASS={nonpass}")
    print(f"ARCHIVE_BIGGEST_FAILURE_FAMILY={biggest[1]}")
    print(f"ARCHIVE_BIGGEST_FAILURE_COUNT={biggest[0]}")
    # IDs are safe opaque references; no private request/evidence content.
    if biggest[1]!="NONE":
        print("ARCHIVE_BIGGEST_FAILURE_IDS="+",".join(ids[biggest[1]]))
    return 1 if malformed else 0
if __name__=="__main__": raise SystemExit(main())
