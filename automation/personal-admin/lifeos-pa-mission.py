#!/usr/bin/env python3
"""Cheap/resumable supervisor for Personal Administration + Autonomy.

Deterministic work stays on the Pi. Private Personal Administration work is
submitted to the existing Governor, which owns AI routing, Tower lifecycle,
verification and governed mutation. Faults are grouped for one Work repair pass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

VERSION = "2026.09.08-2"
REPO = pathlib.Path(os.getenv("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform"))
STATE = pathlib.Path(os.getenv("LIFEOS_PA_MISSION_STATE", str(pathlib.Path.home()/".local/state/lifeos-pa-autonomy")))
GOV = os.getenv("LIFEOS_GOVERNOR_URL", "http://127.0.0.1:8790").rstrip("/")
POLL = int(os.getenv("LIFEOS_PA_POLL_SECONDS", "15"))
MAX_POLL = int(os.getenv("LIFEOS_PA_MAX_POLL_SECONDS", "1800"))
MAX_RETRIES = int(os.getenv("LIFEOS_PA_MAX_JOB_RETRIES", "3"))
STATE_FILE = STATE/"state.json"
AUDIT_FILE = STATE/"audit.json"
BUNDLE_FILE = STATE/"WORK_BUNDLE.md"
LOCK_FILE = STATE/"runner.lock"
TERMINAL = {"PASS","BLOCKED","FAILED","ERROR","CANCELLED","SUPERSEDED"}
HARD = {"REPO_MISSING","REPO_DIRTY","REPO_DRIFT","GOVERNOR_DOWN","GOVERNOR_API_DOWN","PRIVACY_ROUTING_DEFECT"}


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def run(argv, cwd=None, timeout=30):
    try:
        p = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
        return {"rc": p.returncode, "out": (p.stdout or "").strip(), "err": (p.stderr or "").strip()}
    except FileNotFoundError:
        return {"rc":127,"out":"","err":"command_not_found"}
    except subprocess.TimeoutExpired:
        return {"rc":124,"out":"","err":"timeout"}
    except Exception as exc:
        return {"rc":125,"out":"","err":type(exc).__name__}


def http(method, url, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept":"application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(2_000_000)
            return r.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(100_000) or b"{}")
        except Exception:
            return exc.code, {"error":"http_error"}
    except Exception as exc:
        return 0, {"error":type(exc).__name__}


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_state():
    try:
        v = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except Exception:
        return {"schema":1,"version":VERSION,"phase":"new","job":{},"retry_count":0,"history":[],"created_at":now()}


def save_state(s):
    s["version"] = VERSION
    s["updated_at"] = now()
    write(STATE_FILE, json.dumps(s, indent=2, sort_keys=True)+"\n")


def fault(fs, root, severity, component, problem, evidence, action, human=False):
    text = evidence if isinstance(evidence, str) else json.dumps(evidence, sort_keys=True)
    text = re.sub(r"(?i)(token|password|secret|authorization)[=:]\S+", r"\1=[redacted]", text)
    fs.append({"root":root,"severity":severity,"component":component,"problem":problem,
               "evidence":text[:1200],"action":action,"human":bool(human)})


def audit(fs):
    out = {"generated_at":now(),"version":VERSION}
    mem_kib = 0
    try:
        for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_kib = int(line.split()[1]); break
    except Exception:
        pass
    disk = shutil.disk_usage(str(REPO if REPO.exists() else pathlib.Path.home()))
    out["host"] = {"hostname":socket.gethostname(),"architecture":platform.machine(),
                   "kernel":platform.release(),"cpu_count":os.cpu_count(),
                   "memory_gib":round(mem_kib/1048576,2),"disk_free_gib":round(disk.free/1073741824,2)}
    if platform.machine() not in {"aarch64","arm64"}:
        fault(fs,"HOST_ROLE_MISMATCH","warning","pi5","Runner is not on expected ARM64 control plane.",out["host"],"Run on the LifeOS Pi 5.")
    if out["host"]["disk_free_gib"] < 2:
        fault(fs,"RESOURCE_PRESSURE","high","pi5","Less than 2 GiB free on control plane.",out["host"],"Free space through existing retention paths; do not delete unknown data.")

    if not (REPO/".git").is_dir():
        out["repo"]={"exists":False}
        fault(fs,"REPO_MISSING","critical","repository","Canonical checkout missing.",str(REPO),"Restore/locate canonical checkout; do not create a second source of truth.")
    else:
        st=run(["git","status","--porcelain","--untracked-files=all"],REPO)
        head=run(["git","rev-parse","HEAD"],REPO)
        fetch=run(["git","fetch","--prune","origin","main"],REPO,90)
        origin=run(["git","rev-parse","origin/main"],REPO)
        dirty=bool(st["out"]); aligned=bool(head["out"]) and head["out"]==origin["out"]
        out["repo"]={"exists":True,"head":head["out"],"origin_main":origin["out"],"dirty":dirty,"aligned":aligned,"fetch_rc":fetch["rc"]}
        if dirty:
            fault(fs,"REPO_DIRTY","critical","repository","Canonical checkout has local changes; runner will not clean/reset it.",{"dirty":True},"Preserve and reconcile bytes safely; never reset --hard or git clean.")
        if fetch["rc"]!=0:
            fault(fs,"GITHUB_SYNC","high","repository","Could not refresh origin/main.",{"rc":fetch["rc"],"err":fetch["err"][:250]},"Repair GitHub/network authentication then rerun.")
        elif not aligned:
            fault(fs,"REPO_DRIFT","critical","repository","Pi HEAD differs from origin/main.",{"head":head["out"],"origin":origin["out"]},"Safely fast-forward only after proving the worktree clean.")

    ps=run(["docker","ps","--format","{{json .Names}}\t{{json .Image}}\t{{json .Status}}"],timeout=20)
    containers=[]
    if ps["rc"]!=0:
        fault(fs,"DOCKER_DOWN","high","runtime","Docker inventory failed.",{"rc":ps["rc"],"err":ps["err"][:250]},"Repair existing Docker service/access once, then rerun.")
    else:
        for line in ps["out"].splitlines():
            try:
                a,b,c=line.split("\t",2); containers.append({"name":json.loads(a),"image":json.loads(b),"status":json.loads(c)})
            except Exception:
                pass
    names=" ".join((x["name"]+" "+x["image"]).lower() for x in containers)
    out["docker"]={"count":len(containers),"containers":containers,
                   "homeassistant":("homeassistant" in names or "home-assistant" in names),
                   "paperless":("paperless" in names),"mosquitto":("mosquitto" in names)}
    if containers and not out["docker"]["homeassistant"]:
        fault(fs,"HA_DOWN","high","homeassistant","Existing Home Assistant container not found.",{},"Restore existing HA; do not deploy a second HA.")
    if containers and not out["docker"]["paperless"]:
        fault(fs,"PAPERLESS_DOWN","high","documents","Existing Paperless container not found.",{},"Restore/reuse existing Paperless; do not create duplicate document storage.")

    active=run(["systemctl","is-active","lifeos-autonomous-agent.service"],timeout=10)
    out["governor_service"]={"active":active["out"]=="active","state":active["out"]}
    if active["out"]!="active":
        fault(fs,"GOVERNOR_DOWN","critical","governor","lifeos-autonomous-agent.service is not active.",out["governor_service"],"Repair existing Governor through governed deployment/service paths.")
    code,h=http("GET",GOV+"/health")
    out["governor"]={"health_code":code,"health":h}
    if code!=200 or not isinstance(h,dict) or h.get("status")!="ok":
        fault(fs,"GOVERNOR_API_DOWN","critical","governor","Governor health endpoint unavailable/unhealthy.",{"code":code,"response":h},"Repair existing Governor API and rerun.")
    else:
        sc,stuck=http("GET",GOV+"/jobs/stuck")
        jobs=stuck.get("stuck_jobs",[]) if sc==200 and isinstance(stuck,dict) else []
        out["governor"]["stuck_jobs"]=[{k:j.get(k) for k in ("id","status","stage","stage_age_seconds")} for j in jobs[:20]]
        if jobs:
            fault(fs,"GOVERNOR_STUCK_JOBS","high","governor","One or more stuck jobs share an autonomy/infrastructure repair batch.",out["governor"]["stuck_jobs"],"Diagnose common causes and repair together; do not retry each symptom separately.")

    out["acceptance"]={
        "AC1_INSPECT_EXISTING":"PROVEN" if out.get("repo",{}).get("exists") and ps["rc"]==0 else "PARTIAL",
        "AC2_SHARED_CONTRACT":"UNKNOWN","AC3_CALENDAR_CONTEXT":"UNKNOWN","AC4_EMAIL_OBLIGATION":"UNKNOWN",
        "AC5_PAPERLESS_EVIDENCE":"PARTIAL" if out["docker"]["paperless"] else "UNKNOWN",
        "AC6_PRIVATE_E2E":"UNKNOWN","AC7_PRIVACY_LOCAL_ONLY":"PARTIAL" if code==200 else "UNKNOWN",
        "AC8_TEST_DEPLOY_REGRESS":"PARTIAL" if out.get("repo",{}).get("aligned") and not out.get("repo",{}).get("dirty") else "BLOCKED",
        "AC9_NO_EXTRA_SERVICE":"UNKNOWN","AC10_RECORD_AFTER_PROOF":"NOT_STARTED"}
    write(AUDIT_FILE,json.dumps(out,indent=2,sort_keys=True)+"\n")
    return out


def mission(a):
    return f"""LifeOS Personal Administration delivery — canonical issue #164.

