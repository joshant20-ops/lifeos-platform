#!/usr/bin/env python3
"""Add the stable AI name as an AdGuard Home DNS rewrite to this Pi."""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import time
import fcntl
import json
import urllib.error
import urllib.request

CONFIG = pathlib.Path("/opt/stacks/adguard/conf/AdGuardHome.yaml")
HOSTNAME = "ai.lan"


def pi_ipv4() -> str:
    route = subprocess.run(
        ["ip", "-4", "route", "get", "1.1.1.1"], check=True,
        capture_output=True, text=True, timeout=5,
    ).stdout
    match = re.search(r"\bsrc\s+(\d{1,3}(?:\.\d{1,3}){3})\b", route)
    if not match:
        raise RuntimeError("Pi LAN source address is unavailable")
    return match.group(1)


def rewrite_section(lines: list[str]) -> tuple[int, int]:
    section = "filtering" if any(re.match(r"^filtering:\s*(?:#.*)?$", line) for line in lines) else "dns"
    start = next((i for i, line in enumerate(lines) if re.match(rf"^{section}:\s*(?:#.*)?$", line)), None)
    if start is None:
        raise RuntimeError("AdGuard config has no top-level filtering or dns section")
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")), len(lines))
    return start, end


def rewrite_config(text: str, address: str) -> str:
    lines = text.splitlines()
    start, end = rewrite_section(lines)
    rewrite = next((i for i in range(start + 1, end) if re.match(r"^  rewrites:\s*(?:\[\])?\s*(?:#.*)?$", lines[i])), None)
    entry = [f"    - domain: {HOSTNAME}", f"      answer: {address}"]
    if rewrite is None:
        lines[start + 1:start + 1] = ["  rewrites:", *entry]
    else:
        if re.match(r"^  rewrites:\s*\[\]", lines[rewrite]):
            lines[rewrite:rewrite + 1] = ["  rewrites:", *entry]
            return "\n".join(lines) + "\n"
        key_end = next((i for i in range(rewrite + 1, end) if lines[i] and len(lines[i]) - len(lines[i].lstrip()) <= 2), end)
        found = next((i for i in range(rewrite + 1, key_end) if re.match(rf"^\s+-\s+domain:\s*['\"]?{re.escape(HOSTNAME)}['\"]?\s*$", lines[i])), None)
        if found is not None:
            indent = len(lines[found]) - len(lines[found].lstrip())
            item_end = next((i for i in range(found + 1, key_end) if lines[i].lstrip().startswith("-") and len(lines[i]) - len(lines[i].lstrip()) == indent), key_end)
            child_indent = " " * indent
            lines[found:item_end] = [f"{child_indent}- domain: {HOSTNAME}", f"{child_indent}  answer: {address}"]
        else:
            lines[key_end:key_end] = entry
    return "\n".join(lines) + "\n"


