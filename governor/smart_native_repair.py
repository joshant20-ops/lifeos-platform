"""Fixed SAT-driver repair for the owner-identified WD SATA disk; no self-tests."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

UUID = "a53fd6a0-c498-4b76-a496-0e5d9233447f"
MODEL = "WDC WD1600BEVT-22ZCT0"
CONFIG = Path("/etc/smartd.conf")
STATE = Path("/var/lib/lifeos-smart-repair")
DEFAULT = "DEVICESCAN -d removable -n standby -m root -M exec /usr/share/smartmontools/smartd-runner"
REPO = Path("/home/joshan/lifeos-platform")

def command(args, timeout=10, check=True):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("bounded_command_failed") from None
    if check and p.returncode:
        raise RuntimeError("native_command_failed")
    return p

def active_lines(raw):
    return [" ".join(line.split("#", 1)[0].split()) for line in raw.splitlines()
            if line.split("#", 1)[0].strip()]

def replacement(raw, target):
    if not re.fullmatch(r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+", target):
        raise RuntimeError("unsafe_device_identity")
    rule = target + " -d sat -a -n standby -m root -M exec /usr/share/smartmontools/smartd-runner"
    if active_lines(raw) == [rule]:
        return raw
    if active_lines(raw) != [DEFAULT]:
        raise RuntimeError("unexpected_native_configuration")
    return "".join((rule + "\n") if line.split("#", 1)[0].strip() else line
                   for line in raw.splitlines(keepends=True))

def validate_identity(data):
    if data.get("model_name") != MODEL or data.get("device", {}).get("protocol") != "ATA":
        raise RuntimeError("drive_identity_mismatch")
    if not 159_000_000_000 <= data.get("user_capacity", {}).get("bytes", 0) <= 161_000_000_000:
        raise RuntimeError("drive_capacity_mismatch")

def health_summary(data):
    attrs = {row.get("id"):row.get("raw", {}).get("value")
             for row in data.get("ata_smart_attributes", {}).get("table", [])}
    return {"overall_passed": data.get("smart_status", {}).get("passed"),
            "reallocated_sectors": attrs.get(5), "pending_sectors": attrs.get(197),
            "offline_uncorrectable": attrs.get(198), "power_on_hours": attrs.get(9),
            "interface_crc_errors": attrs.get(199)}

def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data); out.flush(); os.fsync(out.fileno())

def atomic_config(raw, info):
    temporary = Path("/etc/smartd.conf.lifeos-sat-tmp")
    private_write(temporary, raw)
    os.chown(temporary, info.st_uid, info.st_gid)
    os.chmod(temporary, stat.S_IMODE(info.st_mode))
    os.replace(temporary, CONFIG)
    fd = os.open("/etc", os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def kernel_faults():
    raw = command(["journalctl", "-k", "-b", "--no-pager", "-o", "cat"], timeout=15).stdout
    return len(re.findall(r"reset .*USB device|uas_eh_abort_handler|uas_eh_device_reset_handler|I/O error.*sda|sda.*I/O error|EXT4-fs error", raw, re.I))

def containers():
    return set(command(["docker", "ps", "-q", "--no-trunc"]).stdout.split())

def topology():
    values = []
    for path in ("/mnt/docker-data", "/opt/stacks"):
        raw = command(["findmnt", "-n", "-o", "UUID,SOURCE", "-T", path]).stdout.split()
        if len(raw) != 2 or raw[0] != UUID or not raw[1].startswith("/dev/sda1"):
            raise RuntimeError("unexpected_storage_topology")
        values.append(raw)
    return values

def main():
    if os.geteuid() != 0 or os.uname().nodename != "Docker":
        raise RuntimeError("wrong_host_or_user")
    STATE.mkdir(mode=0o700, exist_ok=True)
    state_info = STATE.lstat()
    if not stat.S_ISDIR(state_info.st_mode) or state_info.st_uid or stat.S_IMODE(state_info.st_mode) != 0o700:
        raise RuntimeError("unsafe_state_directory")
    lock = os.open(STATE / "lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before_mounts, before_containers = topology(), containers()
    if len(before_containers) < 15:
        raise RuntimeError("current_service_baseline_not_running")
    info = CONFIG.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_size > 65536 or info.st_mode & 0o022:
        raise RuntimeError("unsafe_native_config")
    original = CONFIG.read_bytes()
    links = sorted(str(p) for p in Path("/dev/disk/by-id").iterdir()
                   if p.is_symlink() and p.resolve() == Path("/dev/sda") and not p.name.endswith("-part1"))
    if not links:
        raise RuntimeError("no_stable_whole_disk_identity")
    proposed = replacement(original.decode(), links[0]).encode()
    changed = proposed != original
    service = command(["systemctl", "show", "smartmontools.service", "-p", "ActiveState", "-p", "Result"]).stdout
    if changed and ("ActiveState=failed" not in service or "Result=timeout" not in service):
        raise RuntimeError("unexpected_service_state")
    faults = kernel_faults()
    # Explicit SAT only: no autodetection, fallback protocol, test, enable, or disk write.
    probe = command(["smartctl", "-d", "sat", "-j", "-i", "-H", "-A", "/dev/sda"], timeout=20, check=False)
    if probe.returncode & 7:
        raise RuntimeError("sat_read_query_failed_no_configuration_change")
    try: data = json.loads(probe.stdout)
    except ValueError: raise RuntimeError("invalid_native_reply") from None
    validate_identity(data)
    if kernel_faults() != faults or topology() != before_mounts or containers() != before_containers:
        raise RuntimeError("prechange_regression_no_configuration_change")
    print("SMART_EXPLICIT_SAT_IDENTITY=PASS")
    print("SMART_READ_ONLY_HEALTH=" + json.dumps(health_summary(data)))
    backup = STATE / "smartd.conf.before-sat"
    if changed:
        if backup.exists():
            if backup.is_symlink() or backup.read_bytes() != original:
                raise RuntimeError("backup_conflict")
        else: private_write(backup, original)
        atomic_config(proposed, info)
    started = False
    start_time = int(time.time())
    try:
        if "ActiveState=active" not in service:
            started = True
            command(["systemctl", "start", "smartmontools.service"], timeout=45)
        time.sleep(15)
        command(["systemctl", "is-active", "--quiet", "smartmontools.service"])
        if started:
            journal = command(["journalctl", "-u", "smartmontools.service", "--since", "@" + str(start_time), "--no-pager", "-o", "cat"]).stdout
            if not re.search(r"Monitoring\s+1\s+ATA", journal):
                raise RuntimeError("native_monitor_registration_unproven")
        if kernel_faults() != faults or topology() != before_mounts or containers() != before_containers:
            raise RuntimeError("postchange_storage_regression")
        command(["bash", str(REPO / "scripts/lifeos-storage-verify-runtime.sh")], timeout=180)
        if CONFIG.read_bytes() != proposed:
            raise RuntimeError("configuration_drift")
    except Exception:
        if started: command(["systemctl", "stop", "smartmontools.service"], timeout=30, check=False)
        if changed and CONFIG.read_bytes() == proposed: atomic_config(original, info)
        print("SMART_ROLLBACK=ORIGINAL_CONFIG_RESTORED_NO_UNSAFE_RESTART")
        raise
    print("SMART_NATIVE_SERVICE=ACTIVE")
    print("SMART_NATIVE_ATA_MONITOR=PASS")
    print("SMART_KERNEL_FAULT_DELTA=0")
    print("SMART_MOUNTS_AND_RUNNING_CONTAINERS=UNCHANGED")
    print("SMART_NATIVE_APPLICATION_REGRESSION=PASS")
    print("SMART_SELF_TESTS=NONE")
    print("SMART_REPAIR=PASS")

if __name__ == "__main__":
    try: main()
    except Exception as error:
        # Native output can contain serials; emit only fixed failure categories.
        label = str(error)
        print("SMART_REPAIR=FAIL")
        print("SMART_REPAIR_REASON=" + (label if re.fullmatch(r"[a-z_]{1,100}", label) else "bounded_operation_failed"))
        raise SystemExit(1)
