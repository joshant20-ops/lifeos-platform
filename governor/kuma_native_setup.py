"""Configure installed Kuma through its native API; private credentials stay local."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess

CREDENTIALS=Path("/etc/lifeos/secrets/uptime-kuma/admin.json")
def specs(pi,gateway):
    if not ipaddress.ip_address(pi).is_private or not ipaddress.ip_address(gateway).is_private: raise RuntimeError("unexpected_lan_route")
    rows=[{"name":"Homelab Router","type":"ping","hostname":gateway},{"name":"Homelab WAN without DNS","type":"port","hostname":"1.1.1.1","port":443},{"name":"Homelab Public DNS via AdGuard","type":"dns","hostname":"example.com","dns_resolve_server":pi,"port":53},{"name":"Homelab Local DNS via AdGuard","type":"dns","hostname":"adguard.lan","dns_resolve_server":pi,"port":53},{"name":"Homelab MQTT listener","type":"port","hostname":pi,"port":1883},{"name":"Homelab Matter listener","type":"port","hostname":pi,"port":5580}]
    for name,port,path in [("Home Assistant",8123,"/"),("AdGuard admin",3001,"/"),("Energy API",8110,"/api/energy/current"),("Paperless",8010,"/"),("Vaultwarden",8081,"/alive")]:
        rows.append({"name":"Homelab "+name,"type":"http","url":"http://"+pi+":"+str(port)+path})
    return rows

def credentials():
    parent=CREDENTIALS.parent
    if not parent.exists(): parent.mkdir(mode=0o700,parents=True)
    if parent.is_symlink() or parent.stat().st_uid!=0 or stat.S_IMODE(parent.stat().st_mode)!=0o700: raise RuntimeError("credential_directory_unsafe")
    if not CREDENTIALS.exists() and not CREDENTIALS.is_symlink():
        value={"username":"joshan","password":"Aa1!"+secrets.token_urlsafe(32)}
        fd=os.open(CREDENTIALS,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"w") as handle: json.dump(value,handle);handle.flush();os.fsync(handle.fileno())
    fd=os.open(CREDENTIALS,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        metadata=os.fstat(fd)
        if metadata.st_uid!=0 or stat.S_IMODE(metadata.st_mode)!=0o600 or not stat.S_ISREG(metadata.st_mode) or metadata.st_size>4096: raise RuntimeError("credential_file_unsafe")
        value=json.loads(os.read(fd,4096))
    finally: os.close(fd)
    if set(value)!={"username","password"} or value["username"]!="joshan" or len(value["password"])<32: raise RuntimeError("credential_shape")
    return value

def main():
    if os.geteuid()!=0 or os.uname().nodename!="Docker":return 64
    try:
        route=subprocess.run(["ip","-j","-4","route","get","1.1.1.1"],capture_output=True,text=True,check=True,timeout=5)
        row=json.loads(route.stdout)[0]
        if row.get("dev")!="eth0":raise RuntimeError("unexpected_interface")
        data=credentials();data["monitors"]=specs(row["prefsrc"],row["gateway"])
        data["retiredPredbatUrl"]="http://"+row["prefsrc"]+":5052/"
        script=Path("/home/joshan/lifeos-platform/scripts/lifeos-kuma-native-setup.cjs").read_text()
        result=subprocess.run(["docker","exec","-i","uptime-kuma","node","-e",script],input=json.dumps(data),capture_output=True,text=True,timeout=440)
        details=json.loads(result.stdout.strip().splitlines()[-1])
        if result.returncode or details.get("ok") is not True:
            print("KUMA_SETUP=FAIL");print("KUMA_FAILURE_STAGE="+str(details.get("stage","UNKNOWN")));return 1
        print("KUMA_CONFIGURED_MONITORS="+str(details["configured"]))
        print("KUMA_HEALTHY_MONITORS="+str(details["healthy"]))
        print("KUMA_MINIMUM_LIVE_UP_SAMPLES="+str(details["minimum_up_samples"]))
        print("KUMA_PERSISTED_FAILURE_RECOVERY_HISTORY=PASS")
        print("KUMA_TEMPORARY_DIAGNOSTIC_REMOVED=PASS")
        print("KUMA_CREDENTIALS=LOCAL_ROOT_ONLY")
        print("KUMA_NOTIFICATIONS=NOT_CONFIGURED")
        print("KUMA_SETUP=PASS");return 0
    except Exception as error:
        print("KUMA_SETUP=FAIL_"+type(error).__name__);return 1
if __name__=="__main__":raise SystemExit(main())