def adguard_ipv4_answers(name: str, resolver: str) -> tuple[set[str], str]:
    request_id = int.from_bytes(os.urandom(2), "big")
    labels = b"".join(bytes([len(label)]) + label.encode("ascii") for label in name.split(".")) + b"\0"
    query = struct.pack("!HHHHHH", request_id, 0x0100, 1, 0, 0, 0) + labels + struct.pack("!HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(3)
        client.sendto(query, (resolver, 53))
        response, _ = client.recvfrom(4096)
    ident, flags, _questions, answers, _authority, _additional = struct.unpack("!HHHHHH", response[:12])
    if ident != request_id:
        return set(), "id_mismatch"

    def skip_name(offset: int) -> int:
        while offset < len(response):
            size = response[offset]
            if size & 0xC0 == 0xC0:
                return offset + 2
            offset += 1
            if size == 0:
                return offset
            offset += size
        raise RuntimeError("Malformed AdGuard DNS response")

    offset = skip_name(12)
    offset += 4
    found = set()
    for _ in range(answers):
        offset = skip_name(offset)
        rtype, rclass, _ttl, length = struct.unpack("!HHIH", response[offset:offset + 10])
        offset += 10
        value = response[offset:offset + length]
        if rtype == 1 and rclass == 1 and length == 4:
            found.add(socket.inet_ntoa(value))
        offset += length
    return found, f"rcode={flags & 0x000F} answers={answers} A={','.join(sorted(found)) or 'none'}"


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("AdGuard DNS configuration requires the allow-listed root gateway")
    if not CONFIG.is_file() or CONFIG.is_symlink():
        raise RuntimeError("AdGuard Home config is missing or not a regular file")
    for directory in (CONFIG.parent, CONFIG.parent.parent, CONFIG.parent.parent.parent):
        parent_stat = directory.lstat()
        root_protected = parent_stat.st_uid == 0 and not parent_stat.st_mode & 0o022
        trusted_adguard_dir = (
            directory in (CONFIG.parent.parent, CONFIG.parent.parent.parent)
            and parent_stat.st_uid == 1000
            and not parent_stat.st_mode & 0o002
        )
        if not directory.is_dir() or directory.is_symlink() or not (root_protected or trusted_adguard_dir):
            raise RuntimeError(f"AdGuard config parent is not protected: {directory} uid={parent_stat.st_uid} mode={stat.S_IMODE(parent_stat.st_mode):04o} symlink={directory.is_symlink()}")
    original = CONFIG.stat()
    if original.st_uid != 0:
        raise RuntimeError("AdGuard Home config is not root-owned")
    container = subprocess.run(
        ["docker", "inspect", "--format={{.State.Running}}", "adguardhome"],
        check=True, capture_output=True, text=True, timeout=5,
    )
    if container.stdout.strip().lower() != "true":
        raise RuntimeError("AdGuard Home container is not running")
    network = subprocess.run(
        ["docker", "inspect", "--format={{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", "adguardhome"],
        check=True, capture_output=True, text=True, timeout=5,
    )
    container_resolvers = [value for value in network.stdout.split() if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value)]
    lock_path = pathlib.Path("/run/lock/lifeos-ai-dns.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    lock_stat = os.fstat(fd)
    if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != 0 or lock_stat.st_mode & 0o022:
        os.close(fd)
        raise RuntimeError("AdGuard DNS lock file is not a protected root-owned regular file")
    with os.fdopen(fd, "r+", encoding="ascii") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return configure_locked(original, container_resolvers)


def configure_locked(original, container_resolvers: list[str]) -> int:
    old = CONFIG.read_text(encoding="utf-8")
    expected = pi_ipv4()
    new = rewrite_config(old, expected)
    if new != old:
        backup = CONFIG.with_name(f"AdGuardHome.yaml.ai-dns-backup-{time.time_ns()}")
        shutil.copy2(CONFIG, backup)
        subprocess.run(["docker", "stop", "adguardhome"], check=True, capture_output=True, text=True, timeout=30)
        try:
            fd, temp_name = tempfile.mkstemp(prefix=".AdGuardHome.ai-dns.", dir=CONFIG.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(new)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temp_name, CONFIG.stat().st_mode & 0o777)
                os.chown(temp_name, original.st_uid, original.st_gid)
                os.replace(temp_name, CONFIG)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            subprocess.run(["docker", "start", "adguardhome"], check=True, capture_output=True, text=True, timeout=30)
        except Exception:
            subprocess.run(["docker", "stop", "adguardhome"], check=False, capture_output=True, text=True, timeout=30)
            shutil.copy2(backup, CONFIG)
            subprocess.run(["docker", "start", "adguardhome"], check=False, capture_output=True, text=True, timeout=30)
            raise

    persisted = CONFIG.read_text(encoding="utf-8")
    rewrite_section_name = "filtering" if re.search(r"^filtering:\s*(?:#.*)?$", persisted, re.MULTILINE) else "dns"
    rewrite_entry = re.search(
        rf"(?m)^\s+- domain:\s*{re.escape(HOSTNAME)}\s*$\n^\s+answer:\s*{re.escape(expected)}\s*$",
        persisted,
    )
    image = subprocess.run(
        ["docker", "inspect", "--format={{.Config.Image}}", "adguardhome"],
        check=True, capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    mount_info = subprocess.run(
        ["docker", "inspect", "--format={{range .Mounts}}{{.Source}}=>{{.Destination}};{{end}}", "adguardhome"],
        check=True, capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    binary_version = subprocess.run(
        ["docker", "exec", "adguardhome", "/opt/adguardhome/AdGuardHome", "--version"],
        check=False, capture_output=True, text=True, timeout=5,
    )
    http_match = re.search(r'(?ms)^http:\s*\n(?:(?:^  [^\n]*\n)|(?:^\n))*?^    address:\s*([^\s#]+)', persisted)
    bind_match = re.search(r'(?m)^bind_port:\s*(\d+)', persisted)
    configured_address = http_match.group(1).strip("'\"") if http_match else ""
    configured_port = configured_address.rsplit(":", 1)[-1] if ":" in configured_address else (bind_match.group(1) if bind_match else "")
    api_bases = [f"http://{host}:{configured_port}" for host in (expected, "127.0.0.1")] if configured_port.isdigit() else []
    api_results = {}
    for api_path in ("/control/rewrite/list", "/control/rewrite/settings"):
        for api_base in api_bases:
            try:
                with urllib.request.urlopen(f"{api_base}{api_path}", timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    if api_path.endswith("/list"):
                        api_results["list"] = f"{response.status}:exact_entry={any(item.get('domain') == HOSTNAME and item.get('answer') == expected for item in payload if isinstance(item, dict))}"
                    else:
                        api_results["settings"] = f"{response.status}:enabled={payload.get('enabled')}"
                    break
            except urllib.error.HTTPError as error:
                api_results["list" if api_path.endswith("/list") else "settings"] = str(error.code)
                break
            except Exception as error:
                api_results["list" if api_path.endswith("/list") else "settings"] = type(error).__name__
    print(f"ADGUARD_IMAGE={image}")
    print(f"ADGUARD_MOUNTS={mount_info}")
    print(f"ADGUARD_VERSION={(binary_version.stdout or binary_version.stderr).strip()[:200] or 'unavailable'}")
    print(f"ADGUARD_CONFIG_SECTION={rewrite_section_name} ENTRY_AFTER_START={'PASS' if rewrite_entry else 'FAIL'}")
    print(f"ADGUARD_REWRITE_API=list:{api_results.get('list')} settings:{api_results.get('settings')}")
    resolvers = list(dict.fromkeys([*container_resolvers, expected, "127.0.0.1"]))
    diagnostics: dict[str, str] = {}
    for _ in range(20):
        for resolver in resolvers:
            try:
                answers, response = adguard_ipv4_answers(HOSTNAME, resolver)
                diagnostics[resolver] = response
                if expected in answers:
                    print(f"ADGUARD_AI_DNS={HOSTNAME}->{expected} RESOLVER={resolver} PASS")
                    return 0
            except OSError as error:
                diagnostics[resolver] = type(error).__name__
        time.sleep(1)
    print("ADGUARD_DNS_DIAGNOSTICS=" + ";".join(f"{resolver}:{diagnostics.get(resolver, 'no_response')}" for resolver in resolvers))
    if new != old:
        subprocess.run(["docker", "stop", "adguardhome"], check=False, capture_output=True, text=True, timeout=30)
        shutil.copy2(backup, CONFIG)
        subprocess.run(["docker", "start", "adguardhome"], check=False, capture_output=True, text=True, timeout=30)
    raise RuntimeError(f"AdGuard did not resolve {HOSTNAME} to the Pi address {expected}")


if __name__ == "__main__":
    raise SystemExit(main())
