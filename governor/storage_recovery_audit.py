"""Fixed read-only storage recovery evidence; never emits config/env contents."""
import json
import os
from pathlib import Path
import re
import subprocess
import sqlite3

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


def smart_diagnostics():
    """Read native service/configuration evidence; no device commands or mutations."""
    props = run(["systemctl", "show", "smartmontools.service",
                 "-p", "ActiveState", "-p", "SubState", "-p", "Result",
                 "-p", "ExecMainCode", "-p", "ExecMainStatus",
                 "-p", "Type", "-p", "TimeoutStartUSec", "-p", "LimitNOFILE",
                 "-p", "LimitNOFILESoft", "-p", "CPUUsageNSec"])
    print("SMART_SERVICE=" + json.dumps(dict(
        line.split("=", 1) for line in props.splitlines() if "=" in line)))
    journal = run(["journalctl", "-u", "smartmontools.service", "-b",
                   "--no-pager", "-n", "100", "-o", "cat"])
    categories = {
        "UNKNOWN_USB_BRIDGE": r"Unknown USB bridge",
        "DEVICE_TYPE_REQUIRED": r"specify device type|device type with the -d",
        "NO_DEVICES": r"No devices to monitor|Unable to register device",
        "DEVICE_OPEN_FAILED": r"Unable to open device|open device.*failed",
        "CONFIG_ERROR": r"configuration.*error|syntax error|Invalid directive",
        "SMART_UNSUPPORTED": r"does not support SMART|SMART support is.*Unavailable",
        "HEALTH_FAILURE": r"SMART (?:overall-health self-assessment test result|Health Status):\\s*(?:FAILED|BAD)|FAILURE PREDICTION THRESHOLD EXCEEDED",
        "START_TIMEOUT": r"start operation timed out",
        "REGISTERED_DEVICE": r"Device:.*registered",
        "MONITORING_DEVICE": r"Monitoring [0-9]+ .*devices",
        "OPENED_DEVICE": r"Device:.*opened",
        "READ_CONFIG": r"Opened configuration file|Configuration file.*parsed",
        "NVME_DETECTED": r"\\[.*NVMe.*\\]|type.*sntjmicron",
        "ATA_DETECTED": r"\\[SAT\\]|type.*sat\\b",
        "DRIVE_INFO": r"Device:.*(Model|Serial|Firmware)",
    }
    print("SMART_LOG_CATEGORIES=" + json.dumps({
        key: len(re.findall(pattern, journal, re.I))
        for key, pattern in categories.items()}))
    version = run(["dpkg-query", "-W", "-f=${Version}", "smartmontools"]).strip()
    print("SMART_PACKAGE_VERSION=" + (version if re.fullmatch(r"[0-9A-Za-z.+:~_-]{1,80}", version) else "UNKNOWN"))

    events = []
    vocabulary = set(("smartd Device opened Opened configuration file parsed scanning ATA SCSI NVMe SAT "
                      "USB JMicron sntjmicron sat scsi removable type devices monitor Monitoring "
                      "DeviceScan Read read Identify Controller failed error unsupported field command "
                      "start operation timed out Terminating Successfully terminated "
                      "SMART support available unavailable enabled disabled "
                      "Power mode standby sleep check failed LOG SENSE INQUIRY "
                      "Adding device list IEC CHECK POWER MODE "
                      "systemd notify notification ready READY exiting exit status timeout").lower().split())
    for line in journal.splitlines():
        # Only publish words from a fixed native diagnostic vocabulary.
        tokens = re.findall(r"[A-Za-z]+", line.lower())
        events.append(" ".join(token for token in tokens if token in vocabulary))
    print("SMART_EVENT_VOCABULARY=" + json.dumps(events))
    kernel = run(["journalctl", "-k", "-b", "--no-pager", "-n", "2000", "-o", "cat"])
    faults = {
        "USB_RESET": r"reset .*USB device",
        "UAS_ABORT": r"uas_eh_abort_handler|uas_eh_device_reset_handler",
        "SCSI_TIMEOUT": r"timing out command|command.*timed out|DID_TIME_OUT",
        "BLOCK_IO_ERROR": r"I/O error.*sda|sda.*I/O error",
        "FILESYSTEM_ERROR": r"EXT4-fs error|Remounting filesystem read-only",
    }
    print("SMART_BOOT_KERNEL_CATEGORIES=" + json.dumps({
        key:len(re.findall(pattern,kernel,re.I)) for key,pattern in faults.items()}))
    for prop in ("vendor", "model", "rev"):
        try:
            value = (Path("/sys/block/sda/device") / prop).read_text().strip()
            # Generic product identity only: never publish serials/WWNs.
            print("SMART_SCSI_" + prop.upper() + "=" +
                  (value if re.fullmatch(r"[A-Za-z0-9 ._-]{1,40}",value) else "REDACTED"))
        except OSError: pass
    config = Path("/etc/smartd.conf")
    try:
        if config.is_symlink() or config.stat().st_size > 65536:
            raise ValueError("unsafe config")
        lines = [line.split("#", 1)[0].strip()
                 for line in config.read_text().splitlines()]
        lines = [line for line in lines if line]
        records = []
        for line in lines:
            parts = line.split()
            record = {"scan": parts[0] == "DEVICESCAN",
                      "ssd_device": parts[0] == "/dev/sda",
                      "other_device": parts[0] not in {"DEVICESCAN", "/dev/sda"}}
            for flag in ("-d", "-n"):
                if flag in parts and parts.index(flag) + 1 < len(parts):
                    value = parts[parts.index(flag) + 1]
                    record[flag] = value if re.fullmatch(r"[a-zA-Z0-9,+-]{1,40}", value) else "REDACTED"
            record["scheduled_self_test"] = "-s" in parts
            records.append(record)
        print("SMART_CONFIG_RULES=" + json.dumps(records))
    except (OSError, ValueError):
        print("SMART_CONFIG_RULES=UNAVAILABLE")
    block = run(["lsblk", "-dn", "-o", "NAME,TRAN,TYPE"])
    print("SMART_BLOCK_TOPOLOGY=" + json.dumps([
        line.split() for line in block.splitlines()
        if re.fullmatch(r"[a-zA-Z0-9_ /-]{1,100}", line)]))
    usb = run(["lsusb"])
    print("SMART_USB_IDS=" + json.dumps(
        re.findall(r"ID ([0-9a-f]{4}:[0-9a-f]{4})", usb)))
    print("SMART_DIAGNOSTIC_DEVICE_COMMANDS=NONE")

