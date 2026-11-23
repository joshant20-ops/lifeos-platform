#!/usr/bin/env python3
"""Fixed read-only storage audit. Only schema-filtered aggregates leave the Pi.

Installed root-owned code/configuration, not a GitHub-supplied script runner.
Cached evidence is input, never authority to delete. No document/log contents read.
"""
import fcntl
import http.client
import json
import os
import pathlib
import re
import socket
import stat
import subprocess
import sys
import time

BASE = pathlib.Path('/var/lib/lifeos-storage-audit')
CONFIG = pathlib.Path('/etc/lifeos-storage-audit.json')
SOCKET = '/run/docker.sock'
UNIT = 'lifeos-storage-audit.service'
LIB = pathlib.Path(__file__).resolve().parent
MAX_JSON = 16 * 1024 * 1024
FIELDS = {
    'schema_version', 'status', 'available_bytes', 'reserve_bytes', 'headroom_bytes',
    'available_inodes', 'backup_groups', 'backup_logical_bytes', 'snapshot_files',
    'snapshot_logical_bytes', 'predbat_candidates', 'predbat_unreferenced_untagged',
    'predbat_cached_unique_bytes', 'protected_running', 'containers_unchanged',
    'inventory_age_seconds', 'predbat_age_seconds', 'inventory_status',
    'predbat_status', 'eligible_for_deletion_bytes', 'cache_age_seconds',
}
STATUS = {'OK', 'PARTIAL', 'DEFERRED', 'UNAVAILABLE'}
SOURCE_STATUS = {'OK', 'STALE', 'INVALID', 'UNAVAILABLE'}


