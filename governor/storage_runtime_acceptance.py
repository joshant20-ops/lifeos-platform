"""Bounded disposable write probes and native read checks for storage recovery."""
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
from governor.storage_recovery_audit import device

TARGETS = {"homeassistant":"/config","mosquitto":"/mosquitto/data","adguardhome":"/opt/adguardhome/work","lifeos-energy":"/data","vaultwarden":"/data","predbat":"/config"}
TOKEN = "lifeos-storage-recovery-disposable-probe"
def command(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)

def probe_location(container, target, row):
    matches=[m for m in row.get("Mounts",[]) if m.get("Destination")==target and m.get("RW") and m.get("Type") in {"bind","volume"}]
    if len(matches)!=1: raise RuntimeError("mount_missing")
    source=Path(matches[0]["Source"])
    if not source.is_dir() or device(source)!="SSD": raise RuntimeError("mount_not_ssd")
    return source

def write_probe(container,target,row):
    source=probe_location(container,target,row)
    path=None
    try:
        # All strings except the fixed target are literal; no user input enters shell.
        result=command(["docker","exec",container,"sh","-ec",
            'umask 077; p=$(mktemp "$1/.lifeos-storage-probe.XXXXXX"); printf %s "$2" >"$p"; sync "$p"; printf %s "$p"',
            "probe",target,TOKEN])
        path=result.stdout.strip()
        if not re.fullmatch(re.escape(target)+r"/\.lifeos-storage-probe\.[A-Za-z0-9]{6}",path):
            path=None
            raise RuntimeError("probe_identity")
        host=source/Path(path).name
        fd=os.open(host,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            if os.read(fd,256)!=TOKEN.encode(): raise RuntimeError("probe_bytes")
            os.fsync(fd)
        finally: os.close(fd)
        if device(host)!="SSD": raise RuntimeError("probe_device")
        return True
    finally:
        if path:
            command(["docker","exec",container,"rm","--",path])
            if (source/Path(path).name).exists(): raise RuntimeError("probe_cleanup")

def http_check(url):
    try:
        request=urllib.request.Request(url)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request,timeout=8) as response:
            return response.status==200
    except Exception: return False

def main():
    if os.geteuid()!=0 or os.uname().nodename!="Docker": raise SystemExit(64)
    marker=Path("/mnt/docker-data/recovery/sd-opt-stacks-20261017/.lifeos-preserved")
    if not marker.is_file() or marker.is_symlink():
        print("RUNTIME_ACCEPTANCE=FAIL_SOURCE_NOT_PRESERVED"); return 1
    rows=json.loads(command(["docker","inspect",*TARGETS]).stdout)
    indexed={r["Name"].lstrip("/"):r for r in rows}
    failed=False
    for name,target in TARGETS.items():
        try:
            row=indexed[name]
            state=row.get("State",{})
            if state.get("Status")!="running" or state.get("Health",{}).get("Status") in {"unhealthy","starting"}:
                raise RuntimeError("not_ready")
            write_probe(name,target,row)
            print("RUNTIME_SSD_WRITE_"+name.replace("-","_")+"=PASS")
        except Exception as error:
            # Never print raw subprocess output/exception text.
            print("RUNTIME_SSD_WRITE_"+name.replace("-","_")+"=FAIL_"+type(error).__name__)
            failed=True
    for label,url in {"ADGUARD_ADMIN":"http://127.0.0.1:3001/","ENERGY_API":"http://127.0.0.1:8110/api/energy/current","VAULTWARDEN_ALIVE":"http://127.0.0.1:8081/alive","PREDBAT_UI":"http://127.0.0.1:5052/"}.items():
        ok=http_check(url);print("RUNTIME_"+label+"="+("PASS" if ok else "FAIL")); failed|=not ok
    ha_code='import os,urllib.request; q=urllib.request.Request("http://127.0.0.1:8123/api/",headers={"Authorization":"Bearer "+os.environ["HA_TOKEN"]}); r=urllib.request.urlopen(q,timeout=8); assert r.status==200; print("HA_AUTH_PASS")'
    try:
        result=command(["lifeos-secret","exec","homeassistant.long_lived_access_token","HA_TOKEN","python3","-c",ha_code],timeout=15)
        ok=result.stdout.strip()=="HA_AUTH_PASS"
    except Exception: ok=False
    print("RUNTIME_HA_AUTH="+("PASS" if ok else "FAIL"));failed|=not ok
    # Non-retained, exact private diagnostic topic: no device/control topic.
    topic="lifeos/diagnostics/storage-recovery"
    subscriber=subprocess.Popen(["mosquitto_sub","-h","127.0.0.1","-t",topic,"-C","1","-W","8"],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    try:
        import time
        time.sleep(1)
        command(["mosquitto_pub","-h","127.0.0.1","-t",topic,"-m",TOKEN])
        output=subscriber.communicate(timeout=10)[0]
        ok=subscriber.returncode==0 and output.strip()==TOKEN
    except Exception:
        subscriber.kill();subscriber.communicate();ok=False
    print("RUNTIME_MQTT_ROUNDTRIP="+("PASS" if ok else "FAIL"));failed|=not ok
    from governor.paperless_runtime_diagnostic import paperless_document_media_probe
    docs,media=paperless_document_media_probe()
    ok=docs=="PASS" and media=="PASS"
    print("RUNTIME_PAPERLESS_AUTH_MEDIA="+("PASS" if ok else "FAIL"));failed|=not ok
    print("RUNTIME_MUTATIONS=DISPOSABLE_PROBE_FILES_AND_NONRETAINED_DIAGNOSTIC_MQTT_ONLY")
    print("RUNTIME_ACCEPTANCE="+("FAIL" if failed else "PASS"))
    return 1 if failed else 0
if __name__=="__main__": raise SystemExit(main())