def main():
    if os.geteuid() != 0 or os.uname().nodename != "Docker": raise SystemExit(64)
    smart_diagnostics()
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
    try:
        db=Path("/mnt/docker-data/volumes/uptime-kuma/_data/kuma.db")
        with sqlite3.connect(db.as_uri()+"?mode=ro&immutable=1",uri=True,timeout=3) as connection:
            connection.execute("PRAGMA query_only=ON")
            users=connection.execute('SELECT COUNT(*) FROM user').fetchone()[0]
            monitors=connection.execute('SELECT COUNT(*) FROM monitor').fetchone()[0]
        print("MONITORING_CHECKPOINTED_USER_COUNT="+str(users))
        print("MONITORING_CHECKPOINTED_MONITOR_COUNT="+str(monitors))
    except Exception:
        print("MONITORING_AUTH_PREFLIGHT=UNAVAILABLE")
    version=run(["docker","exec","uptime-kuma","node","-p","require('/app/package.json').version"]).strip()
    print("MONITORING_INSTALLED_VERSION="+(version if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.A-Za-z0-9]+)?",version) else "UNKNOWN"))
    native=run(["docker","exec","uptime-kuma","node","-e","const {io}=require(\"socket.io-client\"); const socket=io(\"http://127.0.0.1:3001\",{transports:[\"websocket\"],reconnection:false,timeout:4000}); const timer=setTimeout(()=>process.exit(1),6000); socket.on(\"connect\",()=>socket.emit(\"needSetup\",(needed)=>{console.log(JSON.stringify({needSetup:needed,version:require(\"/app/package.json\").version}));clearTimeout(timer);socket.close();})); socket.on(\"connect_error\",()=>process.exit(1));"])
    try:
        details=json.loads(native)
        print("MONITORING_NATIVE_SETUP_REQUIRED="+str(details.get("needSetup") is True))
        print("MONITORING_NATIVE_VERSION="+str(details.get("version") if re.fullmatch(r"[0-9A-Za-z.+-]{1,40}",str(details.get("version"))) else "UNKNOWN"))
    except Exception: print("MONITORING_NATIVE_PREFLIGHT=UNAVAILABLE")
    states=run(["lifeos-secret","exec","homeassistant.long_lived_access_token","HA_TOKEN","python3","-c","import json,os,urllib.request; q=urllib.request.Request(\"http://127.0.0.1:8123/api/config/config_entries/entry\",headers={\"Authorization\":\"Bearer \"+os.environ[\"HA_TOKEN\"]}); rows=json.load(urllib.request.urlopen(q,timeout=6)); print(json.dumps({d:[r.get(\"state\") for r in rows if r.get(\"domain\")==d] for d in [\"matter\",\"zwave_js\",\"mqtt\"]}))"])
    try:
        details=json.loads(states)
        allowed={"loaded","not_loaded","setup_error","setup_retry","migration_error","failed_unload","setup_in_progress","unload_in_progress"}
        print("RECOVERY_HA_INTEGRATIONS="+json.dumps({k:[v if v in allowed else "OTHER" for v in details.get(k,[])] for k in ["matter","zwave_js","mqtt"]}))
    except Exception: print("RECOVERY_HA_INTEGRATIONS=UNAVAILABLE")
    core=run(["lifeos-secret","exec","homeassistant.long_lived_access_token","HA_TOKEN","python3","-c","import json,os,urllib.request; h={\"Authorization\":\"Bearer \"+os.environ[\"HA_TOKEN\"]}; q=urllib.request.Request(\"http://127.0.0.1:8123/api/config\",headers=h); d=json.load(urllib.request.urlopen(q,timeout=6)); print(json.dumps({\"state\":d.get(\"state\"),\"components\":len(d.get(\"components\",[]))}))"])
    try:
        value=json.loads(core);state=str(value.get("state")).upper()
        print("RECOVERY_HA_CORE="+json.dumps({"state":state if state in {"RUNNING","STARTING","STOPPING","NOT_RUNNING"} else "OTHER","component_count":value.get("components")}))
    except Exception: print("RECOVERY_HA_CORE=UNAVAILABLE")
    health=json.loads(run(["docker","inspect","--format","{{json .State.Health}}","homeassistant"]) or "{}")
    print("RECOVERY_HA_HEALTH="+json.dumps({"status":health.get("Status"),"exit_codes":[r.get("ExitCode") for r in health.get("Log",[])]}))
    # docker writes HA logs to stderr; capture privately, emit fixed categories only.
    try:
        proc=subprocess.run(["docker","logs","--tail","1200","homeassistant"],capture_output=True,text=True,timeout=8)
        logs=(proc.stdout+proc.stderr)[-1048576:]
    except Exception: logs=""
    patterns={"DB_LOCKED":r"database is locked|database locked","DB_CORRUPT":r"database disk image is malformed|database.*corrupt","NO_SPACE":r"No space left","PERMISSION":r"PermissionError|Permission denied","SETUP_FAILURE":r"Error setting up|Setup failed","SETUP_WAIT":r"Waiting on integrations|taking over.*seconds","INITIALIZED":r"Home Assistant initialized|Home Assistant is running","TRACEBACK":r"Traceback"}
    print("RECOVERY_HA_LOG_CATEGORIES="+json.dumps({k:len(re.findall(p,logs,re.I)) for k,p in patterns.items()}))
    codes={}
    for label,url in {"HA_ROOT":"http://127.0.0.1:8123/","HA_ONBOARDING":"http://127.0.0.1:8123/api/onboarding"}.items():
        result=run(["curl","--noproxy","*","-s","--max-time","5","-o","/dev/null","-w","%{http_code}",url])
        codes[label]=result.strip() if re.fullmatch(r"[0-9]{3}",result.strip()) else "UNAVAILABLE"
    print("RECOVERY_HA_HTTP_CODES="+json.dumps(codes))
    try:
        tower=json.loads(run(["mosquitto_sub","-h","127.0.0.1","-t","lifeos/tower/state","-C","1","-W","5"]))
        print("RECOVERY_TOWER_STATE="+json.dumps({k:tower.get(k) for k in ["lease_state","active_leases","accessible","idle_seconds"]}))
    except Exception: print("RECOVERY_TOWER_STATE=UNAVAILABLE")
    try:
        import base64, http.client, stat
        credential=Path("/etc/lifeos/secrets/uptime-kuma/admin.json")
        fd=os.open(credential,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o600 or not stat.S_ISREG(info.st_mode) or info.st_size>4096: raise ValueError("unsafe")
            auth=json.loads(os.read(fd,4096))
        finally: os.close(fd)
        header=base64.b64encode((auth["username"]+":"+auth["password"]).encode()).decode()
        connection=http.client.HTTPConnection("127.0.0.1",3002,timeout=8)
        try:
            connection.request("GET","/metrics",headers={"Authorization":"Basic "+header})
            response=connection.getresponse()
            if response.status!=200: raise ValueError("metrics_unavailable")
            data=response.read(1048577)
            if len(data)>1048576: raise ValueError("metrics_oversized")
        finally: connection.close()
        statuses=[float(line.rsplit(" ",1)[1]) for line in data.decode().splitlines() if line.startswith("monitor_status{")]
        known={"Homelab Router","Homelab WAN without DNS","Homelab Public DNS via AdGuard","Homelab Local DNS via AdGuard","Homelab MQTT listener","Homelab Matter listener","Homelab Home Assistant","Homelab AdGuard admin","Homelab Energy API","Homelab Paperless","Homelab Vaultwarden","Homelab Predbat"}
        down=[]
        for line in data.decode().splitlines():
            if line.startswith("monitor_status{") and float(line.rsplit(" ",1)[1])!=1:
                for name in known:
                    if 'monitor_name="'+name+'"' in line: down.append(name)
        print("MONITORING_NATIVE_STATUS="+json.dumps({"monitors":len(statuses),"up":sum(x==1 for x in statuses),"down":sum(x==0 for x in statuses),"down_services":sorted(down)}))
    except FileNotFoundError: print("MONITORING_NATIVE_STATUS=NOT_CONFIGURED")
    except Exception: print("MONITORING_NATIVE_STATUS=UNAVAILABLE")
    try:
        rows=run(["ss","-H","-ltn"]).splitlines()
        bindings=[row.split()[3] for row in rows if len(row.split())>3 and row.split()[3].endswith(":5052")]
        print("MONITORING_PREDBAT_BIND="+json.dumps({"listeners":len(bindings),"loopback_only":bool(bindings) and all(v.startswith(("127.","[::1]:")) for v in bindings)}))
        db=Path("/mnt/docker-data/volumes/uptime-kuma/_data/kuma.db")
        with sqlite3.connect(db.as_uri()+"?mode=ro&immutable=1",uri=True,timeout=3) as connection:
            messages=connection.execute("SELECT h.msg FROM heartbeat h JOIN monitor m ON m.id=h.monitor_id WHERE m.name='Homelab Predbat' ORDER BY h.id DESC LIMIT 5").fetchall()
        raw=" ".join(str(row[0]) for row in messages)
        categories={"CONNECTION_REFUSED":r"ECONNREFUSED|connection refused","TIMEOUT":r"timeout|timed out","HTTP_AUTH":r"status code (401|403)","HTTP_NOT_FOUND":r"status code 404","HTTP_SERVER":r"status code 5[0-9][0-9]"}
        print("MONITORING_PREDBAT_FAILURES="+json.dumps({k:bool(re.search(pattern,raw,re.I)) for k,pattern in categories.items()}))
    except Exception: print("MONITORING_PREDBAT_DIAGNOSTIC=UNAVAILABLE")

    try:
        path=Path("/opt/stacks/homeassistant/config/www/lifeos_tasks.json")
        if path.is_symlink() or path.stat().st_size>8*1024*1024: raise ValueError("unsafe")
        tasks=json.loads(path.read_text())
        held=[row for row in tasks.get("informational",[]) if row.get("obligation_suppressed")=="quote_only_no_verified_policy"]
        exposed=[row for row in tasks.get("tasks",[]) if row.get("obligation_suppressed")=="quote_only_no_verified_policy"]
        print("PA_QUOTE_PROJECTION=" + json.dumps({"held_informational":len(held),"held_still_actionable":len(exposed),"errors":tasks.get("errors"),"age_seconds":int(__import__("time").time())-int(tasks.get("generated_time") or 0)}))
    except Exception: print("PA_QUOTE_PROJECTION=UNAVAILABLE")
    print("RECOVERY_DIAGNOSTIC_MUTATIONS=NONE")
if __name__ == "__main__": main()