PRIMARY OUTCOME
Calendar + Email + Paperless -> shared event/obligation/action/evidence -> existing PA attention surface.

PARALLEL AUTONOMY OUTCOME
Use this real workload to improve Intelligence & Autonomy only where a defect blocks useful Personal Administration progress. OpenHands, a provider, Tower AI, dashboards and Governor perfection are implementation mechanisms, not objectives.

DETERMINISTIC PREFLIGHT
repo_clean_aligned={a.get('repo',{}).get('aligned') and not a.get('repo',{}).get('dirty')}
governor_health={a.get('governor',{}).get('health_code')}
paperless_present={a.get('docker',{}).get('paperless')}
homeassistant_present={a.get('docker',{}).get('homeassistant')}

RULES
Inspect live implementation before mutation; runtime outranks stale issue text. OTS/native first. Reuse Calendar, Email, Paperless and the existing PA surface; do not create duplicate systems of record. This is private/local-only: never send personal email/calendar/document content to cloud AI, GitHub, or external logs. Use small resumable milestones. Recover/reroute ordinary worker/provider failures. Never bypass Watchman/root/transaction/recovery controls. Never reset/clean the canonical checkout. Continue without routine user approval; stop only at a genuine external human boundary.

ACCEPTANCE
1 inspect existing Calendar/Email/Paperless before mutation;
2 reuse/implement one shared event/obligation/action/evidence contract;
3 Calendar contributes PA context without duplicating authority;
4 Email can create an actionable obligation/follow-up and link evidence;
5 Paperless remains authoritative while obligations/actions link to evidence;
6 one local private E2E case crosses at least two source systems and reaches PA attention;
7 private routing is live-proven local-only with cloud fallback blocked;
8 focused tests, governed deployment/runtime proof, regression and clean canonical repo pass;
9 no unjustified always-on service;
10 canonical evidence/roadmap updated only after live proof.

