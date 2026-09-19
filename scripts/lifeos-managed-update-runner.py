#!/usr/bin/env python3
"""Runtime coordinator for the existing managed-component update pipeline.
Discovery/execution are delegated to the protected gateway; this coordinator
owns policy gating and fail-closed sequencing only."""
from __future__ import annotations
import argparse,json,pathlib,subprocess,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"engineer"))
import managed_updates as mu
GATEWAY="/usr/local/sbin/lifeos-deploy-gateway"
def call(op):
 r=subprocess.run(["sudo","-n",GATEWAY,op],text=True,capture_output=True,timeout=900)
 print(r.stdout,end="")
 if r.returncode: raise SystemExit(r.returncode)
 return r.stdout
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--target",choices=("predbat","home-assistant-core"),required=True);a=ap.parse_args()
 # Protected observation command emits sanitised contract JSON only.
 raw=call("managed-update-observe-"+a.target)
 marker="MANAGED_UPDATE_OBSERVATION="
 line=next((x for x in raw.splitlines() if x.startswith(marker)),None)
 if not line: raise SystemExit("sanitised observation missing")
 obs=json.loads(line[len(marker):])
 policy=mu.load_policy(ROOT/"engineer/managed_updates.json")
 packet=mu.build_packet(policy,obs)
 print("MANAGED_UPDATE_DECISION="+("DEPLOY" if packet["automatic_deploy_allowed"] else "HOLD"))
 if not packet["automatic_deploy_allowed"]: return 0
 call("managed-update-apply-"+a.target)
 print("MANAGED_UPDATE_PIPELINE=PASS")
if __name__=="__main__":main()
