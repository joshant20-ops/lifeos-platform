#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG=/etc/lifeos/tower.json
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || { echo 'ERROR=tower_config_missing'; exit 1; }

read -r TOWER_HOST EXPECTED_MAC < <(python3 - "$CONFIG" <<'PY'
import ipaddress, json, re, sys
from pathlib import Path
cfg=json.loads(Path(sys.argv[1]).read_text())
mac=str(cfg.get("mac") or "").replace("-",":").lower()
if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
    raise SystemExit("ERROR=configured_tower_mac_invalid")
probe=cfg.get("access_probe") if isinstance(cfg.get("access_probe"),dict) else {}
shutdown=cfg.get("shutdown") if isinstance(cfg.get("shutdown"),dict) else {}
for value in (probe.get("host"),cfg.get("host"),shutdown.get("host")):
    try:
        address=ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        continue
    if address.version == 4 and address.is_private:
        print(f"{address} {mac}")
        break
else:
    raise SystemExit("ERROR=configured_private_tower_host_missing")
PY
)
[[ "$TOWER_HOST" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { echo 'ERROR=tower_host_invalid'; exit 1; }
[[ "$EXPECTED_MAC" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]] || { echo 'ERROR=tower_mac_invalid'; exit 1; }

CONTROLLER_IP="$(ip -4 -o route get "$TOWER_HOST" | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
[[ "$CONTROLLER_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { echo 'ERROR=controller_source_ip_unavailable'; exit 1; }

REMOTE_SCRIPT="$(cat <<'REMOTE'
set -Eeuo pipefail
EXPECTED_MAC="$1"
CONTROLLER_IP="$2"
[[ "$EXPECTED_MAC" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]]
[[ "$CONTROLLER_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]

echo "TOWER_EXPECTED_WOL_MAC=$EXPECTED_MAC"
echo "TOWER_CONTROLLER_SOURCE_IP=$CONTROLLER_IP"
echo '==> TOWER ip link'
ip link
echo '==> TOWER ip addr'
ip addr
echo '==> TOWER ip route'
ip route

ACTIVE_IFACE="$(ip -j route get "$CONTROLLER_IP" 2>/dev/null | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0].get("dev","") if rows else "")' || true)"
if [[ -z "$ACTIVE_IFACE" ]]; then
  ACTIVE_IFACE="$(ip -j route show default 2>/dev/null | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0].get("dev","") if rows else "")' || true)"
fi
echo "TOWER_ACTIVE_ROUTE_INTERFACE=${ACTIVE_IFACE:-UNKNOWN}"
ROUTE_IFACE="$ACTIVE_IFACE"
PHY_IFACES=()
if [[ -n "$ROUTE_IFACE" ]]; then
  for candidate_path in "/sys/class/net/$ROUTE_IFACE"/brif/* "/sys/class/net/$ROUTE_IFACE"/lower_*; do
    [[ -e "$candidate_path" ]] || continue
    candidate="${candidate_path##*/}"
    [[ -e "/sys/class/net/$candidate/device" ]] && PHY_IFACES+=("$candidate")
  done
  if [[ ${#PHY_IFACES[@]} -eq 0 && -e "/sys/class/net/$ROUTE_IFACE/device" ]]; then
    PHY_IFACES+=("$ROUTE_IFACE")
  fi
fi
PHY_IFACE="$ROUTE_IFACE"
for candidate in "${PHY_IFACES[@]}"; do
  candidate_mac="$(cat "/sys/class/net/$candidate/address" 2>/dev/null || true)"
  if [[ "${candidate_mac,,}" == "$EXPECTED_MAC" ]]; then
    PHY_IFACE="$candidate"
    break
  fi
done
if [[ -z "$PHY_IFACE" || ! -e "/sys/class/net/$PHY_IFACE/device" ]]; then
  PHY_IFACE="${PHY_IFACES[0]:-$ROUTE_IFACE}"
fi
echo "TOWER_ACTIVE_PHYSICAL_ETHERNET_INTERFACE=${PHY_IFACE:-UNKNOWN}"
if [[ -n "$PHY_IFACE" ]]; then
  if [[ -r "/sys/class/net/$PHY_IFACE/type" ]]; then
    LINK_TYPE="$(cat "/sys/class/net/$PHY_IFACE/type")"
    echo "TOWER_ACTIVE_INTERFACE_LINK_TYPE=$LINK_TYPE"
    if [[ -e "/sys/class/net/$PHY_IFACE/device" ]]; then
      echo 'TOWER_ACTIVE_INTERFACE_PHYSICAL_DEVICE=YES'
    else
      echo 'TOWER_ACTIVE_INTERFACE_PHYSICAL_DEVICE=NO'
    fi
    echo "TOWER_ACTIVE_INTERFACE_MAC=$(cat "/sys/class/net/$PHY_IFACE/address" 2>/dev/null || echo unknown)"
    echo "TOWER_WOL_MAC_INTERFACE_MATCH=$(python3 - "$PHY_IFACE" "$EXPECTED_MAC" <<'PY'
import sys
from pathlib import Path
iface,expected=sys.argv[1:]
actual=Path("/sys/class/net",iface,"address").read_text().strip().lower()
print("YES" if actual == expected else "NO")
PY
)"
    echo '==> TOWER ethtool'
    if command -v ethtool >/dev/null 2>&1; then
      ethtool "$PHY_IFACE" || echo 'ETHTOOL_RESULT=UNAVAILABLE'
      echo '==> TOWER ethtool -i'
      ethtool -i "$PHY_IFACE" || echo 'ETHTOOL_DRIVER_RESULT=UNAVAILABLE'
      echo '==> TOWER ethtool --show-eee'
      ethtool --show-eee "$PHY_IFACE" || echo 'ETHTOOL_EEE_RESULT=UNSUPPORTED_OR_UNAVAILABLE'
    else
      echo 'ETHTOOL_RESULT=NOT_INSTALLED'
      echo '==> TOWER read-only ethtool ioctl fallback'
      python3 - "$PHY_IFACE" <<'PY'
import array, ctypes, errno, fcntl, os, socket, struct, sys
iface = sys.argv[1]
driver_link = f"/sys/class/net/{iface}/device/driver"
if os.path.exists(driver_link):
    print("TOWER_DRIVER_SYSFS=" + os.path.basename(os.path.realpath(driver_link)))
else:
    print("TOWER_DRIVER_SYSFS=UNAVAILABLE")
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
def query(cmd, size):
    buf = bytearray(size)
    struct.pack_into("=I", buf, 0, cmd)
    holder = (ctypes.c_ubyte * size).from_buffer(buf)
    ifreq = struct.pack("16sP", iface.encode(), ctypes.addressof(holder))
    fcntl.ioctl(sock.fileno(), 0x8946, ifreq)
    return buf
def wol_letters(mask):
    return "".join(letter for bit, letter in ((1,"p"),(2,"u"),(4,"m"),(8,"b"),(16,"a"),(32,"g"),(64,"s"),(128,"f")) if mask & bit) or "d"
try:
    wol = query(0x14, 16)
    _, supported, current = struct.unpack_from("=III", wol)
    print("TOWER_SUPPORTS_WAKE_ON=" + wol_letters(supported))
    print("TOWER_CURRENT_WAKE_ON=" + wol_letters(current))
    print("TOWER_ETHTOOL_GWOL=PASS")
except OSError as exc:
    print("TOWER_ETHTOOL_GWOL=UNAVAILABLE errno=" + str(exc.errno))
try:
    drv = query(0x3, 196)
    name = bytes(drv[4:36]).split(b"\x00",1)[0].decode(errors="replace")
    version = bytes(drv[36:68]).split(b"\x00",1)[0].decode(errors="replace")
    bus = bytes(drv[100:132]).split(b"\x00",1)[0].decode(errors="replace")
    print("TOWER_ETHTOOL_DRIVER=" + name)
    print("TOWER_ETHTOOL_DRIVER_VERSION=" + version)
    print("TOWER_ETHTOOL_BUS_INFO=" + bus)
except OSError as exc:
    print("TOWER_ETHTOOL_GDRVINFO=UNAVAILABLE errno=" + str(exc.errno))
try:
    eee = query(0x0c, 40)
    _, supported, advertised, lp_advertised, active, enabled, tx_lpi, timer = struct.unpack_from("=IIIIIIII", eee)
    print("TOWER_EEE_SUPPORTED=" + str(bool(supported)))
    print("TOWER_EEE_ENABLED=" + str(bool(enabled)))
    print("TOWER_EEE_ACTIVE=" + str(bool(active)))
    print("TOWER_EEE_TX_LPI_ENABLED=" + str(bool(tx_lpi)))
except OSError as exc:
    print("TOWER_ETHTOOL_GEEE=UNSUPPORTED_OR_UNAVAILABLE errno=" + str(exc.errno))
PY
    fi
    for power_file in       "/sys/class/net/$PHY_IFACE/device/power/wakeup"       "/sys/class/net/$PHY_IFACE/device/power/control"       "/sys/class/net/$PHY_IFACE/device/power/runtime_status"; do
      if [[ -r "$power_file" ]]; then
        echo "TOWER_SYSFS_$(basename "$power_file")=$(cat "$power_file")"
      else
        echo "TOWER_SYSFS_$(basename "$power_file")=UNAVAILABLE"
      fi
    done

    echo '==> TOWER NETWORK MANAGER STATUS'
    for service in NetworkManager systemd-networkd; do
      printf 'TOWER_SERVICE_%s=' "$service"
      systemctl is-active "$service" 2>/dev/null || true
    done
    if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager 2>/dev/null; then
      nmcli -f GENERAL.STATE,GENERAL.CONNECTION,GENERAL.HWADDR,GENERAL.TYPE device show "$PHY_IFACE" || true
      PROFILE="$(nmcli -g GENERAL.CONNECTION device show "$PHY_IFACE" 2>/dev/null | head -n 1 || true)"
      if [[ -n "$PROFILE" && "$PROFILE" != '--' ]]; then
        echo "TOWER_NM_PROFILE=$PROFILE"
        nmcli -f connection.id,connection.interface-name,802-3-ethernet.wake-on-lan connection show "$PROFILE" || true
      fi
    fi
    if command -v networkctl >/dev/null 2>&1 && systemctl is-active --quiet systemd-networkd 2>/dev/null; then
      NETWORK_STATUS="$(networkctl status "$PHY_IFACE" --no-pager 2>/dev/null || true)"
      printf '%s\n' "$NETWORK_STATUS"
      NETWORK_FILE="$(printf '%s\n' "$NETWORK_STATUS" | sed -n 's/^[[:space:]]*Network File: //p' | head -n 1)"
      case "$NETWORK_FILE" in
        /etc/systemd/network/*.network|/run/systemd/network/*.network)
          python3 - "$NETWORK_FILE" "$PHY_IFACE" "$EXPECTED_MAC" <<'PY'
import sys
from pathlib import Path
path,iface,mac=sys.argv[1:]
section=""
print("TOWER_NETWORKD_MATCHED_FILE="+path)
for raw in Path(path).read_text(errors="replace").splitlines():
    line=raw.strip()
    if line.startswith("[") and line.endswith("]"):
        section=line[1:-1]
        continue
    if "=" not in line:
        continue
    key,value=(part.strip() for part in line.split("=",1))
    if (section=="Match" and key in {"Name","MACAddress"}) or (section=="Link" and key=="WakeOnLan"):
        print(f"TOWER_NETWORKD_{section}_{key}={value}")
PY
          ;;
        *)
          echo 'TOWER_NETWORKD_MATCHED_FILE=UNAVAILABLE'
          ;;
      esac
    fi

    if [[ -r /etc/network/interfaces || -d /etc/network/interfaces.d ]]; then
      echo '==> TOWER ifupdown configuration'
      python3 - "$ACTIVE_IFACE" "$ROUTE_IFACE" <<'PY'
import glob, sys
from pathlib import Path
physical, bridge = sys.argv[1:]
targets = {physical, bridge}
paths = ["/etc/network/interfaces", *glob.glob("/etc/network/interfaces.d/*")]
allowed = {"iface", "address", "netmask", "gateway", "bridge-ports", "bridge-stp", "bridge-fd", "bridge-vlan-aware", "bridge-pvid", "hwaddress"}
for filename in paths:
    path = Path(filename)
    if not path.is_file():
        continue
    current = None
    for raw in path.read_text(errors="replace").splitlines():
        parts = raw.strip().split(None, 2)
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] in {"auto", "allow-hotplug"} and any(name in parts[1:] for name in targets):
            print(f"TOWER_IFUPDOWN_{path.name}_{parts[0]}={' '.join(parts[1:])}")
            continue
        if parts[0] == "iface" and len(parts) >= 2:
            current = parts[1] if parts[1] in targets else None
        if current is None:
            continue
        key = parts[0].lower()
        if key in allowed:
            print(f"TOWER_IFUPDOWN_{path.name}_{current}_{key}={' '.join(parts[1:])}")
        elif key in {"post-up", "pre-up"} and any(word in raw.lower() for word in ("ethtool", "wakeonlan", "wol")):
            print(f"TOWER_IFUPDOWN_{path.name}_{current}_{key}={raw.strip()[len(parts[0]):].strip()}")
PY
    fi
  else
    echo 'TOWER_ACTIVE_INTERFACE_DEVICE_PATH=UNAVAILABLE'
  fi
fi

python3 - "$EXPECTED_MAC" <<'PY'
import sys
from pathlib import Path
expected=sys.argv[1]
found=[]
for address_file in Path("/sys/class/net").glob("*/address"):
    try:
        if address_file.read_text().strip().lower() == expected:
            found.append(address_file.parent.name)
    except OSError:
        pass
print("TOWER_CONFIGURED_WOL_MAC_INTERFACES="+(",".join(sorted(found)) if found else "NOT_FOUND"))
print("TOWER_NETWORK_INSPECTION=COMPLETE")
PY
REMOTE
)"

SSH_OPTIONS=(
  -o BatchMode=yes -o IdentitiesOnly=no -o StrictHostKeyChecking=yes
  -o ConnectTimeout=5 -o ServerAliveInterval=5 -o ServerAliveCountMax=2
)
SSH_BASE=(
  /usr/sbin/runuser -u joshan -- /usr/bin/env -i
  HOME=/home/joshan
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  LANG=C.UTF-8
  ssh "${SSH_OPTIONS[@]}"
)
echo "TOWER_INSPECTION_TARGET=$TOWER_HOST"
printf '%s\n' "$REMOTE_SCRIPT" | "${SSH_BASE[@]}" "joshan@$TOWER_HOST" bash -s -- "$EXPECTED_MAC" "$CONTROLLER_IP"
