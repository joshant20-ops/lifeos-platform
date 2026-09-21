#!/usr/bin/env python3
"""Sanitised 24h Tower lifecycle proof from controller journal."""
import re, subprocess, time
cp=subprocess.run(["journalctl","-u","lifeos-tower-control.service","--since","24 hours ago","--no-pager","-o","short-unix"],text=True,capture_output=True,check=True)
events=[]; wake=shutdown=0
for line in cp.stdout.splitlines():
    m=re.match(r"^(\d+(?:\.\d+)?)\s+.*?TOWER_STATE=([A-Z_]+).*?ACCESSIBLE=(YES|NO)",line)
    if m: events.append((float(m.group(1)),m.group(2),m.group(3)=="YES"))
    if "TOWER_COMPUTE_WAKE=REQUESTED" in line: wake+=1
    if "TOWER_COMPUTE_SHUTDOWN=REQUESTED" in line: shutdown+=1
now=time.time(); start=now-86400
events=[e for e in events if start <= e[0] <= now+60]
dur={"ACCESSIBLE":0.0,"INACCESSIBLE":0.0}; transitions=0
if events:
    prev_t=start; prev=events[0][2]
    for t,_,accessible in events:
        dur["ACCESSIBLE" if prev else "INACCESSIBLE"]+=max(0,min(t,now)-prev_t)
        if accessible!=prev: transitions+=1
        prev_t=min(t,now); prev=accessible
    dur["ACCESSIBLE" if prev else "INACCESSIBLE"]+=max(0,now-prev_t)
covered=sum(dur.values()); valid=bool(events) and 0 < covered <= 86520
print(f"TOWER_24H_SAMPLES={len(events)}")
print(f"TOWER_24H_COVERAGE_MINUTES={covered/60:.1f}")
print(f"TOWER_24H_ACCESSIBLE_MINUTES={dur['ACCESSIBLE']/60:.1f}")
print(f"TOWER_24H_INACCESSIBLE_MINUTES={dur['INACCESSIBLE']/60:.1f}")
print(f"TOWER_24H_ACCESS_TRANSITIONS={transitions}")
print(f"TOWER_24H_LIFEOS_WAKE_REQUESTS={wake}")
print(f"TOWER_24H_LIFEOS_SHUTDOWN_REQUESTS={shutdown}")
print("TOWER_24H_RAW_PRIVATE_DATA_EMITTED=NONE")
print("RESULT="+("PASS" if valid else "FAIL"))
raise SystemExit(0 if valid else 1)