def public(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError('public_schema')
    if data['schema_version'] != 1 or data['status'] not in STATUS:
        raise ValueError('public_schema')
    for key in ('inventory_status', 'predbat_status'):
        if data[key] not in SOURCE_STATUS: raise ValueError('public_schema')
    for key in ('protected_running', 'containers_unchanged'):
        if type(data[key]) is not bool: raise ValueError('public_schema')
    numeric = FIELDS - {'status', 'inventory_status', 'predbat_status', 'protected_running', 'containers_unchanged'}
    for key in numeric:
        lower = -(2**60) if key == 'headroom_bytes' else -1
        if type(data[key]) is not int or not lower <= data[key] <= 2**60:
            raise ValueError('public_schema')
    if data['eligible_for_deletion_bytes'] != 0: raise ValueError('no_deletion_authority')
    return data


def empty():
    d = {k: -1 for k in FIELDS}
    d.update(schema_version=1, status='UNAVAILABLE', inventory_status='UNAVAILABLE',
             predbat_status='UNAVAILABLE', protected_running=False,
             containers_unchanged=False, eligible_for_deletion_bytes=0)
    return d


def read_json(path, trusted=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON:
            raise ValueError('input_bounds')
        if trusted and (info.st_uid != 0 or info.st_mode & 0o077):
            raise ValueError('unsafe_private_file')
        return json.loads(stream.read(MAX_JSON + 1)), info


def configuration(path=CONFIG):
    c, _ = read_json(path, trusted=True)
    if set(c) != {'storage_root', 'automation_root', 'inventory_tsv', 'predbat_report',
                  'protected_container_names', 'max_cache_age_seconds'}:
        raise ValueError('configuration_schema')
    for key in ('storage_root', 'automation_root', 'inventory_tsv', 'predbat_report'):
        if not isinstance(c[key], str) or not pathlib.Path(c[key]).is_absolute():
            raise ValueError('configuration_path')
    if (type(c['max_cache_age_seconds']) is not int or not 60 <= c['max_cache_age_seconds'] <= 86400
            or not isinstance(c['protected_container_names'], list)
            or not 3 <= len(c['protected_container_names']) <= 8
            or not all(isinstance(n, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', n)
                       for n in c['protected_container_names'])):
        raise ValueError('configuration_limits')
    return c


def age(path):
    s = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(s.st_mode): raise ValueError('unsafe_input')
    n = int(time.time() - s.st_mtime)
    if n < 0: raise ValueError('future_input')
    return n


class DockerReadOnly:
    def get(self, endpoint):
        if (endpoint != '/containers/json?all=1'
                and not re.fullmatch(r'/images/sha256:[a-f0-9]{64}/json', endpoint)
                and not re.fullmatch(r'/containers/[a-f0-9]{64}/json', endpoint)):
            raise ValueError('docker_endpoint_not_allowlisted')
        class UnixConnection(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(2)
                self.sock.connect(SOCKET)
        connection = UnixConnection('localhost', timeout=2)
        try:
            connection.request('GET', endpoint)
            response = connection.getresponse()
            data = response.read(MAX_JSON + 1)
            if response.status != 200 or len(data) > MAX_JSON: raise ValueError('docker_read_failed')
            return json.loads(data)
        finally:
            connection.close()


def resource_safe():
    try:
        memory = pathlib.Path('/proc/meminfo').read_text()
        available = int(re.search(r'^MemAvailable:\s+(\d+)', memory, re.M)[1]) * 1024
        temperature = int(pathlib.Path('/sys/class/thermal/thermal_zone0/temp').read_text())
        return (available >= 2 * 1024**3 and temperature < 75000
                and os.getloadavg()[0] <= max(1, os.cpu_count() or 1) * 0.65)
    except (OSError, ValueError, TypeError):
        return False


def fleet(rows):
    if not isinstance(rows, list) or len(rows) > 256: raise ValueError('fleet_bounds')
    return sorted((r['Id'], r['ImageID'], r.get('State'), tuple(r.get('Names', []))) for r in rows)


def protected_running(rows, names):
    running = {n.lstrip('/') for r in rows if r.get('State') == 'running' for n in r.get('Names', [])}
    return set(names) <= running


def protected_state(rows, names, docker):
    selected = [r for r in rows if any(n.lstrip('/') in names for n in r.get('Names', []))]
    states = []
    for r in selected:
        if not re.fullmatch(r'[a-f0-9]{64}', r['Id']): raise ValueError('container_identity')
        data = docker.get('/containers/' + r['Id'] + '/json')
        state = data['State']
        if not state.get('Running') or state.get('Health', {}).get('Status') in {'unhealthy', 'starting'}:
            raise ValueError('protected_health')
        states.append((data['Id'], data['Image'], state['StartedAt'], data['RestartCount']))
    return sorted(states)


def unique_estimate(report, candidates):
    values = {}
    for line in report.get('docker_df_image_rows', []):
        parts = line.split()
        if len(parts) < 5: continue
        match = re.fullmatch(r'(\d+(?:\.\d+)?)(B|kB|MB|GB|KiB|MiB|GiB)', parts[-2])
        if not match: continue
        scale = {'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3,
                 'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}[match[2]]
        for short in candidates:
            if short in parts: values[short] = int(float(match[1]) * scale)
    return sum(values.values()) if set(values) == set(candidates) else -1


def predbat(c, d, docker):
    d['predbat_age_seconds'] = age(c['predbat_report'])
    stale = d['predbat_age_seconds'] > c['max_cache_age_seconds']
    report, _ = read_json(c['predbat_report'])
    rows = report['inventory']
    if not isinstance(rows, list) or len(rows) > 64: raise ValueError('inventory_bounds')
    candidates = [r for r in rows if r.get('disposition') == 'HOLD']
    pins = [r for r in rows if r.get('disposition') == 'KEEP']
    if len(candidates) != 20 or len(pins) != 4: raise ValueError('inventory_roles')
    ids = [r['id'] for r in rows]
    if len(set(ids)) != len(ids) or not all(re.fullmatch(r'sha256:[a-f0-9]{64}', i) for i in ids):
        raise ValueError('inventory_identity')
    before = docker.get('/containers/json?all=1')
    baseline = fleet(before)
    d['protected_running'] = protected_running(before, c['protected_container_names'])
    if not d['protected_running']: d['predbat_status'] = 'INVALID'; return
    before_protected = protected_state(before, c['protected_container_names'], docker)
    refs = {r['ImageID'] for r in before}
    count = 0
    for row in rows:
        current = docker.get('/images/' + row['id'] + '/json')
        if current.get('Id') != row['id']: raise ValueError('image_identity')
        if row in candidates and row['id'] not in refs and not current.get('RepoTags') and not current.get('RepoDigests'):
            count += 1
    after = docker.get('/containers/json?all=1')
    d['containers_unchanged'] = (baseline == fleet(after) and before_protected ==
                               protected_state(after, c['protected_container_names'], docker))
    d['protected_running'] = d['protected_running'] and protected_running(after, c['protected_container_names'])
    d['predbat_candidates'] = len(candidates)
    d['predbat_unreferenced_untagged'] = count
    d['predbat_cached_unique_bytes'] = -1 if stale else unique_estimate(report, [r['id'][7:19] for r in candidates])
    d['predbat_status'] = ('STALE' if stale else 'OK') if d['containers_unchanged'] and d['protected_running'] else 'INVALID'


def inventories(c, d):
    # Reuse existing deterministic metadata parsers; no new full-disk scan.
    sys.path.insert(0, str(LIB))
    from scripts import lifeos_storage_retention_inventory as retention
    from scripts import lifeos_storage_backup_profile as backup
    import datetime
    previous_roots = retention.ROOT, backup.ROOT
    try:
        retention.ROOT = c['automation_root'].rstrip('/') + '/'
        backup.ROOT = retention.ROOT
        d['inventory_age_seconds'] = age(c['inventory_tsv'])
        stale = d['inventory_age_seconds'] > c['max_cache_age_seconds']
        today = datetime.datetime.now(datetime.timezone.utc).date()
        with retention.open_inventory(c['inventory_tsv']) as stream:
            totals = retention.summarise(stream, today)
        with retention.open_inventory(c['inventory_tsv']) as stream:
            profile = backup.profile(stream, today)
    finally:
        retention.ROOT, backup.ROOT = previous_roots
    d['backup_groups'] = profile['backup_groups']
    d['backup_logical_bytes'] = totals['categories'].get('backups', {}).get('bytes', 0)
    snap = totals['categories'].get('repair_lifecycle/snapshots', {})
    d['snapshot_files'], d['snapshot_logical_bytes'] = snap.get('files', 0), snap.get('bytes', 0)
    d['inventory_status'] = ('STALE' if stale else 'OK') if not totals['invalid_rows'] and not profile['invalid_rows'] else 'INVALID'


def collect(c, docker=None):
    d = empty()
    d['cache_age_seconds'] = 0
    fs = os.statvfs(c['storage_root'])
    d['available_bytes'] = fs.f_bavail * fs.f_frsize
    d['reserve_bytes'] = (fs.f_blocks * fs.f_frsize + 9) // 10
    d['headroom_bytes'] = d['available_bytes'] - d['reserve_bytes']
    d['available_inodes'] = fs.f_favail
    if not resource_safe():
        d['status'] = 'DEFERRED'; return public(d)
    # Low reserve permits only bounded cache/Docker metadata, not parser work.
    if d['headroom_bytes'] >= 0:
        try: inventories(c, d)
        except Exception: d['inventory_status'] = 'INVALID'
    try: predbat(c, d, docker or DockerReadOnly())
    except Exception: d['predbat_status'] = 'INVALID'
    d['status'] = 'OK' if d['inventory_status'] == d['predbat_status'] == 'OK' else 'PARTIAL'
    return public(d)


def request():
    if os.geteuid() != 0: raise ValueError('root_boundary_required')
    try: fresh = age(BASE / 'public.json') <= 300
    except (OSError, ValueError): fresh = False
    if not fresh:
        p = subprocess.run(['/usr/bin/systemctl', 'start', UNIT], capture_output=True, timeout=120)
        if p.returncode: raise ValueError('audit_unavailable')
    data, _ = read_json(BASE / 'public.json', trusted=True)
    data['cache_age_seconds'] = age(BASE / 'public.json')
    print(json.dumps(public(data), sort_keys=True))


def main(argv):
    if argv == ['--request']: request(); return
    if argv == ['--collect']:
        if os.geteuid() != 0: raise ValueError('root_boundary_required')
        os.umask(0o077)
        with (BASE / 'audit.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = collect(configuration())
            (BASE / 'public.next').write_text(json.dumps(data, sort_keys=True))
            os.replace(BASE / 'public.next', BASE / 'public.json')
        return
    if len(argv) == 2 and argv[0] == '--public':
        data, _ = read_json(argv[1])
        print(json.dumps(public(data), sort_keys=True)); return
    raise ValueError('fixed_operation_only')


if __name__ == '__main__':
    try: main(sys.argv[1:])
    except Exception:
        print('STORAGE_AUDIT_UNAVAILABLE', file=sys.stderr)
        raise SystemExit(1)
