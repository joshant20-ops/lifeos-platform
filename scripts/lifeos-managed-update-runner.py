#!/usr/bin/env python3
"""Runtime coordinator for the existing managed-component update pipeline.
Discovery/execution are delegated to the protected gateway; this coordinator
owns policy gating and fail-closed sequencing only."""
from __future__ import annotations
import argparse,json,pathlib,re,subprocess,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"engineer"))
import managed_updates as mu
GATEWAY="/usr/local/sbin/lifeos-deploy-gateway"\nDIGEST_RE=re.compile(r"^sha256:[0-9a-f]{64}$")
def call(op):
 r=subprocess.run(["sudo","-n",GATEWAY,op],text=True,capture_output=True,timeout=900)
 print(r.stdout,end="")
 if r.returncode: raise SystemExit(r.returncode)
 return r.stdout
def reconcile_predbat_desired(digest):
 if not DIGEST_RE.match(digest): raise SystemExit("accepted digest invalid")
 path=ROOT/"ansible/desired/compose/predbat/docker-compose.yml"
 text=path.read_text()
 new,n=re.subn(r"(?m)^(\\s*image:\\s*nipar44/predbat_addon)(?:@sha256:[0-9a-f]{64}|:[^\\s]+)$",r"\\1@"+digest,text,count=1)
 if n != 1: raise SystemExit("canonical Predbat image declaration missing or ambiguous")
 if new != text:
  path.write_text(new)
  subprocess.run(["git","add","--",str(path.relative_to(ROOT))],cwd=ROOT,check=True,timeout=30)
  subprocess.run(["git","commit","-m",f"Reconcile Predbat desired digest to {digest[:19]}"],cwd=ROOT,check=True,timeout=30)
  subprocess.run(["git","push","origin","HEAD:main"],cwd=ROOT,check=True,timeout=120)
 subprocess.run(["git","fetch","origin","main"],cwd=ROOT,check=True,timeout=120)
 head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
 origin=subprocess.check_output(["git","rev-parse","origin/main"],cwd=ROOT,text=True).strip()
 if head != origin or subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True).strip():
  raise SystemExit("canonical reconciliation postcondition failed")
 print("MANAGED_UPDATE_CANONICAL_DIGEST="+digest)
 print("MANAGED_UPDATE_CANONICAL_RECONCILE=PASS")

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
