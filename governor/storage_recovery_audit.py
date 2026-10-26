"""Fixed read-only storage recovery evidence; never emits config/env contents."""
import json
import os
from pathlib import Path
import re
import subprocess

SSD = "a53fd6a0-c498-4b76-a496-0e5d9233447f"
SD = "e20b40e9-a03b-4e15-b170-f527cf96d5e5"
def run(args, timeout=8):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""

def device(path):
    raw = run(["findmnt", "-n", "-o", "UUID,FSTYPE", "-T", str(path)]).split()
    if not raw: return "UNKNOWN"
    if SSD in raw: return "SSD"
    if SD in raw: return "SD_ROOT"
    if any(v in {"nfs", "nfs4", "cifs"} for v in raw): return "NAS"
    return "OTHER"

def safe_name(raw):
    return raw.lstrip("/") if re.fullmatch(r"/?[A-Za-z0-9_.-]{1,100}", raw) else "UNRECOGNIZED"

def main():
    if os.geteuid() != 0 or os.uname().nodename != "Docker": raise SystemExit(64)
    ids = run(["docker", "ps", "-aq"]).split()
    rows = json.loads(run(["docker", "inspect", *ids]) or "[]") if ids else []
    current = {r["Id"]:r for r in rows}
    for row in rows:
        name = safe_name(row.get("Name", ""))
        data = {"name":name, "state":row.get("State",{}).get("Status"), "created":row.get("Created"), "restart_policy":row.get("HostConfig",{}).get("RestartPolicy",{}).get("Name")}
        data["writable_mounts"] = [{"target":m.get("Destination"), "device":device(m.get("Source",""))} for m in row.get("Mounts",[]) if m.get("RW") and m.get("Type") in {"bind","volume"}]
        print("RECOVERY_CONTAINER="+json.dumps(data, separators=(",",":")))
    baseline = Path("/var/lib/lifeos-storage-migration/active-containers.before")
    old = baseline.read_text().split() if baseline.is_file() and baseline.stat().st_size<65536 else []
    roots = [Path("/mnt/docker-data/containers"), Path("/var/lib/docker/containers"), Path("/mnt/docker-data/docker/containers")]
    for index, prefix in enumerate(old,1):
        if not re.fullmatch(r"[0-9a-f]{12,64}",prefix): continue
        matches = [r for cid,r in current.items() if cid.startswith(prefix)]
        record = {"entry":index,"matched":len(matches)==1}
        if len(matches)==1:
            record.update(name=safe_name(matches[0]["Name"]),state=matches[0]["State"]["Status"])
        else:
            recovered = set()
            for root in roots:
                if not root.is_dir(): continue
                for item in list(root.glob(prefix+"*"))[:10]:
                    config = item/"config.v2.json"
                    try:
                        if config.is_symlink() or config.stat().st_size>1048576: continue
                        recovered.add(safe_name(json.loads(config.read_text()).get("Name","")))
                    except (OSError,ValueError): pass
            record["retained_metadata_names"]=sorted(recovered)
        print("RECOVERY_BASELINE="+json.dumps(record,separators=(",",":")))
    marker = Path("/mnt/docker-data/recovery/sd-opt-stacks-20261017/.lifeos-preserved")
    print("RECOVERY_SD_COPY="+("VERIFIED_MARKER_PRESENT" if marker.is_file() and not marker.is_symlink() else "NOT_YET_VERIFIED"))
    for unit in ["docker.service","opt-stacks.mount","mnt-docker\\x2ddata.mount"]:
        text = run(["systemctl","show",unit,"-p","ActiveState","-p","Requires","-p","BindsTo","-p","After"])
        print("RECOVERY_BOOT_UNIT="+json.dumps({"unit":unit,"properties":text.strip().splitlines()},separators=(",",":")))
    print("RECOVERY_DIAGNOSTIC_MUTATIONS=NONE")
if __name__ == "__main__": main()
