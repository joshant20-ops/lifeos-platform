#!/usr/bin/env python3
"""Bounded, packet-level observation of the existing Tower controller WoL path.

This tool never constructs or sends a WoL packet. Capture mode only publishes a
short lease on the controller's existing MQTT topic and observes its traffic.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import pathlib
import selectors
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

CONFIG = pathlib.Path("/etc/lifeos/tower.json")
STATE_TOPIC = "lifeos/tower/state"
LEASE_PREFIX = "lifeos/tower/lease/"
CONTROLLER_UNIT = "lifeos-tower-control.service"
LEASE_WINDOW_SECONDS = 120
LEASE_TTL_SECONDS = LEASE_WINDOW_SECONDS + 10
NETWORK_POLL_SECONDS = 4
ICMP_POLL_SECONDS = 20


def fail(message: str, code: int = 2) -> None:
    print(f"DIAGNOSTIC_RESULT=BLOCKED REASON={message}", flush=True)
    raise SystemExit(code)


def command(args: list[str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def read_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text())
    except Exception as exc:
        fail(f"CONFIG_READ_{type(exc).__name__}")
    if not isinstance(cfg, dict):
        fail("CONFIG_NOT_OBJECT")
    mac = str(cfg.get("mac") or "").replace(":", "").replace("-", "").lower()
    if len(mac) != 12 or any(ch not in "0123456789abcdef" for ch in mac):
        fail("CONFIGURED_TOWER_MAC_INVALID")
    broadcast = str(cfg.get("broadcast") or "").strip()
    try:
        ipaddress.IPv4Address(broadcast)
    except Exception:
        fail("CONFIGURED_WOL_DESTINATION_INVALID")
    try:
        port = int(cfg.get("wol_port") or 0)
    except Exception:
        fail("CONFIGURED_WOL_PORT_INVALID")
    if not 1 <= port <= 65535:
        fail("CONFIGURED_WOL_PORT_INVALID")
    probe = cfg.get("access_probe") if isinstance(cfg.get("access_probe"), dict) else {}
    host = str(probe.get("host") or cfg.get("host") or "").strip()
    try:
        address = ipaddress.IPv4Address(host)
    except Exception:
        fail("CONFIGURED_ACCESS_HOST_NOT_IPV4")
    access_port = int(probe.get("port") or 22)
    return {
        "mac": ":".join(mac[i:i+2] for i in range(0, 12, 2)),
        "mac_bytes": bytes.fromhex(mac),
        "broadcast": broadcast,
        "wol_port": port,
        "host": str(address),
        "access_port": access_port,
    }


def route_for(destination: str) -> tuple[str, str]:
    cp = command(["ip", "-4", "route", "get", destination])
    if cp.returncode:
        fail("ROUTE_LOOKUP_FAILED")
    words = cp.stdout.split()
    try:
        dev = words[words.index("dev") + 1]
        src = words[words.index("src") + 1]
        ipaddress.IPv4Address(src)
    except Exception:
        fail("ROUTE_INTERFACE_OR_SOURCE_MISSING")
    return dev, src


def state_snapshot() -> dict:
    cp = command(["mosquitto_sub", "-h", "127.0.0.1", "-C", "1", "-W", "3", "-t", STATE_TOPIC], timeout=5)
    if cp.returncode:
        fail("TOWER_STATE_UNAVAILABLE")
    try:
        return json.loads(cp.stdout.strip())
    except Exception:
        fail("TOWER_STATE_INVALID")


def identity(cfg: dict, iface: str, source: str) -> str:
    obj = {k: cfg[k] for k in ("mac", "broadcast", "wol_port", "host", "access_port")}
    obj.update({"interface": iface, "source_ip": source})
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def inspect(cfg: dict, iface: str, source: str, state: dict) -> bool:
    print(f"PI_INTERFACE={iface}")
    print(f"PI_SOURCE_IP={source}")
    print(f"TOWER_MAC={cfg['mac']}")
    print(f"WOL_DESTINATION_IP={cfg['broadcast']}")
    print(f"WOL_UDP_PORT={cfg['wol_port']}")
    print(f"READINESS_HOST={cfg['host']}")
    print(f"READINESS_TCP_PORT={cfg['access_port']}")
    print(f"TOWER_STATE={state.get('state', 'UNKNOWN')}")
    print(f"TOWER_ACCESSIBLE={'YES' if state.get('accessible') else 'NO'}")
    print(f"ACTIVE_LEASES={state.get('active_leases', 'UNKNOWN')}")
    print(f"LAST_WAKE_AT={state.get('last_wake_at') or 'none'}")
    print(f"CONFIG_FINGERPRINT={identity(cfg, iface, source)}")
    tcpdump = shutil.which("tcpdump")
    print(f"TCPDUMP_PATH={tcpdump or 'missing'}")
    if not tcpdump:
        print("CAPTURE_READY=NO")
        return False
    # Open and immediately stop the exact outbound capture filter. This verifies
    # existing capture privilege without sending traffic or installing software.
    filt = f"udp and dst host {cfg['broadcast']} and dst port {cfg['wol_port']}"
    with tempfile.NamedTemporaryFile(prefix="lifeos-wol-probe-", suffix=".pcap", delete=False) as f:
        probe_path = f.name
    try:
        proc = subprocess.Popen(
            [tcpdump, "-i", iface, "-Q", "out", "-nn", "-s", "0", "-w", probe_path, filt],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        time.sleep(0.6)
        output = ""
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                output = proc.communicate(timeout=3)[0] or ""
            except subprocess.TimeoutExpired:
                proc.kill()
                output = proc.communicate()[0] or ""
            ready = proc.returncode in (0, 130)
        else:
            output = proc.communicate()[0] or ""
            ready = proc.returncode == 0
        if not ready:
            for line in output.splitlines():
                if "permission" in line.lower() or "capabilit" in line.lower() or "error" in line.lower():
                    print("CAPTURE_PROBE_ERROR=" + " ".join(line.split())[:240])
            print("CAPTURE_READY=NO")
            return False
        print("CAPTURE_READY=YES")
        return True
    finally:
        try:
            os.unlink(probe_path)
        except FileNotFoundError:
            pass


def parse_pcap(path: str, target_mac: bytes, port: int, destination: str) -> list[dict]:
    raw = pathlib.Path(path).read_bytes()
    if len(raw) < 24:
        return []
    magic = raw[:4]
    formats = {
        b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
        b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
        b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
        b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
    }
    if magic not in formats:
        fail("PCAP_FORMAT_UNSUPPORTED")
    endian, scale = formats[magic]
    linktype = struct.unpack(endian + "I", raw[20:24])[0]
    if linktype != 1:
        fail(f"PCAP_LINKTYPE_UNSUPPORTED_{linktype}")
    frames = []
    offset = 24
    expected = b"\xff" * 6 + target_mac * 16
    while offset + 16 <= len(raw):
        sec, fraction, caplen, _ = struct.unpack(endian + "IIII", raw[offset:offset + 16])
        offset += 16
        frame = raw[offset:offset + caplen]
        offset += caplen
        if len(frame) < 14:
            continue
        dst_mac, src_mac = frame[:6], frame[6:12]
        etype = struct.unpack("!H", frame[12:14])[0]
        ipoff = 14
        while etype in (0x8100, 0x88A8, 0x9100):
            if len(frame) < ipoff + 4:
                break
            etype = struct.unpack("!H", frame[ipoff + 2:ipoff + 4])[0]
            ipoff += 4
        if etype != 0x0800 or len(frame) < ipoff + 20:
            continue
        version_ihl = frame[ipoff]
        if version_ihl >> 4 != 4:
            continue
        ihl = (version_ihl & 15) * 4
        if ihl < 20 or len(frame) < ipoff + ihl + 8:
            continue
        if frame[ipoff + 9] != 17:
            continue
        src_ip = socket.inet_ntoa(frame[ipoff + 12:ipoff + 16])
        dst_ip = socket.inet_ntoa(frame[ipoff + 16:ipoff + 20])
        udp = ipoff + ihl
        src_port, dst_port, udp_len = struct.unpack("!HHH", frame[udp:udp + 6])
        if dst_port != port or dst_ip != destination:
            continue
        payload = frame[udp + 8:min(udp + udp_len, len(frame))]
        valid = payload == expected
        stamp = dt.datetime.fromtimestamp(sec + fraction / scale, tz=dt.timezone.utc)
        frames.append({
            "timestamp": stamp.isoformat(),
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_mac": ":".join(f"{x:02x}" for x in src_mac),
            "dst_mac": ":".join(f"{x:02x}" for x in dst_mac),
            "src_port": src_port,
            "dst_port": dst_port,
            "payload_bytes": len(payload),
            "payload_valid": valid,
            "repetitions": 16 if valid else 0,
            "payload_hex": payload.hex(),
        })
    return frames


def publish_lease(lease_id: str, state: str, expires_at: int) -> None:
    payload = json.dumps({"owner": "github-1588-wol-packet-diagnostic", "state": state, "expires_at": expires_at}, separators=(",", ":"))
    cp = command(["mosquitto_pub", "-h", "127.0.0.1", "-t", LEASE_PREFIX + lease_id, "-r", "-m", payload])
    if cp.returncode:
        fail("LEASE_PUBLISH_FAILED")


def parse_marker_timestamp(line: str) -> str:
    token = line.split(maxsplit=1)[0]
    try:
        return dt.datetime.fromisoformat(token.replace("Z", "+00:00")).astimezone(dt.timezone.utc).isoformat()
    except Exception:
        return "unparsed"


def tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def wake_window_complete(started_at: float, now: float, readiness_observed: bool) -> bool:
    return readiness_observed or now - started_at >= LEASE_WINDOW_SECONDS


def monitor(
    cfg: dict,
    started_at: float,
    on_tick=None,
) -> dict:
    deadline = started_at + LEASE_WINDOW_SECONDS
    next_ping = started_at
    next_observation = started_at
    last_icmp = None
    last_result = None
    first_tcp22_ready = None
    first_ollama_ready = None
    first_ready = None

    while not wake_window_complete(started_at, time.monotonic(), first_ready is not None):
        if on_tick:
            on_tick()
        now = time.monotonic()
        if now >= next_observation and deadline - now >= 5:
            if now >= next_ping:
                ping = command(["ping", "-c", "1", "-W", "1", cfg["host"]], timeout=3)
                last_icmp = ping.returncode == 0
                next_ping = now + ICMP_POLL_SECONDS
            neigh = command(["ip", "neigh", "show", cfg["host"]], timeout=1).stdout.strip()
            ssh = tcp_open(cfg["host"], cfg["access_port"])
            ollama = tcp_open(cfg["host"], 11434)
            observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
            current = {
                "neigh": neigh or "absent",
                "icmp": last_icmp,
                "tcp_ssh": ssh,
                "tcp_ollama": ollama,
            }
            elapsed = round(time.monotonic() - started_at, 3)
            if ssh and first_tcp22_ready is None:
                first_tcp22_ready = {"at_utc": observed_at, "elapsed_seconds": elapsed}
                print(f"TOWER_TCP22_READY_UTC={observed_at}", flush=True)
                print(f"LEASE_TO_TCP22_SECONDS={elapsed:.3f}", flush=True)
            if ollama and first_ollama_ready is None:
                first_ollama_ready = {"at_utc": observed_at, "elapsed_seconds": elapsed}
                print(f"TOWER_OLLAMA_READY_UTC={observed_at}", flush=True)
                print(f"LEASE_TO_OLLAMA_SECONDS={elapsed:.3f}", flush=True)
            if ssh and ollama and first_ready is None:
                first_ready = {
                    "at_utc": observed_at,
                    "elapsed_seconds": elapsed,
                    "tcp_ssh": True,
                    "tcp_ollama": True,
                }
                print(f"TOWER_FULL_READINESS_UTC={observed_at}", flush=True)
                print(f"LEASE_TO_FIRST_READINESS_SECONDS={elapsed:.3f}", flush=True)
            if current != last_result:
                print(
                    "NETWORK_OBSERVATION="
                    + json.dumps({"at_utc": observed_at, **current}, sort_keys=True),
                    flush=True,
                )
                last_result = current
            next_observation = time.monotonic() + NETWORK_POLL_SECONDS
        if on_tick:
            on_tick()
        remaining = deadline - time.monotonic()
        if remaining > 0 and first_ready is None:
            time.sleep(min(0.25, remaining))

    if on_tick:
        on_tick()
    return {
        "first_tcp22_ready": first_tcp22_ready,
        "first_ollama_ready": first_ollama_ready,
        "first_ready": first_ready,
        "seconds": round(time.monotonic() - started_at, 3),
        "window_seconds": LEASE_WINDOW_SECONDS,
        "last": last_result,
    }


def capture(cfg: dict, iface: str, source: str, fingerprint: str, expected: str, run_id: str) -> int:
    if fingerprint != expected:
        fail("CONFIG_FINGERPRINT_CHANGED_SINCE_INSPECTION")
    state = state_snapshot()
    generated = int(state.get("generated_at") or 0)
    if not generated or abs(int(time.time()) - generated) > 35:
        fail("TOWER_STATE_SNAPSHOT_STALE")
    if int(state.get("active_leases") or 0) != 0:
        fail("OTHER_ACTIVE_TOWER_LEASES_PRESENT")
    tcpdump = shutil.which("tcpdump")
    if not tcpdump:
        fail("TCPDUMP_UNAVAILABLE")
    filter_expr = f"udp and dst host {cfg['broadcast']} and dst port {cfg['wol_port']}"
    with tempfile.NamedTemporaryFile(prefix="lifeos-wol-", suffix=".pcap", delete=False) as f:
        pcap_path = f.name
    lease_id = "lifeos-1588-wol-diag-" + "".join(c for c in run_id if c.isalnum())[:24]
    proc = None
    journal = None
    markers = []
    lease_published = False
    try:
        journal = subprocess.Popen(
            ["journalctl", "-f", "-n", "0", "-u", CONTROLLER_UNIT, "-o", "short-iso", "--no-pager"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1,
        )
        if journal.poll() is not None or journal.stdout is None:
            fail("CONTROLLER_JOURNAL_FOLLOW_UNAVAILABLE")
        proc = subprocess.Popen(
            [tcpdump, "-i", iface, "-Q", "out", "-nn", "-e", "-s", "0", "-w", pcap_path, filter_expr],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        time.sleep(0.7)
        if proc.poll() is not None:
            out = proc.communicate()[0] or ""
            fail("CAPTURE_START_FAILED_" + " ".join(out.split())[:160])
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        print(f"CAPTURE_STARTED_UTC={started}")
        print(f"CAPTURE_INTERFACE={iface}")
        print(f"CAPTURE_FILTER={filter_expr}")
        selector = selectors.DefaultSelector()
        selector.register(journal.stdout, selectors.EVENT_READ)

        def drain_markers() -> None:
            while True:
                events = selector.select(timeout=0)
                if not events:
                    return
                key, _ = events[0]
                line = key.fileobj.readline()
                if "TOWER_COMPUTE_WAKE=REQUESTED" in line:
                    marker = {"line": " ".join(line.split()), "at_utc": parse_marker_timestamp(line)}
                    markers.append(marker)
                    print("CONTROLLER_WAKE_MARKER=" + json.dumps(marker, sort_keys=True), flush=True)

        publish_lease(lease_id, "active", int(time.time()) + LEASE_TTL_SECONDS)
        lease_published = True
        lease_started_at = time.monotonic()
        lease_published_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        print(f"LEASE_PUBLISHED_UTC={lease_published_utc}")
        print(f"LEASE_WINDOW_SECONDS={LEASE_WINDOW_SECONDS}")
        outcome = monitor(cfg, lease_started_at, on_tick=drain_markers)
        drain_markers()
        publish_lease(lease_id, "released", 0)
        lease_published = False
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        frames = parse_pcap(pcap_path, cfg["mac_bytes"], cfg["wol_port"], cfg["broadcast"])
        print(f"CONTROLLER_WAKE_MARKER_COUNT={len(markers)}")
        print(f"WOL_PACKET_COUNT={len(frames)}")
        previous_packet_time = None
        marker_times = [
            dt.datetime.fromisoformat(marker["at_utc"])
            for marker in markers
            if marker.get("at_utc") != "unparsed"
        ]
        for i, frame in enumerate(frames, 1):
            print(f"WOL_PACKET_{i}=" + json.dumps({k: v for k, v in frame.items() if k != "payload_hex"}, sort_keys=True))
            print(f"WOL_PACKET_{i}_PAYLOAD_HEX={frame['payload_hex']}")
            packet_time = dt.datetime.fromisoformat(frame["timestamp"])
            if previous_packet_time is not None:
                print(f"WOL_PACKET_INTERVAL_{i}_SECONDS={(packet_time-previous_packet_time).total_seconds():.3f}")
            previous_packet_time = packet_time
            if marker_times:
                nearest_marker = min(marker_times, key=lambda stamp: abs((packet_time-stamp).total_seconds()))
                print(f"WOL_PACKET_{i}_NEAREST_MARKER_DELTA_SECONDS={(packet_time-nearest_marker).total_seconds():.3f}")
        if not markers:
            print("WAKE_PATH_RESULT=NO_CONTROLLER_WAKE_MARKER")
        elif not frames:
            print("WAKE_PATH_RESULT=MARKER_WITHOUT_CAPTURED_PACKET")
        elif all(frame["payload_valid"] for frame in frames):
            print(f"WAKE_PATH_RESULT=ALL_{len(frames)}_CAPTURED_MAGIC_PACKETS_VALID_ON_PI_EGRESS")
        else:
            print("WAKE_PATH_RESULT=PACKET_COUNT_OR_PAYLOAD_REQUIRES_REVIEW")
        print("NETWORK_MONITOR_RESULT=" + json.dumps(outcome, sort_keys=True), flush=True)
        if outcome["first_ready"] is None:
            print(f"TOWER_NETWORK_READINESS=NOT_OBSERVED_WITHIN_{LEASE_WINDOW_SECONDS}S")
        else:
            print("TOWER_NETWORK_READINESS=OBSERVED")
        print("DIAGNOSTIC_RESULT=COMPLETE", flush=True)
        return 0
    finally:
        if lease_published:
            try:
                publish_lease(lease_id, "released", 0)
            except Exception:
                pass
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.communicate(timeout=3)
            except Exception:
                proc.kill()
        if journal and journal.poll() is None:
            journal.terminate()
            try:
                journal.wait(timeout=3)
            except subprocess.TimeoutExpired:
                journal.kill()
        try:
            os.unlink(pcap_path)
        except FileNotFoundError:
            pass


def main() -> int:
    mode = ""
    expected = ""
    run_id = ""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
        elif arg == "--expected-fingerprint" and i + 1 < len(args):
            expected = args[i + 1]
        elif arg == "--run-id" and i + 1 < len(args):
            run_id = args[i + 1]
    if mode not in {"inspect", "capture"}:
        fail("MODE_INVALID")
    cfg = read_config()
    iface, source = route_for(cfg["broadcast"])
    state = state_snapshot()
    ready = inspect(cfg, iface, source, state)
    if mode == "inspect":
        print("DIAGNOSTIC_MODE=READ_ONLY_INSPECT")
        print("DIAGNOSTIC_RESULT=" + ("INSPECTION_READY" if ready else "INSPECTION_CAPTURE_UNAVAILABLE"))
        return 0
    if not expected or not run_id:
        fail("CAPTURE_REQUIRES_INSPECTION_FINGERPRINT_AND_RUN_ID")
    if not ready:
        fail("CAPTURE_PRIVILEGE_NOT_AVAILABLE")
    print("DIAGNOSTIC_MODE=BOUNDED_CONTROLLER_LEASE_WINDOW")
    return capture(cfg, iface, source, identity(cfg, iface, source), expected, run_id)


if __name__ == "__main__":
    raise SystemExit(main())
