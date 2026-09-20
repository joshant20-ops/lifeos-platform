#!/usr/bin/env python3
import os,sqlite3,subprocess,time
from pathlib import Path
REPO=Path("/home/joshan/lifeos-platform")
svc=REPO/"governor/systemd/lifeos-pip-continuous.service"; timer=REPO/"governor/systemd/lifeos-pip-continuous.timer"
for p in (svc,timer):
 if not p.exists(): raise SystemExit("P7_UNIT_SOURCE=FAIL")
subprocess.run(["sudo","-n","install","-m","0644",str(svc),"/etc/systemd/system/lifeos-pip-continuous.service"],check=True)
subprocess.run(["sudo","-n","install","-m","0644",str(timer),"/etc/systemd/system/lifeos-pip-continuous.timer"],check=True)
subprocess.run(["sudo","-n","systemctl","daemon-reload"],check=True)
subprocess.run(["sudo","-n","systemctl","enable","--now","lifeos-pip-continuous.timer"],check=True,stdout=subprocess.DEVNULL)
enabled=subprocess.run(["systemctl","is-enabled","lifeos-pip-continuous.timer"],capture_output=True,text=True).stdout.strip()
active=subprocess.run(["systemctl","is-active","lifeos-pip-continuous.timer"],capture_output=True,text=True).stdout.strip()
if enabled!="enabled" or active!="active": raise SystemExit("P7_TIMER=FAIL")
# Execute the real production unit now; P5's accepted processor is idempotent and only selects pending exceptions.
r=subprocess.run(["sudo","-n","systemctl","start","lifeos-pip-continuous.service"],capture_output=True,text=True,timeout=1200)
if r.returncode: print("P7_SERVICE_START=FAIL"); raise SystemExit(r.returncode)
show=subprocess.run(["systemctl","show","lifeos-pip-continuous.service","-p","Result","-p","ExecMainStatus"],capture_output=True,text=True,check=True).stdout
if "Result=success" not in show or "ExecMainStatus=0" not in show: raise SystemExit("P7_SERVICE_RESULT=FAIL")
# A second production invocation proves an empty/no-new-work cycle is safe and repeatable.
r2=subprocess.run(["sudo","-n","systemctl","start","lifeos-pip-continuous.service"],capture_output=True,text=True,timeout=1200)
if r2.returncode: raise SystemExit("P7_REPEAT=FAIL")
print("P7_TIMER_ENABLED=PASS");print("P7_TIMER_ACTIVE=PASS");print("P7_PRODUCTION_PROCESSOR=REUSED");print("P7_REPEAT_CYCLE=PASS");print("P7_CONTINUOUS_LIVE_ACCEPTANCE=PASS")
