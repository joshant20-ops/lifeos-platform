"""Fixed, staged reboot acceptance for the preserved interrupted migration."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from governor.storage_recovery_audit import device

STATE=Path("/var/lib/lifeos-storage-migration")
RECORD=STATE/"boot-recovery.json"
CANVAS={"lifeos-agent-canvas","lifeos-agent-canvas-tls"}
EXPECTED={"uptime-kuma","zwave-js-ui","homeassistant","nginx-proxy-manager","mosquitto","adguardhome","lifeos-agent-canvas","lifeos-agent-canvas-tls","lifeos-energy","vaultwarden","predbat","paperless-paperless-1","paperless-db-1","paperless-redis-1","matter-server"}
RUNNER="actions.runner.joshant20-ops-lifeos-platform.lifeos-pi5.service"

def command(args,timeout=20):
    return subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=True).stdout.strip()

def boot_id(): return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(data):
    fd,name=tempfile.mkstemp(prefix=".boot-recovery-",dir=STATE)
    with os.fdopen(fd,"w") as handle:
        json.dump(data,handle);handle.flush();os.fsync(handle.fileno())
    os.replace(name,RECORD)

def inventory():
    ids=command(["docker","ps","-aq"]).split()
    rows=json.loads(command(["docker","inspect",*ids]))
    return {r["Name"].lstrip("/"):{"id":r["Id"],"state":r["State"]["Status"],"health":r["State"].get("Health",{}).get("Status","none"),"policy":r["HostConfig"]["RestartPolicy"]["Name"]} for r in rows}

def validate_fleet(before,after):
    if {n for n,r in after.items() if r["state"]=="running"} != EXPECTED: raise RuntimeError("running_set_changed")
    for name,row in before.items():
        if name not in after or row["id"]!=after[name]["id"]: raise RuntimeError("container_identity_changed")
        if row["state"]!="running" and after[name]["state"]=="running": raise RuntimeError("legacy_container_started")
    for name in EXPECTED:
        row=after[name]
        if row["health"] not in {"healthy","none"}: raise RuntimeError("container_not_healthy")

def preflight(require_idle=True):
    if device("/opt/stacks")!="SSD" or device("/mnt/docker-data")!="SSD" or device("/")!="SD_ROOT": raise RuntimeError("storage_device_mismatch")
    if command(["docker","info","--format","{{.DockerRootDir}}"])!="/mnt/docker-data": raise RuntimeError("docker_root")
    command(["/usr/local/sbin/lifeos-require-opt-stacks-ssd"])
    marker=Path("/mnt/docker-data/recovery/sd-opt-stacks-20261017/.lifeos-preserved")
    if not marker.is_file() or marker.is_symlink(): raise RuntimeError("preservation_missing")
    if not STATE.is_dir() or STATE.is_symlink() or STATE.stat().st_uid!=0: raise RuntimeError("state_unsafe")
    for unit in [RUNNER,"ssh.service","NetworkManager.service","lifeos-root-broker.socket","lifeos-control-job-submit.socket","lifeos-tower-control.service"]:
        command(["systemctl","is-active","--quiet",unit])
    command(["systemctl","is-enabled","--quiet",RUNNER])
    state=json.loads(command(["mosquitto_sub","-h","127.0.0.1","-t","lifeos/tower/state","-C","1","-W","5"]))
    if require_idle and (state.get("lease_state")!="NONE" or int(state.get("active_leases") or 0)!=0): raise RuntimeError("active_compute_lease")

def applications():
    command(["bash","/home/joshan/lifeos-platform/scripts/lifeos-storage-verify-runtime.sh"],timeout=180)
    command(["bash","/home/joshan/lifeos-platform/scripts/lifeos-storage-restore-matter.sh"],timeout=240)
    print("BOOT_NATIVE_APPLICATION_ACCEPTANCE=PASS")

def prepare():
    preflight()
    if RECORD.exists() or RECORD.is_symlink(): raise RuntimeError("boot_record_already_exists")
    before=inventory();validate_fleet(before,before)
    applications()
    data={"status":"PREPARING","time":int(time.time()),"boot_id":boot_id(),"containers":before,"fstab_sha":digest("/etc/fstab"),"guard_sha":digest("/usr/local/sbin/lifeos-require-opt-stacks-ssd")}
    save(data)
    changed=[]
    try:
        for name in EXPECTED:
            policy=before[name]["policy"]
            if name in CANVAS and policy=="no":
                command(["docker","update","--restart","unless-stopped",before[name]["id"]]);changed.append(name)
            elif policy not in {"unless-stopped","always"}: raise RuntimeError("unexpected_restart_policy")
        after=inventory();validate_fleet(before,after)
        if any(after[n]["policy"] not in {"unless-stopped","always"} for n in EXPECTED): raise RuntimeError("restart_policy_not_persisted")
        data["status"]="PREPARED";data["time"]=int(time.time());save(data)
        print("BOOT_PREPARE=PASS")
        print("BOOT_POLICY_CHANGE=ONLY_TWO_RUNNING_CANVAS_CONTAINERS")
    except Exception:
        for name in changed:
            command(["docker","update","--restart",before[name]["policy"],before[name]["id"]])
        data["status"]="PREPARE_FAILED_ROLLED_BACK";save(data)
        raise

def reboot():
    preflight()
    data=json.loads(RECORD.read_text())
    if data["status"]!="PREPARED" or data["boot_id"]!=boot_id() or not 0<=time.time()-data["time"]<900: raise RuntimeError("stale_reboot_request")
    validate_fleet(data["containers"],inventory())
    if data["fstab_sha"]!=digest("/etc/fstab") or data["guard_sha"]!=digest("/usr/local/sbin/lifeos-require-opt-stacks-ssd"): raise RuntimeError("boot_configuration_changed")
    if any(inventory()[n]["policy"] not in {"unless-stopped","always"} for n in EXPECTED): raise RuntimeError("restart_policy_changed")
    data["status"]="REBOOT_SCHEDULED";data["scheduled_at"]=int(time.time());save(data)
    command(["sync"],timeout=60)
    command(["systemd-run","--unit=lifeos-storage-recovery-reboot","--on-active=45s","--timer-property=AccuracySec=1s","/usr/bin/systemctl","reboot"])
    print("BOOT_REBOOT_SCHEDULED=45_SECONDS")
    print("BOOT_ACCEPTANCE=PENDING_REAL_NEW_BOOT")

def verify():
    data=json.loads(RECORD.read_text())
    if data["status"]!="REBOOT_SCHEDULED" or data["boot_id"]==boot_id(): raise RuntimeError("new_boot_not_observed")
    for attempt in range(60):
        try:
            preflight(require_idle=False);validate_fleet(data["containers"],inventory());break
        except Exception:
            if attempt==59: raise
            time.sleep(3)
    applications()
    validate_fleet(data["containers"],inventory())
    data["status"]="VERIFIED";data["verified_boot_id"]=boot_id();data["verified_at"]=int(time.time());save(data)
    fd=os.open(STATE/"boot-validation.pass",os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w") as handle:
        handle.write("REAL_REBOOT=PASS\nCURRENT_SERVICE_SET=PASS\n");handle.flush();os.fsync(handle.fileno())
    print("BOOT_REAL_NEW_BOOT=PASS")
    print("BOOT_SAME_CONTAINER_IDENTITIES=PASS")
    print("BOOT_LEGACY_STOPPED_SET_UNCHANGED=PASS")
    print("BOOT_STORAGE_AND_NATIVE_APPLICATIONS=PASS")
    print("BOOT_ACCEPTANCE=PASS")

def main():
    if os.geteuid()!=0 or os.uname().nodename!="Docker" or len(sys.argv)!=2: return 64
    actions={"prepare":prepare,"reboot":reboot,"verify":verify}
    if sys.argv[1] not in actions:return 64
    try:actions[sys.argv[1]]();return 0
    except Exception as error:
        if type(error) is RuntimeError and str(error).replace("_","").isalnum(): print("BOOT_FAILURE_REASON="+str(error))
        print("BOOT_ACCEPTANCE=FAIL_"+type(error).__name__);return 1
if __name__=="__main__":raise SystemExit(main())
