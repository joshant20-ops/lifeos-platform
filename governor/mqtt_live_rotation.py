"""Fixed Pi adapter for retained Mosquitto log rotation."""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import time
import uuid

from governor.mqtt_retained_rotation import RotationStopped, rotate
from governor.mqtt_rotation_preflight import CONTAINER, LOG, inspect, preflight, writer_matches
from governor.storage_health_gate import HealthGate, HealthUnavailable
from governor.storage_tier0 import baseline, command, dns_answers

JOURNAL = Path("/var/lib/lifeos-mqtt-retained-rotation")
RETAINED = "mosquitto.log.lifeos-retained"


def connection_inputs():
    addresses = command(["/usr/bin/getent", "ahostsv4", "github.com"]).splitlines()
    for line in addresses:
        address = ipaddress.IPv4Address(line.split()[0])
        if not address.is_global:
            continue
        routes = json.loads(command(["/usr/sbin/ip", "-j", "-4", "route", "get", str(address)]))
        if len(routes) != 1:
            continue
        local = ipaddress.IPv4Address(routes[0]["prefsrc"])
        if local.is_private and not local.is_loopback:
            return str(local), str(address)
    raise RotationStopped("resolver_route_unverified")


def health_checks(resolver, public):
    # The current LAN address serves household DNS on this host. Check both
    # transports using a public name and independently keep the TLS IP fixed.
    checks = baseline(resolver, "github.com", "", public, "github.com")["checks"]
    checks["household_dns_udp"] = checks["household_dns_public"]
    checks["household_dns_tcp"] = bool(dns_answers(resolver, "github.com", tcp=True))
    return checks


def broker_identity():
    broker = inspect("container", CONTAINER)
    state = broker["State"]
    if not state["Running"] or state["Health"]["Status"] != "healthy":
        raise RotationStopped("broker_unhealthy")
    return (broker["Id"], broker["Image"], state["Pid"], state["StartedAt"],
            broker["RestartCount"])


def run_rotation():
    if os.geteuid() != 0:
        raise RotationStopped("fixed_root_gateway_required")
    checks, _, _ = preflight()
    if not all(checks.values()):
        raise RotationStopped("broker_preflight_failed")
    resolver, public = connection_inputs()
    gate = HealthGate(lambda: health_checks(resolver, public), interval=2, max_age=16)
    gate.start()
    subscriber = None
    try:
        JOURNAL.mkdir(mode=0o700, exist_ok=True)
        info = JOURNAL.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise RotationStopped("journal_directory_unverified")
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(JOURNAL / "lock", flags, 0o600), "rb+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (JOURNAL / "prepared.json").exists() or (LOG.parent / RETAINED).exists():
                raise RotationStopped("prior_rotation_requires_review")
            original = broker_identity()
            checks, _, _ = preflight()
            if not all(checks.values()) or broker_identity() != original:
                raise RotationStopped("broker_preflight_identity_changed")
            container, _, pid, _, _ = original

            def stable():
                gate.guard()
                if broker_identity() != original:
                    raise RotationStopped("broker_identity_changed")

            def docker_exec(*args):
                subprocess.run(["/usr/bin/docker", "exec", container, *args],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5, check=True)

            topic = "lifeos/storage/rotation-proof/" + uuid.uuid4().hex
            subscriber = subprocess.Popen(
                ["/usr/bin/docker", "exec", container, "mosquitto_sub", "-h", "127.0.0.1",
                 "-t", topic, "-C", "2", "-W", "30"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )

            def message(value):
                docker_exec("mosquitto_pub", "-h", "127.0.0.1", "-t", topic, "-m", value)
                ready, _, _ = select.select([subscriber.stdout], [], [], 3)
                if not ready or subscriber.stdout.readline() != value.encode() + b"\n":
                    raise RotationStopped("mqtt_continuity_unverified")

            time.sleep(0.5)
            message("before")
            stable()

            def writer(info):
                # Also used for a guarded name restore when network probes fail.
                return broker_identity() == original and writer_matches(pid, info)

            def reopen():
                stable()
                docker_exec("mosquitto_signal", "-p", "1", "log-rotate")

            def verify(old, new):
                stable()
                if writer(old) or not writer(new):
                    raise RotationStopped("log_descriptors_unverified")
                retained = LOG.with_name(RETAINED)
                size = retained.stat().st_size
                message("after")
                if subscriber.wait(timeout=5) != 0 or retained.stat().st_size != size:
                    raise RotationStopped("retained_log_or_subscriber_changed")
                gate.sample()
                stable()

            return rotate(LOG.parent, LOG.name, RETAINED, JOURNAL, stable, writer, reopen, verify)
    finally:
        try:
            if subscriber is not None:
                if subscriber.poll() is None:
                    subscriber.kill()
                subscriber.communicate(timeout=5)
        finally:
            gate.close()


def main():
    def interrupted(_signum, _frame):
        raise RotationStopped("rotation_interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        report = run_rotation()
    except (OSError, ValueError, KeyError, IndexError, RotationStopped,
            HealthUnavailable, subprocess.SubprocessError):
        print(json.dumps({"status": "rotation_stopped_review_local_journal"}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
