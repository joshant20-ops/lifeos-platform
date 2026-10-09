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


def adguard_dns_config_summary(text: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^dns:\s*(?:#.*)?$", line)), None)
    if start is None:
        return "dns_section:missing"
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")), len(lines))
    port_line = next((line for line in lines[start + 1:end] if re.match(r"^  port:", line)), None)
    bind_line = next((i for i in range(start + 1, end) if re.match(r"^  bind_hosts:", lines[i])), None)
    port = re.sub(r"^  port:\s*", "", port_line).split("#", 1)[0].strip() if port_line else "default"
    hosts = []
    if bind_line is not None:
        inline = lines[bind_line].split(":", 1)[1].split("#", 1)[0].strip()
        if inline:
            hosts = [inline]
        else:
            for line in lines[bind_line + 1:end]:
                if line and len(line) - len(line.lstrip()) <= 2:
                    break
                match = re.match(r"^    -\s*(.*?)\s*$", line)
                if match:
                    hosts.append(match.group(1).strip("'\\\""))
    details = [f"port:{port}", f"bind_hosts:{','.join(hosts) if hosts else 'all-or-empty'}"]
    for key in ("enabled", "serve_plain_dns", "protection_enabled", "upstream_mode"):
        match = next((line for line in lines[start + 1:end] if re.match(rf"^  {key}:", line)), None)
        if match:
            details.append(f"{key}:{match.split(':', 1)[1].split('#', 1)[0].strip()}")
    for key in ("upstream_dns", "bootstrap_dns", "fallback_dns"):
        match_index = next((i for i in range(start + 1, end) if re.match(rf"^  {key}:", lines[i])), None)
        if match_index is None:
            details.append(f"{key}:unset")
        else:
            value = lines[match_index].split(":", 1)[1].split("#", 1)[0].strip()
            if value:
                details.append(f"{key}:inline")
            else:
                count = 0
                for line in lines[match_index + 1:end]:
                    if line and len(line) - len(line.lstrip()) <= 2:
                        break
                    if re.match(r"^    -\s*", line):
                        count += 1
                details.append(f"{key}:count={count}")
    return ";".join(details)



def adguard_rewrite_structure_summary(text: str) -> str:
    lines = text.splitlines()
    filtering_sections = [i for i, line in enumerate(lines) if re.match(r"^filtering:\s*(?:#.*)?$", line)]
    start, end = rewrite_section(lines)
    rewrite_keys = [i for i in range(start + 1, end) if re.match(r"^  rewrites:\s*(?:\[\])?\s*(?:#.*)?$", lines[i])]
    matches = []
    for rewrite in rewrite_keys:
        key_end = next((i for i in range(rewrite + 1, end) if lines[i] and len(lines[i]) - len(lines[i].lstrip()) <= 2), end)
        for i in range(rewrite + 1, key_end):
            domain = re.match(r"^\s+-\s+domain:\s*([^\s#]+)", lines[i])
            if domain and domain.group(1).strip("'") == HOSTNAME:
                answer = next((re.match(r"^\s+answer:\s*([^\s#]+)", lines[j]) for j in range(i + 1, min(i + 3, key_end)) if re.match(r"^\s+answer:", lines[j])), None)
                matches.append(answer.group(1).strip("'") if answer else "answer_missing")
    return (
        f"top_level_filtering_sections:{len(filtering_sections)};"
        f"selected_rewrites_keys:{len(rewrite_keys)};"
        f"ai_lan_entries:{len(matches)};"
        f"ai_lan_answers:{','.join(matches) if matches else 'none'}"
    )


def filtering_rewrite_flags(text: str) -> str:
    lines = text.splitlines()
    start, end = rewrite_section(lines)
    if not re.match(r"^filtering:\s*(?:#.*)?$", lines[start]):
        return "legacy_dns_section"
    values = {}
    for key in ("filtering_enabled", "rewrites_enabled", "protection_enabled", "protection_disabled_until"):
        found = next((line for line in lines[start + 1:end] if re.match(rf"^  {key}:", line)), None)
        value = re.sub(r"^  [^:]+:\s*", "", found).split("#", 1)[0].strip().lower() if found else "unset"
        values[key] = value
    return ",".join(f"{key}:{values[key]}" for key in ("filtering_enabled", "rewrites_enabled"))


def rewrite_config(text: str, address: str) -> str:
    lines = text.splitlines()
    start, end = rewrite_section(lines)
    if re.match(r"^filtering:\s*(?:#.*)?$", lines[start]):
        enabled = next((i for i in range(start + 1, end) if re.match(r"^  rewrites_enabled:", lines[i])), None)
        if enabled is None:
            lines.insert(start + 1, "  rewrites_enabled: true")
        else:
            current = re.sub(r"^  rewrites_enabled:\s*", "", lines[enabled]).split("#", 1)[0].strip().lower()
            if current != "true":
                lines[enabled] = "  rewrites_enabled: true"
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



def dns_transport_state_summary() -> str:
    parts = []
    if shutil.which("ss"):
        result = subprocess.run(["ss", "-H", "-lntuap"], check=False, capture_output=True, text=True, timeout=5)
        sockets = [line.strip() for line in result.stdout.splitlines() if re.search(r":53\b", line)]
        parts.append("sockets=" + (" || ".join(sockets[:8]) if sockets else "none"))
    for command in (["iptables", "-t", "nat", "-S"], ["nft", "list", "ruleset"]):
        if shutil.which(command[0]):
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=5)
            rules = [
                line.strip() for line in result.stdout.splitlines()
                if "53" in line and re.search(r"(?:dport|--dport|redirect|dnat)", line, re.IGNORECASE)
            ]
            parts.append(command[0] + "=" + (" || ".join(rules[:8]) if rules else "no-port-53-rule"))
    return ";".join(parts) if parts else "unavailable"



def adguard_ai_querylog_summary() -> str:
    candidates = (
        pathlib.Path("/opt/stacks/adguard/work/data/querylog.json"),
        pathlib.Path("/opt/stacks/adguard/work/querylog.json"),
        pathlib.Path("/opt/adguardhome/work/data/querylog.json"),
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw_lines = path.read_bytes()[-4_000_000:].splitlines()
            matches = []
            for raw in raw_lines:
                try:
                    item = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                host = str(item.get("QH", item.get("question", {}).get("host", ""))).rstrip(".").lower()
                if host != HOSTNAME:
                    continue
                result = item.get("Result") or item.get("result") or {}
                answers = item.get("Answer") or item.get("answer") or []
                matches.append(f"reason:{result.get('Reason', result.get('reason', 'unknown'))};answer_items:{len(answers) if isinstance(answers, list) else 'present'}")
            return f"path:{path};matches:{len(matches)};latest:{matches[-1] if matches else 'none'}"
        except OSError as error:
            return f"path:{path};error:{type(error).__name__}"
    return "querylog_file:not_found_or_disabled"



def adguard_querylog_api_summary(api_base: str) -> str:
    """Summarize AdGuard's live query-log API without exposing unrelated client history."""
    url = f"{api_base}/control/querylog?search={HOSTNAME}&response_status=all&limit=20"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            records = payload if isinstance(payload, list) else payload.get("data", [])
            matches = []
            for item in records if isinstance(records, list) else []:
                question = item.get("question") or {}
                host = str(item.get("QH", question.get("host", ""))).rstrip(".").lower()
                if host != HOSTNAME:
                    continue
                result = item.get("Result") or item.get("result") or {}
                answers = item.get("Answer") or item.get("answer") or []
                matches.append(
                    f"reason:{result.get('Reason', result.get('reason', 'unknown'))};"
                    f"answer_items:{len(answers) if isinstance(answers, list) else 'present'}"
                )
            return f"http:{response.status};records:{len(records) if isinstance(records, list) else 'invalid'};ai_matches:{len(matches)};latest:{matches[-1] if matches else 'none'}"
    except urllib.error.HTTPError as error:
        return f"http:{error.code}"
    except Exception as error:
        return type(error).__name__


def adguard_client_override_summary(text: str, addresses: set[str]) -> str:
    lines = text.splitlines()
    clients_start = next((i for i, line in enumerate(lines) if re.match(r"^clients:\s*(?:#.*)?$", line)), None)
    if clients_start is None:
        return "clients_section:missing"
    clients_end = next((i for i in range(clients_start + 1, len(lines)) if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")), len(lines))
    persistent = next((i for i in range(clients_start + 1, clients_end) if re.match(r"^  persistent:\s*(?:#.*)?$", lines[i])), None)
    if persistent is None:
        return "persistent_clients:missing"
    entries = []
    starts = [i for i in range(persistent + 1, clients_end) if re.match(r"^\s+-\s+name:", lines[i])]
    for index, start in enumerate(starts):
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = next((i for i in range(start + 1, clients_end) if re.match(r"^\s+-\s+name:", lines[i]) and len(lines[i]) - len(lines[i].lstrip()) == indent), clients_end)
        stanza = lines[start:end]
        if not any(address in line for address in addresses for line in stanza):
            continue
        filtering = next((re.sub(r"^.*filtering_enabled:\s*", "", line).split("#", 1)[0].strip().lower() for line in stanza if re.match(r"^\s+filtering_enabled:", line)), "unset")
        global_settings = next((re.sub(r"^.*use_global_settings:\s*", "", line).split("#", 1)[0].strip().lower() for line in stanza if re.match(r"^\s+use_global_settings:", line)), "unset")
        entries.append(f"filtering_enabled:{filtering},use_global_settings:{global_settings}")
    return f"matched_local_clients:{len(entries)};overrides:{'|'.join(entries) if entries else 'none'}"


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
    startup_logs = subprocess.run(
        ["docker", "logs", "--since", "10m", "--tail", "1000", "adguardhome"],
        check=False, capture_output=True, text=True, timeout=5,
    )
    log_lines = (startup_logs.stdout + startup_logs.stderr).splitlines()
    startup_errors = [
        line.strip()[:240] for line in log_lines
        if re.search(r"(?:dns.{0,100}(?:error|fail|listen|bind|start|stop|server|disabled)|(?:error|fail|fatal|starting|stopping|listening).{0,100}(?:dns|listen|bind|port|server)|address already in use|bind:|port 53)", line, re.IGNORECASE)
    ][-8:]
    http_match = re.search(r'(?ms)^http:\s*\n(?:(?:^  [^\n]*\n)|(?:^\n))*?^  address:\s*([^\s#]+)', persisted)
    bind_match = re.search(r'(?m)^bind_port:\s*(\d+)', persisted)
    configured_address = http_match.group(1).strip("'\"") if http_match else ""
    configured_port = configured_address.rsplit(":", 1)[-1] if ":" in configured_address else (bind_match.group(1) if bind_match else "")
    api_bases = [f"http://{host}:{configured_port}" for host in (expected, "127.0.0.1")] if configured_port.isdigit() else []
    adguard_runtime = subprocess.run(
        ["docker", "inspect", "--format={{.Path}}|{{json .Args}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}", "adguardhome"],
        check=False, capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    adguard_health = subprocess.run(
        ["docker", "inspect", "--format={{if .State.Health}}{{json .State.Health}}{{else}}no-healthcheck{{end}}", "adguardhome"],
        check=False, capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    resolved_state = subprocess.run(
        ["systemctl", "is-active", "systemd-resolved"],
        check=False, capture_output=True, text=True, timeout=5,
    ).stdout.strip() or "unknown"
    network_runtime = subprocess.run(
        ["docker", "inspect", "--format={{.HostConfig.NetworkMode}}|{{json .NetworkSettings.Ports}}|{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", "adguardhome"],
        check=True, capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    api_results = {}
    runtime_status = {}
    for api_base in api_bases:
        for api_path in ("/control/status", "/control/rewrite/list", "/control/rewrite/settings", "/control/check_host?name=ai.lan"):
            key = f"{api_base.rsplit(':', 1)[0].removeprefix('http://')}:{api_path}"
            try:
                with urllib.request.urlopen(f"{api_base}{api_path}", timeout=3) as response:
                    api_results[key] = f"{response.status};server={response.headers.get('Server', 'none')};type={response.headers.get('Content-Type', 'none')}"
                    payload = json.loads(response.read().decode("utf-8"))
                    if api_path.endswith("/status") and not runtime_status:
                        runtime_status = payload
                    if "/check_host?" in api_path:
                        result = {
                            "reason": payload.get("reason"),
                            "ip_addrs": payload.get("ip_addrs"),
                            "cname": payload.get("cname"),
                        }
                        api_results[key] += f";check_host={json.dumps(result, separators=(',', ':'))}"
                    if api_path.endswith("/list"):
                        api_results[key] += f";exact_entry={any(item.get('domain') == HOSTNAME and item.get('answer') == expected for item in payload if isinstance(item, dict))}"
            except urllib.error.HTTPError as error:
                api_results[key] = f"{error.code};server={error.headers.get('Server', 'none')};type={error.headers.get('Content-Type', 'none')}"
            except Exception as error:
                api_results[key] = type(error).__name__
    dns_port = runtime_status.get("dns_port")
    dns_addresses = runtime_status.get("dns_addresses")
    print(f"ADGUARD_HTTP_CONFIG_ADDRESS={configured_address or 'unavailable'} API_PORT={configured_port or 'unavailable'}")
    print(f"ADGUARD_DOCKER_NETWORK_PORTS={network_runtime}")
    print(f"ADGUARD_PROCESS_PATH_ARGS_HEALTH={adguard_runtime or 'unavailable'}")
    print(f"ADGUARD_SYSTEMD_RESOLVED={resolved_state}")
    print(f"ADGUARD_CONTAINER_HEALTH={adguard_health or 'unavailable'}")
    print(
        "ADGUARD_RUNTIME_PROTECTION="
        f"enabled:{runtime_status.get('protection_enabled', 'unavailable')};"
        f"disabled_duration:{runtime_status.get('protection_disabled_duration', 'unavailable')};"
        f"start_time:{runtime_status.get('start_time', 'unavailable')}"
    )
    print(
        "ADGUARD_RUNTIME_STATUS="
        f"running:{runtime_status.get('running', 'unavailable')};"
        f"dns_addresses:{','.join(dns_addresses) if isinstance(dns_addresses, list) else 'unavailable'};"
        f"dns_port:{dns_port or 'unavailable'};http_port:{runtime_status.get('http_port', 'unavailable')};"
        f"version:{runtime_status.get('version', 'unavailable')}"
    )
    listener_output = ""
    if shutil.which("ss"):
        listeners = subprocess.run(
            ["ss", "-H", "-lntup"], check=False, capture_output=True, text=True, timeout=5,
        ).stdout
        ports = {"53", "3001"}
        if isinstance(dns_port, int):
            ports.add(str(dns_port))
        port_pattern = r":(?:" + "|".join(re.escape(port) for port in sorted(ports)) + r")\b"
        listener_output = ";".join(line.strip() for line in listeners.splitlines() if re.search(port_pattern, line))
    print(f"ADGUARD_HOST_LISTENERS={listener_output or 'unavailable'}")
    print(f"ADGUARD_IMAGE={image}")
    print(f"ADGUARD_MOUNTS={mount_info}")
    print(f"ADGUARD_VERSION={(binary_version.stdout or binary_version.stderr).strip()[:200] or 'unavailable'}")
    print("ADGUARD_DNS_STARTUP_ERRORS=" + " || ".join(startup_errors if startup_errors else ["none"]))
    print(f"ADGUARD_DNS_CONFIG_BEFORE={adguard_dns_config_summary(old)}")
    print(f"ADGUARD_DNS_CONFIG_AFTER={adguard_dns_config_summary(persisted)}")
    container_config = subprocess.run(
        ["docker", "exec", "adguardhome", "cat", "/opt/adguardhome/conf/AdGuardHome.yaml"],
        check=False, capture_output=True, text=True, timeout=5,
    )
    if container_config.returncode == 0:
        print(f"ADGUARD_CONTAINER_CONFIG_DNS={adguard_dns_config_summary(container_config.stdout)}")
        print(f"ADGUARD_CONTAINER_CONFIG_REWRITE={adguard_rewrite_structure_summary(container_config.stdout)}")
        print(f"ADGUARD_CONTAINER_CONFIG_FILTERING={filtering_rewrite_flags(container_config.stdout)}")
    else:
        print(f"ADGUARD_CONTAINER_CONFIG_READ=failed:{container_config.returncode}")
    print(f"ADGUARD_PI_CLIENT_OVERRIDES={adguard_client_override_summary(persisted, {expected, '127.0.0.1'})}")
    print(f"ADGUARD_REWRITE_CONFIG_STRUCTURE={adguard_rewrite_structure_summary(persisted)}")
    print(f"ADGUARD_FILTERING_FLAGS_BEFORE={filtering_rewrite_flags(old)}")
    print(f"ADGUARD_FILTERING_FLAGS_AFTER={filtering_rewrite_flags(persisted)}")
    print(f"ADGUARD_CONFIG_SECTION={rewrite_section_name} ENTRY_AFTER_START={'PASS' if rewrite_entry else 'FAIL'}")
    print(f"ADGUARD_REWRITE_API=list:{api_results.get('list')} settings:{api_results.get('settings')}")
    print("ADGUARD_HTTP_PROBES=" + ";".join(f"{key}={value}" for key, value in sorted(api_results.items())))
    resolvers = list(dict.fromkeys([*container_resolvers, expected, "127.0.0.1"]))
    known_rewrite_diagnostics: dict[str, str] = {}
    for resolver in resolvers:
        try:
            answers, response = adguard_ipv4_answers("ha.lan", resolver)
            known_rewrite_diagnostics[resolver] = (
                f"{response};expected_answer:{'PASS' if expected in answers else 'FAIL'}"
            )
        except OSError as error:
            known_rewrite_diagnostics[resolver] = type(error).__name__
    print("ADGUARD_KNOWN_REWRITE_CONTROL=" + ";".join(
        f"{resolver}:{known_rewrite_diagnostics[resolver]}" for resolver in resolvers
    ))
    diagnostics: dict[str, str] = {}
    for _ in range(20):
        for resolver in resolvers:
            try:
                answers, response = adguard_ipv4_answers(HOSTNAME, resolver)
                diagnostics[resolver] = response
                if expected in answers:
                    print("ADGUARD_DNS_TRANSPORT_AT_ACCEPTANCE=" + dns_transport_state_summary())
                    print("ADGUARD_AI_QUERYLOG=" + adguard_ai_querylog_summary())
                    print("ADGUARD_QUERYLOG_API=" + ";".join(
                        f"{base.rsplit(':', 1)[0].removeprefix('http://')}:{adguard_querylog_api_summary(base)}"
                        for base in api_bases
                    ))
                    print(f"ADGUARD_AI_DNS={HOSTNAME}->{expected} RESOLVER={resolver} PASS")
                    return 0
            except OSError as error:
                diagnostics[resolver] = type(error).__name__
        time.sleep(1)
    print("ADGUARD_DNS_TRANSPORT_AFTER_PROBES=" + dns_transport_state_summary())
    print("ADGUARD_AI_QUERYLOG=" + adguard_ai_querylog_summary())
    print("ADGUARD_QUERYLOG_API=" + ";".join(
        f"{base.rsplit(':', 1)[0].removeprefix('http://')}:{adguard_querylog_api_summary(base)}"
        for base in api_bases
    ))
    print("ADGUARD_DNS_DIAGNOSTICS=" + ";".join(f"{resolver}:{diagnostics.get(resolver, 'no_response')}" for resolver in resolvers))
    if new != old:
        subprocess.run(["docker", "stop", "adguardhome"], check=False, capture_output=True, text=True, timeout=30)
        shutil.copy2(backup, CONFIG)
        subprocess.run(["docker", "start", "adguardhome"], check=False, capture_output=True, text=True, timeout=30)
    raise RuntimeError(f"AdGuard did not resolve {HOSTNAME} to the Pi address {expected}")


if __name__ == "__main__":
    raise SystemExit(main())
