#!/usr/bin/env python3
"""Publish TowerPC/Z97 host telemetry to MQTT for Home Assistant.

Uses Linux /proc and /sys for CPU, memory, network, disk and temperature metrics.
NVIDIA GPU metrics are used when nvidia-smi is already available. No additional
monitoring stack is required.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

MQTT_HOST = os.environ.get("LIFEOS_MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("LIFEOS_MQTT_PORT", "1883"))
INTERVAL = max(5, int(os.environ.get("LIFEOS_TOWER_METRICS_INTERVAL", "15")))
BASE = os.environ.get("LIFEOS_TOWER_METRICS_BASE", "lifeos/tower/metrics")
DISCOVERY = os.environ.get("LIFEOS_HA_DISCOVERY_PREFIX", "homeassistant")
IDLE_SECONDS = max(60, int(os.environ.get("LIFEOS_TOWER_IDLE_SECONDS", "600")))
CPU_IDLE_MAX = float(os.environ.get("LIFEOS_TOWER_IDLE_CPU_MAX", "10"))
GPU_IDLE_MAX = float(os.environ.get("LIFEOS_TOWER_IDLE_GPU_MAX", "10"))
DISK_IDLE_MAX_MBPS = float(os.environ.get("LIFEOS_TOWER_IDLE_DISK_MAX_MBPS", "1"))
NET_IDLE_MAX_MBPS = float(os.environ.get("LIFEOS_TOWER_IDLE_NET_MAX_MBPS", "0.25"))


def pub(topic: str, payload: str, retain: bool = False) -> None:
    args = ["mosquitto_pub", "-h", MQTT_HOST, "-p", str(MQTT_PORT), "-t", topic, "-m", payload]
    if retain:
        args.append("-r")
    subprocess.run(args, check=True, timeout=10)


def safe_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def read_cpu() -> tuple[int, int]:
    fields = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    total = sum(fields)
    return idle, total


def cpu_percent(prev: tuple[int, int], cur: tuple[int, int]) -> float:
    idle = cur[0] - prev[0]
    total = cur[1] - prev[1]
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - idle / total)))


def memory_percent() -> tuple[float, float, float]:
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, rest = line.split(":", 1)
        try:
            values[key] = int(rest.strip().split()[0])
        except (ValueError, IndexError):
            pass
    total = values.get("MemTotal", 0) / 1024 / 1024
    available = values.get("MemAvailable", 0) / 1024 / 1024
    used = max(0.0, total - available)
    pct = used / total * 100 if total else 0.0
    return pct, used, total


def network_bytes() -> tuple[int, int]:
    rx = tx = 0
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        iface, raw = line.split(":", 1)
        iface = iface.strip()
        if iface == "lo":
            continue
        cols = raw.split()
        rx += int(cols[0])
        tx += int(cols[8])
    return rx, tx


def disk_counters() -> dict[str, tuple[int, int]]:
    result = {}
    for line in Path("/proc/diskstats").read_text().splitlines():
        cols = line.split()
        if len(cols) < 14:
            continue
        name = cols[2]
        # Whole physical disks only. Exclude loop/ram/device-mapper and partitions.
        if name.startswith(("loop", "ram", "dm-", "md")):
            continue
        if re.match(r"^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$", name):
            sectors_read = int(cols[5])
            sectors_written = int(cols[9])
            result[name] = (sectors_read, sectors_written)
    return result


def disk_capacity(name: str) -> tuple[float | None, float | None, float | None]:
    # Capacity is per mounted filesystem associated with the physical disk.
    best = None
    try:
        mounts = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return None, None, None
    for line in mounts:
        cols = line.split()
        if len(cols) < 2:
            continue
        dev, mount = cols[0], cols[1].replace("\\040", " ")
        if not dev.startswith("/dev/"):
            continue
        base = Path(dev).name
        if name.startswith("nvme"):
            matches = base == name or base.startswith(name + "p")
        else:
            matches = base == name or re.match(rf"^{re.escape(name)}\d+$", base)
        if not matches:
            continue
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        total = usage.total / 1024**3
        used = (usage.total - usage.free) / 1024**3
        pct = used / total * 100 if total else 0.0
        candidate = (pct, used, total)
        if best is None or total > best[2]:
            best = candidate
    return best or (None, None, None)


def temperatures() -> tuple[float | None, dict[str, float]]:
    vals = {}
    for input_path in Path("/sys/class/hwmon").glob("hwmon*/temp*_input"):
        try:
            raw = float(input_path.read_text().strip()) / 1000
            if not (-20 <= raw <= 130):
                continue
            label_path = input_path.with_name(input_path.name.replace("_input", "_label"))
            label = label_path.read_text().strip() if label_path.exists() else input_path.parent.name + "_" + input_path.stem
            vals[label] = raw
        except (OSError, ValueError):
            continue
    cpu_candidates = [v for k, v in vals.items() if any(x in k.lower() for x in ("package", "core", "cpu", "tdie", "tctl"))]
    return (max(cpu_candidates) if cpu_candidates else (max(vals.values()) if vals else None)), vals


def gpu_metrics() -> dict:
    if shutil.which("nvidia-smi"):
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        cp = subprocess.run(cmd, text=True, capture_output=True, timeout=5)
        if cp.returncode == 0 and cp.stdout.strip():
            row = [x.strip() for x in cp.stdout.splitlines()[0].split(",")]
            if len(row) >= 6:
                def num(x):
                    try:
                        return float(x)
                    except ValueError:
                        return None
                used, total = num(row[2]), num(row[3])
                return {
                    "available": True,
                    "vendor": "nvidia",
                    "name": row[0],
                    "util_percent": num(row[1]),
                    "vram_used_mb": used,
                    "vram_total_mb": total,
                    "vram_percent": (used / total * 100) if used is not None and total else None,
                    "temp_c": num(row[4]),
                    "power_w": num(row[5]),
                }
    # Generic DRM busy percentage where the kernel exports gpu_busy_percent.
    for p in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
        try:
            util = float(p.read_text().strip())
            return {"available": True, "vendor": "drm", "name": p.parts[-3], "util_percent": util}
        except (OSError, ValueError):
            pass
    return {"available": False, "util_percent": 0.0}


def discovery_sensor(object_id: str, name: str, template: str, unit: str | None = None,
                     device_class: str | None = None, state_class: str | None = "measurement",
                     icon: str | None = None) -> None:
    payload = {
        "name": name,
        "unique_id": f"lifeos_tower_{object_id}_v1",
        "state_topic": BASE,
        "value_template": template,
        "availability_topic": f"{BASE}/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": {
            "identifiers": ["lifeos_tower"],
            "name": "Tower PC / Z97",
            "manufacturer": "LifeOS",
            "model": "Z97 telemetry",
        },
    }
    if unit:
        payload["unit_of_measurement"] = unit
    if device_class:
        payload["device_class"] = device_class
    if state_class:
        payload["state_class"] = state_class
    if icon:
        payload["icon"] = icon
    pub(f"{DISCOVERY}/sensor/tower/{object_id}/config", json.dumps(payload, separators=(",", ":")), True)


def publish_discovery(disks: list[str]) -> None:
    fixed = [
        ("cpu_util", "CPU utilisation", "{{ value_json.cpu_percent }}", "%", None, "measurement", "mdi:cpu-64-bit"),
        ("ram_util", "RAM utilisation", "{{ value_json.ram_percent }}", "%", None, "measurement", "mdi:memory"),
        ("cpu_temp", "CPU temperature", "{{ value_json.cpu_temp_c }}", "°C", "temperature", "measurement", "mdi:thermometer"),
        ("load_1m", "Load average 1m", "{{ value_json.load_1m }}", None, None, "measurement", "mdi:gauge"),
        ("net_rx", "Network receive", "{{ value_json.net_rx_mb_s }}", "MB/s", "data_rate", "measurement", "mdi:download-network"),
        ("net_tx", "Network transmit", "{{ value_json.net_tx_mb_s }}", "MB/s", "data_rate", "measurement", "mdi:upload-network"),
        ("gpu_util", "GPU utilisation", "{{ value_json.gpu.util_percent }}", "%", None, "measurement", "mdi:expansion-card"),
        ("gpu_temp", "GPU temperature", "{{ value_json.gpu.temp_c }}", "°C", "temperature", "measurement", "mdi:thermometer"),
        ("gpu_vram", "GPU VRAM utilisation", "{{ value_json.gpu.vram_percent }}", "%", None, "measurement", "mdi:memory"),
        ("gpu_power", "GPU power", "{{ value_json.gpu.power_w }}", "W", "power", "measurement", "mdi:flash"),
        ("activity", "Activity state", "{{ value_json.activity }}", None, None, None, "mdi:state-machine"),
    ]
    for args in fixed:
        discovery_sensor(*args)
    for disk in disks:
        did = safe_id(disk)
        discovery_sensor(f"disk_{did}_read", f"{disk} read rate", f"{{{{ value_json.disks.{disk}.read_mb_s }}}}", "MB/s", "data_rate", "measurement", "mdi:harddisk")
        discovery_sensor(f"disk_{did}_write", f"{disk} write rate", f"{{{{ value_json.disks.{disk}.write_mb_s }}}}", "MB/s", "data_rate", "measurement", "mdi:harddisk")
        discovery_sensor(f"disk_{did}_used", f"{disk} used", f"{{{{ value_json.disks.{disk}.used_percent }}}}", "%", None, "measurement", "mdi:harddisk")


def main() -> None:
    if not shutil.which("mosquitto_pub"):
        raise SystemExit("mosquitto_pub is required; install/use the existing MQTT client package before enabling this service")

    pub(f"{BASE}/availability", "online", True)
    prev_cpu = read_cpu()
    prev_net = network_bytes()
    prev_disks = disk_counters()
    publish_discovery(sorted(prev_disks))
    last_discovery = time.monotonic()
    idle_since = None

    while True:
        started = time.monotonic()
        time.sleep(INTERVAL)
        now = time.monotonic()
        elapsed = max(0.001, now - started)

        cur_cpu = read_cpu()
        cpu = cpu_percent(prev_cpu, cur_cpu)
        prev_cpu = cur_cpu

        ram_pct, ram_used, ram_total = memory_percent()
        cur_net = network_bytes()
        rx = max(0, cur_net[0] - prev_net[0]) / elapsed / 1024**2
        tx = max(0, cur_net[1] - prev_net[1]) / elapsed / 1024**2
        prev_net = cur_net

        cur_disks = disk_counters()
        disks = {}
        total_disk_mbps = 0.0
        for name, vals in cur_disks.items():
            old = prev_disks.get(name, vals)
            read = max(0, vals[0] - old[0]) * 512 / elapsed / 1024**2
            write = max(0, vals[1] - old[1]) * 512 / elapsed / 1024**2
            used_pct, used_gb, total_gb = disk_capacity(name)
            disks[name] = {
                "read_mb_s": round(read, 3), "write_mb_s": round(write, 3),
                "used_percent": round(used_pct, 1) if used_pct is not None else None,
                "used_gb": round(used_gb, 1) if used_gb is not None else None,
                "total_gb": round(total_gb, 1) if total_gb is not None else None,
            }
            total_disk_mbps += read + write
        prev_disks = cur_disks

        cpu_temp, _ = temperatures()
        gpu = gpu_metrics()
        gpu_util = float(gpu.get("util_percent") or 0.0)
        low_activity = (
            cpu < CPU_IDLE_MAX and gpu_util < GPU_IDLE_MAX and
            total_disk_mbps < DISK_IDLE_MAX_MBPS and (rx + tx) < NET_IDLE_MAX_MBPS
        )
        if low_activity:
            if idle_since is None:
                idle_since = time.monotonic()
            activity = "IDLE" if time.monotonic() - idle_since >= IDLE_SECONDS else "QUIET"
        else:
            idle_since = None
            activity = "HEAVY" if max(cpu, gpu_util) >= 80 or total_disk_mbps >= 100 else "ACTIVE"

        load1, load5, load15 = os.getloadavg()
        payload = {
            "timestamp": int(time.time()),
            "cpu_percent": round(cpu, 1),
            "ram_percent": round(ram_pct, 1),
            "ram_used_gb": round(ram_used, 2),
            "ram_total_gb": round(ram_total, 2),
            "cpu_temp_c": round(cpu_temp, 1) if cpu_temp is not None else None,
            "load_1m": round(load1, 2), "load_5m": round(load5, 2), "load_15m": round(load15, 2),
            "net_rx_mb_s": round(rx, 3), "net_tx_mb_s": round(tx, 3),
            "gpu": gpu, "disks": disks, "activity": activity,
        }
        pub(BASE, json.dumps(payload, separators=(",", ":")), False)
        pub(f"{BASE}/availability", "online", True)
        if time.monotonic() - last_discovery > 3600:
            publish_discovery(sorted(cur_disks))
            last_discovery = time.monotonic()


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            pub(f"{BASE}/availability", "offline", True)
        except Exception:
            pass
