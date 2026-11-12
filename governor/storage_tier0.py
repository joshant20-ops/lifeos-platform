"""Read-only Tier 0 baseline for the local storage programme."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess

ADGUARD = Path("/opt/stacks/adguard")
DOCKER_DATA = Path("/mnt/docker-data")
RESERVE_BYTES = 10 * 1024**3


def command(argv):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=6, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""


def dns_answers(resolver, name, tcp=False):
    transport = ["+tcp"] if tcp else []
    reply = command(["dig", "-r", "@" + resolver, name, "A", "+time=2", "+tries=1",
                     "+noall", "+answer", *transport])
    answers = set()
    for line in reply.splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[3] == "A":
            try:
                answers.add(str(ipaddress.IPv4Address(fields[4])))
            except ValueError:
                continue
    return answers


def direct_internet(address, hostname):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((address, 443), timeout=3) as connection:
            with context.wrap_socket(connection, server_hostname=hostname):
                return True
    except (OSError, ValueError):
        return False


def reserves_met(stats):
    reserve = max(RESERVE_BYTES, stats.f_blocks * stats.f_frsize // 10)
    return (stats.f_bavail * stats.f_frsize >= reserve
            and stats.f_files > 0 and stats.f_favail * 10 >= stats.f_files)


def docker_data_capacity():
    """Collect aggregate counters without listing directories or reading files."""
    try:
        if not DOCKER_DATA.is_mount():
            return {"status": "mount_unverified"}
        stats = os.statvfs(DOCKER_DATA)
    except OSError:
        return {"status": "capacity_unavailable"}
    return {
        "status": "within_reserve" if reserves_met(stats) else "below_reserve",
        "capacity_bytes": stats.f_blocks * stats.f_frsize,
        "used_bytes": (stats.f_blocks - stats.f_bfree) * stats.f_frsize,
        "available_bytes": stats.f_bavail * stats.f_frsize,
        "reserved_free_bytes": (stats.f_bfree - stats.f_bavail) * stats.f_frsize,
        "total_inodes": stats.f_files,
        "available_inodes": stats.f_favail,
    }


def enough_space():
    try:
        for path in (ADGUARD / "conf", ADGUARD / "work", DOCKER_DATA):
            if not reserves_met(os.statvfs(path)):
                return False
    except OSError:
        return False
    return True


def baseline(resolver, local_name, local_address, internet_ip, internet_name):
    state = command(["docker", "inspect", "--type", "container", "--format",
                     "{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                     "adguardhome"])
    checks = {
        "adguard_running": state in {"true healthy", "true none"},
        "household_dns_udp": local_address in dns_answers(resolver, local_name),
        "household_dns_tcp": local_address in dns_answers(resolver, local_name, tcp=True),
        "household_dns_public": bool(dns_answers(resolver, "github.com")),
        "direct_internet_tls": direct_internet(internet_ip, internet_name),
        "github_https": command(["curl", "-q", "--noproxy", "*", "--max-time", "5", "--silent",
                                 "--output", "/dev/null", "--write-out", "%{http_code}",
                                 "https://github.com/"]) == "200",
        "storage_reserve": enough_space(),
    }
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks": checks,
        "network_and_capacity_pass": all(checks.values()),
        "maintenance_authorised": False,
    }


def hostname(value):
    labels = value.split(".")
    if len(value) > 253 or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", part)
                               or part.endswith("-") for part in labels):
        raise argparse.ArgumentTypeError("invalid DNS name")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolver", required=True, type=ipaddress.IPv4Address)
    parser.add_argument("--local-name", required=True, type=hostname)
    parser.add_argument("--local-address", required=True, type=ipaddress.IPv4Address)
    parser.add_argument("--internet-ip", required=True, type=ipaddress.IPv4Address)
    parser.add_argument("--internet-name", required=True, type=hostname)
    args = parser.parse_args()
    if not args.internet_ip.is_global:
        parser.error("internet probe requires a public IPv4 address")
    report = baseline(str(args.resolver), args.local_name, str(args.local_address),
                      str(args.internet_ip), args.internet_name)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["network_and_capacity_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
