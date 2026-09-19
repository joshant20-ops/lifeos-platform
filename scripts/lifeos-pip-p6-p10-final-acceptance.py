#!/usr/bin/env python3
"""Sequential P6-P10 final acceptance gate. Stops on first failed gate."""
from __future__ import annotations
import argparse, pathlib, subprocess, sys
REPO=pathlib.Path("/home/joshan/lifeos-platform")
GATES={
 "p6":[sys.executable,str(REPO/"scripts/lifeos-pip-p6-real-acceptance.py")],
 "p7":[sys.executable,str(REPO/"tests/test_pip_p6_p10_functional.py"),"P7"],
 "p8":[sys.executable,str(REPO/"tests/test_pip_p6_p10_functional.py"),"P8"],
 "p9":[sys.executable,str(REPO/"tests/test_pip_p6_p10_functional.py"),"P9"],
 "p10":[sys.executable,str(REPO/"tests/test_pip_p6_p10_functional.py"),"P10"],
}
def run(g):
 print(f"{g.upper()}_FINAL_GATE=START")
 r=subprocess.run(GATES[g],cwd=REPO,timeout=1200)
 if r.returncode:
  print(f"{g.upper()}_FINAL_GATE=FAIL"); raise SystemExit(r.returncode)
 print(f"{g.upper()}_FINAL_GATE=PASS")
def main():
 p=argparse.ArgumentParser();p.add_argument("--from-gate",choices=GATES,default="p6");a=p.parse_args()
 names=list(GATES); start=names.index(a.from_gate)
 for g in names[start:]: run(g)
 print("P6_P10_GATED_ACCEPTANCE=PASS")
if __name__=="__main__":main()
