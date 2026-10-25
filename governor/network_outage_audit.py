#!/usr/bin/env python3
"""Fixed read-only Pi forensics for the 23 October connectivity incident.

Raw journals remain on Pi. Only fixed categories, counts and UTC timestamps
leave this boundary; no addresses, SSIDs, log messages or credentials.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import socket
import struct
import subprocess

SINCE = '2026-10-23 16:30:00 UTC'
UNTIL = '2026-10-24 09:05:00 UTC'
UNITS = ('NetworkManager.service', 'systemd-networkd.service', 'systemd-resolved.service',
         'wpa_supplicant.service', 'tailscaled.service', 'wg-quick@*.service', 'openvpn*.service',
         'systemd-logind.service', 'systemd-journald.service',
         'actions.runner.joshant20-ops-lifeos-platform.lifeos-pi5.service')
RULES = (
    ('power_undervoltage', r'under.?voltage|voltage.*below'),
    ('memory_oom', r'out of memory|oom-kill|killed process.*total-vm'),
    ('storage_or_usb_event', r'i/o error|ext4-fs error|buffer i/o|usb.*disconnect|reset.*usb device'),
    ('kernel_lockup', r'kernel panic|watchdog.*lockup|hung task'),
    ('link_down', r'lost carrier|carrier lost|link is down|link down'),
    ('connection_down', r'state change: activated ->|disconnected'),
    ('shutdown_requested', r'shutting down|system is rebooting|system is powering down|reached target.*(?:reboot|power.off)'),
    ('link_up', r'gained carrier|link is up|link up|state change: .* -> activated'),
    ('dhcp_failure', r'dhcp.*(?:timed out|timeout|failed|expired)|lease.*(?:expired|lost)'),
    ('dns_failure', r'temporary failure in name resolution|name resolution.*fail|dns.*(?:timeout|failed|unreachable)|lookup.*no such host'),
    ('dns_lookup_error', r'name or service not known|no such host|eai_again|enotfound|getaddrinfo|nameresolutionerror'),
    ('tls_error', r'ssl connection could not be established|authenticationexception|certificate.*(?:invalid|expired)|tls.*handshake.*fail'),
    ('transport_error', r'connection reset by peer|connection refused|socketexception|httprequestexception'),
    ('cancel_or_timeout', r'taskcanceledexception|timeoutexception|deadline exceeded|operation was cancel'),
    ('remote_service_error', r'badgateway|serviceunavailable|gatewaytimeout|too many requests|toomanyrequests'),
    ('remote_auth_error', r'unauthorized|forbidden|invalid.*(?:credential|token)'),
    ('runner_session_failure', r'failed to create.*session|session.*conflict|runner listener.*exit|main process exited'),
    ('route_failure', r'network is unreachable|no route to host'),
    ('connection_timeout', r'connection timed out|connection timeout|connect.*timed out'),
    ('runner_connected', r'listening for jobs|connected to github'),
    ('runner_disconnected', r'failed to connect|connection.*(?:lost|closed)|session.*(?:expired|conflict)'),
)


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def unit_group(unit, kernel=False):
    if kernel:
        return 'kernel'
    if unit.startswith('actions.runner.'):
        return 'runner'
    if any(unit.startswith(x) for x in ('tailscaled', 'wg-quick@', 'openvpn')):
        return 'vpn'
    return 'network'


def summarize_journal(raw, kernel=False):
    events = []
    records = []
    for line in raw.splitlines():
        try:
            row = json.loads(line)
            stamp = int(row['__REALTIME_TIMESTAMP']) / 1000000
            message = row.get('MESSAGE', '')
            if not isinstance(message, str):
                continue
            records.append(stamp)
            group = unit_group(str(row.get('_SYSTEMD_UNIT', '')), kernel)
            for category, pattern in RULES:
                if re.search(pattern, message, re.I):
                    events.append({'at': utc(stamp), 'group': group, 'category': category})
        except (ValueError, KeyError, TypeError, OverflowError, OSError):
            continue
    counts = Counter((x['group'], x['category']) for x in events)
    # Preserve initial and latest evidence without dumping repetitive messages.
    selected = []
    for pair in sorted(counts):
        matching = [x for x in events if (x['group'], x['category']) == pair]
        for item in matching[:2] + matching[-4:]:
            if item not in selected:
                selected.append(item)
    return {'records': len(records), 'record_limit_reached': len(raw.splitlines()) >= 6000,
            'first': utc(min(records)) if records else None,
            'last': utc(max(records)) if records else None,
            'counts': [{'group': g, 'category': c, 'count': n} for (g, c), n in sorted(counts.items())],
            'events': sorted(selected, key=lambda x: x['at'])}


def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def runner_diagnostics(directory):
    start = datetime(2026, 10, 23, 16, 30, tzinfo=timezone.utc)
    end = datetime(2026, 10, 24, 9, 5, tzinfo=timezone.utc)
    files = sorted(directory.glob('Runner_*.log'), reverse=True)
    rows, checked, limited = [], 0, False
    for path in files:
        # Files started after the incident cannot contain incident evidence.
        name_date = re.search(r'Runner_(\d{8})', path.name)
        if name_date and name_date[1] > '20261024':
            continue
        if checked >= 6:
            limited = True
            break
        if path.is_symlink():
            continue
        try:
            if path.stat().st_mtime < start.timestamp():
                continue
            checked += 1
            stamp = None
            with path.open(errors='replace') as stream:
                total = 0
                for line in stream:
                    total += len(line.encode('utf-8', errors='replace'))
                    if total > 16 * 1024 * 1024 or len(rows) >= 2000:
                        limited = True
                        break
                    match = re.search(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z', line)
                    if match:
                        stamp = datetime.fromisoformat(match[0].replace('Z', '+00:00'))
                    if stamp is not None and stamp > end:
                        break
                    if stamp is None or stamp < start:
                        continue
                    if any(re.search(pattern, line, re.I) for _, pattern in RULES):
                        rows.append(json.dumps({'__REALTIME_TIMESTAMP': int(stamp.timestamp() * 1000000),
                            '_SYSTEMD_UNIT': 'actions.runner.local.service', 'MESSAGE': line}))
        except (OSError, ValueError, OverflowError):
            continue
    result = summarize_journal('\n'.join(rows))
    result.update(files_checked=checked, scan_limit_reached=limited)
    return result


def dns_probe(server, name):
    ident = 0x4c4f
    question = b''.join(bytes([len(part)]) + part.encode('ascii') for part in name.split('.')) + b'\0'
    packet = struct.pack('!6H', ident, 0x0100, 1, 0, 0, 0) + question + struct.pack('!2H', 1, 1)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.settimeout(3)
            stream.sendto(packet, (server, 53))
            data, _ = stream.recvfrom(4096)
        header = struct.unpack('!6H', data[:12])
        if header[0] != ident or not header[1] & 0x8000:
            return {'status': 'PROTOCOL_ERROR'}
        code = header[1] & 15
        return {'status': {0: 'NOERROR', 2: 'SERVFAIL', 3: 'NXDOMAIN', 5: 'REFUSED'}.get(code, 'OTHER'),
                'answers': header[3], 'truncated': bool(header[1] & 0x0200)}
    except (socket.timeout, TimeoutError):
        return {'status': 'TIMEOUT'}
    except (OSError, ValueError, struct.error):
        return {'status': 'UNAVAILABLE'}


def dns_checks():
    servers = [('loopback', '127.0.0.1')]
    raw = command(['ip', '-j', '-4', 'address', 'show', 'scope', 'global'])
    try:
        for interface in json.loads(raw or '[]'):
            if str(interface.get('ifname', '')).startswith(('eth', 'en', 'wlan')):
                for addr in interface.get('addr_info', []):
                    if addr.get('family') == 'inet' and len(servers) < 3:
                        servers.append(('lan', addr['local']))
    except (ValueError, TypeError, KeyError):
        pass
    for label, server in servers:
        for name in ('adguard.lan', 'example.com'):
            print('OUTAGE_CURRENT_DNS=' + json.dumps({'via': label, 'name': name, **dns_probe(server, name)}))


def main():
    if platform.node() != 'Docker' or os.geteuid() != 0:
        print('OUTAGE_AUDIT=WRONG_RUNTIME')
        return 20
    print('OUTAGE_AUDIT_VERSION=1')
    print('OUTAGE_WINDOW_START=2026-10-23T16:30:00Z')
    print('OUTAGE_WINDOW_END=2026-10-24T09:05:00Z')
    try:
        uptime = float(Path('/proc/uptime').read_text().split()[0])
        print('OUTAGE_CURRENT_BOOT=' + utc(datetime.now(timezone.utc).timestamp() - uptime))
    except (OSError, ValueError, IndexError):
        print('OUTAGE_CURRENT_BOOT=UNAVAILABLE')
    boots = command(['journalctl', '--list-boots', '--no-pager', '--utc'])
    print('OUTAGE_RETAINED_BOOTS=' + str(len([x for x in (boots or '').splitlines()
          if re.match(r'\s*-?\d+\s+[a-f0-9]{32}\s', x)])))
    for line in (boots or '').splitlines()[-4:]:
        match = re.match(r'\s*(-?\d+)\s+[a-f0-9]{32}\s', line)
        dates = re.findall(r'\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\b', line)
        if match and len(dates) == 2:
            print('OUTAGE_BOOT=' + json.dumps({'index': int(match[1]), 'first_utc': dates[0], 'last_utc': dates[1]}))
    common = ['journalctl', '--since', SINCE, '--until', UNTIL, '--no-pager', '-o', 'json', '-n', '6000']
    units = [arg for unit in UNITS for arg in ('-u', unit)]
    for name, extra, kernel in (('network', units, False), ('kernel', ['_TRANSPORT=kernel'], True)):
        raw = command(common + extra)
        if raw is None:
            print('OUTAGE_JOURNAL_' + name.upper() + '=UNAVAILABLE')
        else:
            print('OUTAGE_JOURNAL_' + name.upper() + '=' + json.dumps(summarize_journal(raw, kernel), separators=(',', ':')))
    print('OUTAGE_RUNNER_DIAGNOSTICS=' + json.dumps(runner_diagnostics(Path('/opt/actions-runner-lifeos/_diag')), separators=(',', ':')))
    dns_checks()
    raw = command(['docker', 'inspect', 'homeassistant', 'adguardhome', 'mosquitto', 'nginx-proxy-manager'])
    try:
        containers = json.loads(raw or '[]')
        for row in containers:
            state = row.get('State') or {}
            name = str(row.get('Name', '')).lstrip('/')
            if name not in {'homeassistant', 'adguardhome', 'mosquitto', 'nginx-proxy-manager'}:
                continue
            # Docker timestamps and states are metadata; never emit Config/Env.
            stamp = datetime.fromisoformat(state['StartedAt'].replace('Z', '+00:00'))
            print('OUTAGE_CONTAINER=' + json.dumps({'name': name, 'started': utc(stamp.timestamp()),
                  'restarts': int(row.get('RestartCount', 0)), 'oom_killed': bool(state.get('OOMKilled'))}))
    except (ValueError, TypeError, KeyError, OverflowError):
        print('OUTAGE_CONTAINER_METADATA=UNAVAILABLE')
    print('OUTAGE_AUDIT_MUTATIONS=NONE')
    print('OUTAGE_AUDIT=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
