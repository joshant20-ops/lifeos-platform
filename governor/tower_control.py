#!/usr/bin/env python3
"""Bounded Tower power/state controller for LifeOS.

Home Assistant may request only ON/OFF over MQTT. This process owns the fixed
Wake-on-LAN and graceful-shutdown implementations. Configuration is root-owned
and deliberately supports no arbitrary shell command.

Three definitive observed states are exposed when an independent power probe is
configured:
  OFF                    -> physical power OFF (dashboard gray)
  POWERED_INACCESSIBLE   -> physical power ON, access probe failed (yellow)
  ACCESSIBLE             -> physical power ON and access probe passed (green)

If physical power cannot be independently established and the access probe also
fails, state is UNKNOWN rather than pretending the machine is off.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

CONFIG = Path(os.environ.get("LIFEOS_TOWER_CONFIG", "/etc/lifeos/tower.json"))
MQTT_HOST = os.environ.get("LIFEOS_MQTT_HOST", "127.0.0.1")
BASE = "lifeos/tower"
DISCOVERY = "homeassistant"
REFRESH = max(5, int(os.environ.get("LIFEOS_TOWER_REFRESH", "15")))
STOP = threading.Event()


def run(*args: str, check: bool = False, timeout: int = 20) -> subprocess.CompletedProcess:
    cp = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and cp.returncode:
        raise RuntimeError(f"{' '.join(args)} rc={cp.returncode}: {(cp.stderr or '').strip()[:500]}")
    return cp


def mqtt_pub(topic: str, payload: str, retain: bool = True) -> None:
    args = ["mosquitto_pub", "-h", MQTT_HOST, "-t", topic, "-m", payload]
    if retain:
        args.append("-r")
    run(*args, check=True)


def load_config() -> dict:
    try:
        value = json.loads(CONFIG.read_text())
    except FileNotFoundError:
        return {"configured": False}
    if not isinstance(value, dict):
        raise RuntimeError("tower config must be an object")
    return value


def tcp_probe(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def retained_mqtt_boolean(topic: str, on_values: list[str], off_values: list[str]) -> bool | None:
    cp = run("mosquitto_sub", "-h", MQTT_HOST, "-C", "1", "-W", "2", "-t", topic)
    if cp.returncode:
        return None
    value = cp.stdout.strip().lower()
    if value in {str(x).lower() for x in on_values}:
        return True
    if value in {str(x).lower() for x in off_values}:
        return False
    return None


def power_probe(cfg: dict) -> tuple[bool | None, str]:
    probe = cfg.get("power_probe") or {"type": "none"}
    ptype = str(probe.get("type") or "none")
    if ptype == "none":
        return None, "not_configured"
    if ptype == "mqtt_boolean":
        topic = str(probe.get("topic") or "")
        if not topic:
            return None, "mqtt_topic_missing"
        value = retained_mqtt_boolean(topic, probe.get("on_values", ["on", "true", "1"]), probe.get("off_values", ["off", "false", "0"]))
        return value, "mqtt_boolean"
    if ptype == "tcp_bmc":
        host, port = str(probe.get("host") or ""), int(probe.get("port") or 0)
        if not host or not port:
            return None, "bmc_endpoint_missing"
        return tcp_probe(host, port), "tcp_bmc"
    return None, "unsupported_power_probe"


def accessibility_probe(cfg: dict) -> tuple[bool, str]:
    probe = cfg.get("access_probe") or {}
    host = str(probe.get("host") or cfg.get("host") or "")
    port = int(probe.get("port") or 0)
    if not host or not port:
        return False, "not_configured"
    return tcp_probe(host, port), f"tcp:{host}:{port}"


def observed_state(cfg: dict) -> dict:
    configured = bool(cfg.get("mac") or cfg.get("host") or cfg.get("access_probe"))
    power, power_source = power_probe(cfg)
    accessible, access_source = accessibility_probe(cfg)
    # Successful application access is itself proof the PC is powered.
    if accessible:
        power = True
    if power is False:
        state, colour = "OFF", "gray"
    elif power is True and accessible:
        state, colour = "ACCESSIBLE", "green"
    elif power is True:
        state, colour = "POWERED_INACCESSIBLE", "yellow"
    else:
        state, colour = "UNKNOWN", "gray"
    switch_state = "ON" if power is True else "OFF" if power is False else "UNKNOWN"
    return {
        "state": state,
        "colour": colour,
        "configured": configured,
        "physical_power": "ON" if power is True else "OFF" if power is False else "UNKNOWN",
        "accessible": accessible,
        "power_source": power_source,
        "access_source": access_source,
        "switch_state": switch_state,
        "generated_at": int(time.time()),
    }


def send_wol(cfg: dict) -> None:
    mac = str(cfg.get("mac") or "").replace(":", "").replace("-", "").lower()
    if len(mac) != 12 or any(c not in "0123456789abcdef" for c in mac):
        raise RuntimeError("tower MAC is not configured")
    broadcast = str(cfg.get("broadcast") or "255.255.255.255")
    port = int(cfg.get("wol_port") or 9)
    packet = bytes.fromhex("ff" * 6 + mac * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))


def graceful_shutdown(cfg: dict) -> None:
    shutdown = cfg.get("shutdown") or {"type": "disabled"}
    stype = str(shutdown.get("type") or "disabled")
    if stype == "disabled":
        raise RuntimeError("Tower graceful shutdown is not configured")
    if stype not in {"linux_ssh", "windows_ssh"}:
        raise RuntimeError("unsupported Tower shutdown profile")
    host = str(shutdown.get("host") or cfg.get("host") or "")
    user = str(shutdown.get("user") or "")
    key = str(shutdown.get("key_file") or "")
    if not host or not user or not key or not Path(key).is_file():
        raise RuntimeError("Tower shutdown SSH endpoint/key is incomplete")
    remote = "sudo -n /sbin/poweroff" if stype == "linux_ssh" else "shutdown.exe /s /t 0"
    args = [
        "ssh", "-i", key, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=5",
        f"{user}@{host}", remote,
    ]
    run(*args, check=True, timeout=20)


def tower_device() -> dict:
    return {"identifiers": ["lifeos_tower"], "name": "Tower PC", "manufacturer": "LifeOS", "model": "Managed dependency"}


def publish_discovery() -> None:
    state = {
        "name": "Tower Status", "unique_id": "lifeos_tower_status_v1", "state_topic": f"{BASE}/state",
        "value_template": "{{ value_json.state }}", "json_attributes_topic": f"{BASE}/state", "icon": "mdi:server",
        "availability_topic": f"{BASE}/availability", "payload_available": "online", "payload_not_available": "offline", "device": tower_device(),
    }
    power = {
        "name": "Tower Power", "unique_id": "lifeos_tower_power_v1", "state_topic": f"{BASE}/power/state", "command_topic": f"{BASE}/power/set",
        "payload_on": "ON", "payload_off": "OFF", "state_on": "ON", "state_off": "OFF", "icon": "mdi:power",
        "availability_topic": f"{BASE}/availability", "payload_available": "online", "payload_not_available": "offline", "device": tower_device(),
    }
    accessible = {
        "name": "Tower Accessible", "unique_id": "lifeos_tower_accessible_v1", "state_topic": f"{BASE}/state",
        "value_template": "{{ 'ON' if value_json.accessible else 'OFF' }}", "payload_on": "ON", "payload_off": "OFF", "device_class": "connectivity",
        "availability_topic": f"{BASE}/availability", "payload_available": "online", "payload_not_available": "offline", "device": tower_device(),
    }
    mqtt_pub(f"{DISCOVERY}/sensor/lifeos_tower/status/config", json.dumps(state, separators=(",", ":")))
    mqtt_pub(f"{DISCOVERY}/switch/lifeos_tower/power/config", json.dumps(power, separators=(",", ":")))
    mqtt_pub(f"{DISCOVERY}/binary_sensor/lifeos_tower/accessible/config", json.dumps(accessible, separators=(",", ":")))


def publish_state() -> dict:
    value = observed_state(load_config())
    mqtt_pub(f"{BASE}/state", json.dumps(value, separators=(",", ":")))
    mqtt_pub(f"{BASE}/power/state", value["switch_state"])
    mqtt_pub(f"{BASE}/availability", "online")
    return value


def handle_command(payload: str) -> None:
    cfg = load_config()
    if payload == "ON":
        send_wol(cfg)
        print("TOWER_COMMAND=ON RESULT=ACCEPTED", flush=True)
    elif payload == "OFF":
        graceful_shutdown(cfg)
        print("TOWER_COMMAND=OFF RESULT=ACCEPTED", flush=True)
    else:
        raise RuntimeError("invalid Tower command")


def command_loop() -> None:
    while not STOP.is_set():
        proc = subprocess.Popen(["mosquitto_sub", "-h", MQTT_HOST, "-t", f"{BASE}/power/set"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while not STOP.is_set() and proc.poll() is None:
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    time.sleep(0.2)
                    continue
                payload = line.strip().upper()
                try:
                    handle_command(payload)
                except Exception as exc:
                    print(f"TOWER_COMMAND={payload} RESULT=BLOCKED REASON={type(exc).__name__}:{exc}", flush=True)
                publish_state()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not STOP.is_set():
            time.sleep(2)


def shutdown_signal(*_args) -> None:
    STOP.set()


def main() -> int:
    signal.signal(signal.SIGTERM, shutdown_signal)
    signal.signal(signal.SIGINT, shutdown_signal)
    publish_discovery()
    threading.Thread(target=command_loop, name="tower-command-listener", daemon=True).start()
    while not STOP.is_set():
        try:
            value = publish_state()
            print(f"TOWER_STATE={value['state']} POWER={value['physical_power']} ACCESSIBLE={'YES' if value['accessible'] else 'NO'} COLOUR={value['colour']}", flush=True)
        except Exception as exc:
            print(f"TOWER_REFRESH=FAIL TYPE={type(exc).__name__} REASON={exc}", flush=True)
        STOP.wait(REFRESH)
    try:
        mqtt_pub(f"{BASE}/availability", "offline")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
