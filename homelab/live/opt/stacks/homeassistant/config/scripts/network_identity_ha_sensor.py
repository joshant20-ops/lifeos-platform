#!/usr/bin/env python3
import json, sys
from pathlib import Path
CANDIDATES=[Path("/config/network_reconciliation.json"),Path("/config/watchman_gate_status.json"),Path("/config/watchman_policy_state.json"),Path("/config/execution_safety_dashboard.json")]
def read_json(p):
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}
def hosts():
    out=[]
    for p in CANDIDATES:
        d=read_json(p)
        for h in d.get("hosts",[]):
            if isinstance(h,dict) and h.get("host_id"):
                out.append(h)
    by={}
    for h in out:
        by[h["host_id"]]={**by.get(h["host_id"],{}),**h}
    return list(by.values())
def get(hid):
    return next((h for h in hosts() if h.get("host_id")==hid),{})
def main():
    key=sys.argv[1] if len(sys.argv)>1 else ""
    hs=hosts()
    if key=="known_host_count": print(len(hs)); return
    if key=="allowed_host_count": print(sum(1 for h in hs if h.get("allowed") is True or h.get("automation_policy")=="remote_actions_allowed")); return
    if key=="blocked_host_count": print(sum(1 for h in hs if h.get("allowed") is False or h.get("automation_policy")=="remote_actions_blocked")); return
    if key=="identity_summary":
        print(" | ".join([f"{h.get('host_id')}:{h.get('reconciliation_state') or h.get('identity') or 'unknown'}@{h.get('observed_ip') or h.get('ip') or 'unknown'}" for h in hs]) or "unknown"); return
    if key.startswith("host:"):
        _,hid,field=key.split(":",2)
        h=get(hid)
        if not h: print("unknown"); return
        if field=="identity": print(h.get("reconciliation_state") or h.get("identity") or "unknown"); return
        if field=="ip": print(h.get("observed_ip") or h.get("ip") or "unknown"); return
        if field=="state": print("READY" if h.get("allowed") is True else "BLOCKED" if h.get("allowed") is False else h.get("automation_policy","unknown")); return
        if field=="reason": print(h.get("blocking_reason") or h.get("reason") or "none"); return
        print(h.get(field,"unknown")); return
    print("unknown")
if __name__=="__main__": main()
