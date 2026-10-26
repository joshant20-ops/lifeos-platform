"""Restore only the original stopped Matter container required by HA."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.request
from governor.storage_recovery_audit import device

def command(args,timeout=20):
    return subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=True).stdout

def api(path,post=False):
    request=urllib.request.Request("http://127.0.0.1:8123"+path,headers={"Authorization":"Bearer "+os.environ["HA_TOKEN"]},data=b"{}" if post else None)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=10) as response:
        return json.load(response)

def matter_entry():
    rows=[r for r in api("/api/config/config_entries/entry") if r.get("domain")=="matter"]
    if len(rows)!=1 or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}",rows[0].get("entry_id","")):
        raise RuntimeError("ambiguous_matter_entry")
    return rows[0]

def original_container(row,baseline):
    cid=row.get("Id","")
    return bool(re.fullmatch(r"[0-9a-f]{64}",cid) and any(re.fullmatch(r"[0-9a-f]{12,64}",p) and cid.startswith(p) for p in baseline.split()))

def main():
    if os.geteuid()!=0 or os.uname().nodename!="Docker": return 64
    started=False
    try:
        marker=Path("/mnt/docker-data/recovery/sd-opt-stacks-20261017/.lifeos-preserved")
        if not marker.is_file() or device("/opt/stacks")!="SSD": raise RuntimeError("storage_precondition")
        row=json.loads(command(["docker","inspect","matter-server"]))[0]
        baseline=Path("/var/lib/lifeos-storage-migration/active-containers.before").read_text()
        if not original_container(row,baseline) or row.get("Name")!="/matter-server": raise RuntimeError("not_original_container")
        state=row.get("State",{}).get("Status")
        if state not in {"running","exited"}: raise RuntimeError("container_transition")
        if row.get("HostConfig",{}).get("NetworkMode")!="host": raise RuntimeError("network_mode_unexpected")
        mount=[m for m in row.get("Mounts",[]) if m.get("Destination")=="/data" and m.get("RW")]
        if len(mount)!=1 or mount[0].get("Source")!="/home/joshan/docker/matter-server/data" or not Path(mount[0]["Source"]).is_dir():
            raise RuntimeError("data_mount_unexpected")
        entry=matter_entry()
        if entry.get("state") not in {"loaded","setup_retry","setup_error"}: raise RuntimeError("integration_state_unexpected")
        if state=="exited":
            command(["docker","start","matter-server"],timeout=40);started=True
        ready=False
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1",5580),timeout=2): ready=True;break
            except OSError: time.sleep(2)
        if not ready: raise RuntimeError("matter_listener_not_ready")
        print("MATTER_ORIGINAL_CONTAINER_LISTENER=PASS")
        if matter_entry().get("state")!="loaded":
            api("/api/config/config_entries/entry/"+entry["entry_id"]+"/reload",post=True)
        loaded=False
        for _ in range(60):
            if matter_entry().get("state")=="loaded": loaded=True;break
            time.sleep(2)
        if not loaded: raise RuntimeError("ha_matter_not_loaded")
        print("MATTER_HA_INTEGRATION=LOADED")
        print("MATTER_RECOVERY_MUTATIONS=ORIGINAL_CONTAINER_START_AND_OWN_HA_INTEGRATION_RELOAD_ONLY")
        print("MATTER_RECOVERY=PASS")
        return 0
    except Exception as error:
        if started:
            try: command(["docker","stop","--time","30","matter-server"],timeout=45);print("MATTER_ROLLBACK=PRIOR_STOPPED_STATE")
            except Exception: print("MATTER_ROLLBACK=FAILED")
        print("MATTER_RECOVERY=FAIL_"+type(error).__name__)
        return 1
if __name__=="__main__":raise SystemExit(main())
