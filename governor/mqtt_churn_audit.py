"""Bounded, read-only MQTT connection and process attribution on the Pi."""
from collections import Counter
from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

from governor.mqtt_rotation_preflight import CONTAINER, LOG, inspect

LIMIT = 4 * 1024**2
SESSION = re.compile(rb"^\d+: (New connection from |New client connected from |Client .+ disconnected)")
PROCESS = re.compile(r"\bpid=(\d+)\b")
PACKET = re.compile(rb"\bIP ((?:[0-9]+\.){3}[0-9]+)\.([0-9]+) > ((?:[0-9]+\.){3}[0-9]+)\.1883:")
KNOWN_CONTAINERS = {"homeassistant", "predbat", "mosquitto"}
KNOWN_CALLERS = {
    b"tower_metrics.py": "tower_metrics",
    b"tower_control.py": "tower_control",
    b"openhands_local_ai_gateway.py": "openhands_local_ai_gateway",
    b"ai_broker.py": "ai_broker",
    b"ha_issue_queue_bridge.py": "ha_issue_queue_bridge",
    b"lifeos_important_info_daily_refresh.py": "important_info_refresh",
}


def classify_records(raw, gateways):
    result = Counter()
    for line in raw.splitlines():
        match = SESSION.match(line)
        if match:
            kind = match[1]
            if kind.startswith(b"New connection"):
                result["socket_connections"] += 1
                source = line[match.end():].split(b" ", 1)[0].rsplit(b":", 1)[0]
                if source in gateways:
                    result["gateway_socket_connections"] += 1
                elif source in {b"127.0.0.1", b"[::1]", b"::1"}:
                    result["loopback_socket_connections"] += 1
            elif kind.startswith(b"New client"):
                result["mqtt_connected"] += 1
            else:
                result["mqtt_disconnected"] += 1
        elif b"Outgoing messages are being dropped" in line:
            result["outgoing_drop_warnings"] += 1
    return result


def known_caller(pid):
    root = Path("/proc") / str(pid)
    try:
        status = (root / "stat").read_text().rsplit(")", 1)[1].split()
        parent = Path("/proc") / str(int(status[1]))
        for proc in (root, parent):
            with (proc / "cmdline").open("rb") as stream:
                args = stream.read(4096).split(b"\0")
            for arg in args:
                label = KNOWN_CALLERS.get(os.path.basename(arg))
                if label:
                    return label
        with (root / "comm").open("rb") as stream:
            executable = stream.read(64).strip()
        return {b"mosquitto_pub": "unattributed_mqtt_publisher",
                b"mosquitto_sub": "unattributed_mqtt_subscriber",
                b"docker-proxy": "docker_proxy"}.get(executable, "other_process")
    except (OSError, ValueError, IndexError):
        return "process_exited_or_unavailable"


@contextmanager
def packet_capture():
    tool = Path("/usr/bin/tcpdump")
    if not tool.is_file():
        tool = Path("/usr/sbin/tcpdump")
    with tempfile.TemporaryFile(dir="/dev/shm") as sample:
        process = None
        if tool.is_file():
            process = subprocess.Popen(
                [str(tool), "-i", "any", "-p", "-nn", "-l", "-s", "80", "-c", "1500",
                 "tcp dst port 1883 and tcp[tcpflags] & tcp-syn != 0"],
                stdin=subprocess.DEVNULL, stdout=sample, stderr=subprocess.DEVNULL,
            )
        def finish():
            if process is None:
                return "tcpdump_unavailable", b""
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            sample.seek(0)
            return ("observed" if process.returncode in (0, -15) else "capture_unavailable",
                    sample.read(512 * 1024))

        try:
            yield finish
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=2)


def classify_packets(raw, gateways, containers):
    counts = Counter()
    seen = set()
    for match in PACKET.finditer(raw):
        key = match.groups()
        if key in seen:
            continue
        seen.add(key)
        address = key[0]
        if address in gateways:
            label = "docker_gateway"
        elif address in containers:
            label = containers[address]
        elif address == b"127.0.0.1":
            label = "loopback"
        else:
            try:
                local = ipaddress.IPv4Address(address.decode()).is_private
            except ValueError:
                continue
            label = "other_private_source" if local else "other_source"
        counts[label] += 1
    return counts



def audit(window=24):
    broker = inspect("container", CONTAINER)
    identity = (broker["Id"], broker["State"]["Pid"], broker["State"]["StartedAt"])
    gateways = set()
    containers = {}
    for name, network in broker["NetworkSettings"]["Networks"].items():
        address = network.get("Gateway")
        if address:
            gateways.add(str(ipaddress.IPv4Address(address)).encode())
        network_state = inspect("network", name)
        for member in (network_state.get("Containers") or {}).values():
            address = member.get("IPv4Address", "").partition("/")[0]
            if address:
                candidate = member.get("Name")
                containers[address.encode()] = candidate if candidate in KNOWN_CONTAINERS else "other_container"
    fd = os.open(LOG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as log, packet_capture() as finish_capture:
        initial = os.fstat(fd)
        if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
            raise ValueError("active_log_unverified")
        start = time.monotonic()
        deadline = start + window
        visible = Counter()
        observed = failed = 0
        while time.monotonic() < deadline:
            sockets = subprocess.run(
                ["/usr/bin/ss", "-Hntp", "( dport = :1883 )"], capture_output=True,
                text=True, timeout=3, check=False,
            )
            failed += int(sockets.returncode != 0)
            for pid in set(PROCESS.findall(sockets.stdout)) if not sockets.returncode else ():
                visible[known_caller(int(pid))] += 1
            observed += 1
            time.sleep(0.5)
        capture_status, packets = finish_capture()
        latest = inspect("container", CONTAINER)
        if identity != (latest["Id"], latest["State"]["Pid"], latest["State"]["StartedAt"]):
            raise ValueError("broker_changed")
        after = LOG.lstat()
        if (after.st_dev, after.st_ino) != (initial.st_dev, initial.st_ino) or after.st_size < initial.st_size:
            raise ValueError("active_log_changed")
        delta = after.st_size - initial.st_size
        log.seek(initial.st_size)
        sample = log.read(min(delta, LIMIT))
        # Discard partial records at the sample edges.
        if initial.st_size:
            log.seek(initial.st_size - 1)
            if log.read(1) != b"\n":
                _, _, sample = sample.partition(b"\n")
        if not sample.endswith(b"\n"):
            sample = sample.rpartition(b"\n")[0]
        return {"status": "mqtt_churn_observed", "window_seconds": round(time.monotonic() - start, 1),
                "active_log_growth_bytes": delta, "sample_limited": delta > LIMIT,
                "event_lines": dict(classify_records(sample, gateways)),
                "packet_capture_status": capture_status,
                "tcp_syn_source_classes": dict(classify_packets(packets, gateways, containers)),
                "host_socket_samples": observed - failed, "host_socket_sample_failures": failed, "visible_caller_observations": dict(visible)}


def main():
    try:
        report = audit()
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as error:
        report = {"status": "mqtt_churn_audit_unavailable", "error_type": type(error).__name__}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "mqtt_churn_observed" else 2