FINAL STATUS MUST EXPLICITLY REPORT
PERSONAL_ADMINISTRATION=COMPLETE|INCOMPLETE
AUTONOMY_PROGRESS=PASS|INCOMPLETE
PRIVACY_PROOF=PASS|INCOMPLETE
RUNTIME_PROOF=PASS|INCOMPLETE
REGRESSION=PASS|INCOMPLETE
"""


def job_step(s,a,fs,mode):
    if {x["root"] for x in fs} & HARD:
        s["phase"]="preflight_blocked"; return
    j=s.setdefault("job",{}); jid=j.get("id")
    if jid:
        code,cur=http("GET",GOV+"/jobs/"+jid)
        if code!=200 or not isinstance(cur,dict):
            fault(fs,"JOB_STATE_LOST","high","autonomy","Persisted mission job cannot be read.",{"job":jid,"code":code},"Recover/reconcile Governor job state; do not blindly submit duplicate work."); s["phase"]="job_unknown"; return
        for k in ("id","status","stage","privacy","stage_detail","completed_at","blocked_reason"):
            j[k]=cur.get(k)
        status=str(cur.get("status","")).upper()
        if status=="PASS": s["phase"]="job_passed"; return
        if status not in TERMINAL: s["phase"]="job_running"; return
        if mode=="resume" and int(s.get("retry_count",0))<MAX_RETRIES:
            rc,n=http("POST",GOV+f"/jobs/{jid}/retry",{})
            if rc==202 and isinstance(n,dict) and n.get("id"):
                s.setdefault("history",[]).append({"job_id":jid,"status":status,"at":now()})
                s["job"]={k:n.get(k) for k in ("id","status","stage","privacy")}; s["retry_count"]=int(s.get("retry_count",0))+1; s["phase"]="job_retried"; return
            fault(fs,"RETRY_FAILED","high","autonomy","Consolidated Governor retry failed.",{"code":rc,"response":n},"Repair bundled root causes before another retry."); return
        fault(fs,"MISSION_BLOCKED","high","autonomy","Mission reached terminal non-PASS state.",{"job":jid,"status":status,"stage":cur.get("stage"),"blocked_reason":cur.get("blocked_reason"),"repeat":cur.get("repeated_failure_count")},"Inspect this single job's evidence, fix shared/root causes together, then run resume."); s["phase"]="job_blocked"; return

    code,n=http("POST",GOV+"/jobs?async=1",{"request":mission(a),"privacy_domain":"personal-administration","continuation_enabled":False},20)
    if code==202 and isinstance(n,dict) and n.get("id"):
        s["job"]={k:n.get(k) for k in ("id","status","stage","privacy","created_at")}; s["phase"]="job_submitted"
        if n.get("privacy")!="local-only":
            fault(fs,"PRIVACY_ROUTING_DEFECT","critical","privacy","Private PA mission did not classify local-only.",{"job":n.get("id"),"privacy":n.get("privacy")},"Stop private execution and repair privacy routing before continuing.")
    else:
        fault(fs,"SUBMISSION_FAILED","critical","autonomy","Could not submit the single governed mission.",{"code":code,"response":n},"Repair Governor ingress; do not create a parallel manual execution path."); s["phase"]="submission_failed"


def poll_job(s,fs):
    jid=s.get("job",{}).get("id")
    if not jid: return
    end=time.monotonic()+MAX_POLL; last=None
    while time.monotonic()<end:
        code,c=http("GET",GOV+"/jobs/"+jid)
        if code!=200 or not isinstance(c,dict):
            fault(fs,"POLL_FAILED","high","autonomy","Mission status became unreadable.",{"job":jid,"code":code},"Repair status path while preserving the existing job ID."); return
        for k in ("status","stage","privacy","stage_detail","blocked_reason","completed_at"):
            s["job"][k]=c.get(k)
        save_state(s)
        if c.get("stage")!=last:
            print(f"JOB={jid} STATUS={c.get('status')} STAGE={c.get('stage')} DETAIL={str(c.get('stage_detail') or '')[:180]}",flush=True); last=c.get("stage")
        status=str(c.get("status","")).upper()
        if status in TERMINAL:
            if status=="PASS": s["phase"]="job_passed"
            else:
                fault(fs,"MISSION_BLOCKED","high","autonomy","Mission reached terminal non-PASS state.",{"job":jid,"status":status,"stage":c.get("stage"),"blocked_reason":c.get("blocked_reason"),"repeat":c.get("repeated_failure_count")},"Batch common faults, repair together, then run resume."); s["phase"]="job_blocked"
            return
        time.sleep(POLL)
    s["phase"]="job_running"


def render(fs,s):
    rank={"warning":1,"medium":2,"high":3,"critical":4}; grouped={}
    for x in fs:
        g=grouped.setdefault(x["root"],{"root":x["root"],"severity":x["severity"],"human":False,"items":[]}); g["items"].append(x); g["human"]|=x["human"]
        if rank.get(x["severity"],0)>rank.get(g["severity"],0): g["severity"]=x["severity"]
    groups=sorted(grouped.values(),key=lambda x:(rank.get(x["severity"],0),len(x["items"])),reverse=True)
    lines=["# LifeOS Personal Administration — consolidated Work bundle","",f"Phase: `{s.get('phase')}`",f"Governor job: `{s.get('job',{}).get('id','none')}`","","Treat this as ONE repair batch. Diagnose shared root causes first, fix as many groups as safely possible in one branch/PR/deployment cycle, independently verify, then run `lifeos-pa-mission resume`. Do not retry each symptom separately. Do not expose private Calendar/Email/Paperless content. Never reset/clean the canonical checkout. Escalate only a genuine human boundary.",""]
    if not groups: lines += ["## Faults","","No bundled technical faults detected.",""]
    for i,g in enumerate(groups,1):
        lines += [f"## {i}. {g['root']} — {g['severity'].upper()}",f"Human boundary: `{str(g['human']).lower()}`",""]
        for x in g["items"]:
            lines += [f"- **{x['component']}**: {x['problem']}",f"  - Evidence: `{x['evidence'][:800]}`",f"  - Action: {x['action']}"]
        lines.append("")
    write(BUNDLE_FILE,"\n".join(lines)+"\n")
    return groups


def acquire_lock():
    STATE.mkdir(parents=True,exist_ok=True); os.chmod(STATE,0o700)
    try:
        fd=os.open(LOCK_FILE,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.write(fd,str(os.getpid()).encode()); os.close(fd)
    except FileExistsError:
        try:
            pid=int(LOCK_FILE.read_text()); os.kill(pid,0); raise SystemExit(f"RUNNER_ALREADY_ACTIVE pid={pid}")
        except ProcessLookupError:
            LOCK_FILE.unlink(missing_ok=True); acquire_lock()
        except (ValueError,OSError):
            LOCK_FILE.unlink(missing_ok=True); acquire_lock()


def status(s):
    j=s.get("job",{})
    print(f"RUNNER_VERSION={VERSION}\nMISSION_PHASE={s.get('phase','unknown')}\nJOB_ID={j.get('id','none')}\nJOB_STATUS={j.get('status','none')}\nJOB_STAGE={j.get('stage','none')}\nJOB_PRIVACY={j.get('privacy','unknown')}\nRETRY_COUNT={s.get('retry_count',0)}\nSTATE_DIR={STATE}\nWORK_BUNDLE={BUNDLE_FILE}")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("mode",nargs="?",choices=("run","resume","audit","status"),default="run"); args=ap.parse_args()
    STATE.mkdir(parents=True,exist_ok=True); os.chmod(STATE,0o700)
    if args.mode=="status":
        s=load_state(); jid=s.get("job",{}).get("id")
        if jid:
            c,j=http("GET",GOV+"/jobs/"+jid)
            if c==200 and isinstance(j,dict):
                for k in ("status","stage","privacy","stage_detail","blocked_reason"): s["job"][k]=j.get(k)
                save_state(s)
        status(s); return 0
    acquire_lock()
    try:
        s=load_state(); fs=[]; print("STAGE=deterministic_audit",flush=True); a=audit(fs)
        if args.mode!="audit":
            print("STAGE=governor_handoff",flush=True); job_step(s,a,fs,args.mode); save_state(s)
            if s.get("phase") in {"job_submitted","job_retried","job_running"}: poll_job(s,fs); save_state(s)
            if s.get("phase") in {"job_passed","job_blocked"}: print("STAGE=post_job_audit",flush=True); post=[]; audit(post); fs.extend(post)
        groups=render(fs,s); save_state(s); status(s)
        if s.get("phase")=="job_passed" and not groups: print("RESULT=PASS"); return 0
        if any(g["human"] for g in groups): print("RESULT=HUMAN_BOUNDARY"); return 30
        if any(g["root"] in HARD for g in groups): print("RESULT=SAFE_STOP"); return 40
        if groups or s.get("phase") in {"preflight_blocked","job_blocked","submission_failed"}: print("RESULT=WORK_BUNDLE_READY"); return 20
        print("RESULT=PROGRESS"); return 0
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__=="__main__":
    raise SystemExit(main())
