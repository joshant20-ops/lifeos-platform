#!/usr/bin/env python3
"""One-off operator cleanup of two known legacy PA backup families.

Not a daemon, scheduler, privileged gateway or general retention executor.
Only an authorised owner may run --execute through existing local permissions.
"""
import argparse
import ast
import collections
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

CUTOFF = int(dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc).timestamp())
PATTERN = re.compile(r'(pa_ha_dashboard|pa_escalation_v1)_[0-9]{8}_[0-9]{6}')
SOURCES = {
    'pa_ha_dashboard': ('lifeos_pa_ha_dashboard_export.py', 'f9ad7d0c77751e4a11d61f0920d863cfc04f9501'),
    'pa_escalation_v1': ('lifeos_pa_escalation_engine.py', '1eb4de6a49e036f544475e5be2051ffc865c283b'),
}
FIELDS = ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_blocks','st_mode','st_uid','st_gid')
NOFOLLOW = os.O_RDONLY | os.O_NOFOLLOW

def call(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=20, **kwargs).stdout

def identity(s):
    return {key: getattr(s, key) for key in FIELDS}

def volume(root):
    v = os.statvfs(root)
    return {'capacity_bytes': v.f_blocks*v.f_frsize,
            'available_bytes': v.f_bavail*v.f_frsize,
            'available_inodes': v.f_favail}

def family(name):
    match = PATTERN.fullmatch(name)
    return match[1] if match else None

def shape(names, kind):
    names = set(names)
    if kind == 'pa_escalation_v1':
        return names == {'lovelace.dashboard_homelab','lifeos_pa_lifecycle.yaml','pa_escalations.json'}
    suffixes = ('__open_loops.json','__pa_latest_summary.json',
                '__lifeos_pa_lifecycle.yaml','__lifeos_pa_lifecycle_export.py')
    return kind == 'pa_ha_dashboard' and len(names) == 4 and all(
        sum(n.endswith(s) for n in names) == 1 for s in suffixes)

def inspect(rootfd, name):
    """No recursive deletion; each admitted generation contains flat known files."""
    kind = family(name)
    if not kind: raise ValueError('unknown_family')
    fd = os.open(name, NOFOLLOW | os.O_DIRECTORY, dir_fd=rootfd)
    try:
        ds = os.fstat(fd)
        if ds.st_dev != os.fstat(rootfd).st_dev: raise ValueError('different_device')
        names = os.listdir(fd)
        if not shape(names, kind): raise ValueError('unknown_or_incomplete_shape')
        files = {}
        for leaf in sorted(names):
            fs = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(fs.st_mode) or fs.st_nlink != 1 or fs.st_dev != ds.st_dev:
                raise ValueError('unsafe_file')
            if not 0 < fs.st_size <= 8*1024**2: raise ValueError('file_size_hold')
            files[leaf] = identity(fs)
        return {'generation': name, 'family': kind, 'directory': identity(ds),
                'files': files, 'allocated_bytes': sum(s['st_blocks']*512 for s in files.values())}
    finally: os.close(fd)

def old(record, birth):
    return 0 < birth < CUTOFF and record['directory']['st_ctime_ns'] < CUTOFF*10**9 and all(
        s['st_ctime_ns'] < CUTOFF*10**9 for s in record['files'].values())

def restore_check(root, record, destination, yaml_validator):
    """Real isolated file-copy restoration, not full Home Assistant DR."""
    destination.mkdir(mode=0o700)
    hashes = {}
    for name, expected in record['files'].items():
        src = root/record['generation']/name
        if identity(src.lstat()) != expected: raise ValueError('recovery_changed')
        dest = destination/name
        shutil.copy2(src, dest, follow_symlinks=False)
        original = src.read_bytes()
        restored = dest.read_bytes()
        if original != restored or identity(src.lstat()) != expected:
            raise ValueError('recovery_copy_mismatch')
        if name.endswith('.json') or name.startswith('lovelace.'):
            json.loads(restored)
        elif name.endswith('.py'): ast.parse(restored)
        elif name.endswith('.yaml'): yaml_validator(restored)
        hashes[name] = hashlib.sha256(restored).hexdigest()
    return hashes

def births(root, names):
    result = {}
    for start in range(0, len(names), 256):
        output = call(['stat','--printf=%W\t%n\0','--',*[str(root/n) for n in names[start:start+256]]])
        for row in output.split(b'\0'):
            if row:
                born, path = row.split(b'\t',1)
                result[Path(os.fsdecode(path)).name] = int(born)
    return result

def references(roots):
    """Bounded current operational records only; never historical binary archives."""
    held = set()
    for root in roots:
        try: root.stat()
        except FileNotFoundError: continue
        count = 0
        def error(exc): raise exc
        for parent, dirs, files in os.walk(root, followlinks=False, onerror=error):
            dirs[:] = [d for d in dirs if d not in {'backups','logs','.git','node_modules'}
                       and not (Path(parent)/d).is_symlink()]
            for leaf in files:
                p = Path(parent)/leaf
                if p.suffix not in {'.json','.yaml','.yml','.conf','.sh','.service','.timer'}: continue
                count += 1
                if count > 20000: raise ValueError('reference_scope_limit')
                s = p.lstat()
                if not stat.S_ISREG(s.st_mode) or s.st_size > 2*1024**2:
                    raise ValueError('unreadable_reference_record')
                held.update(m.group() for m in PATTERN.finditer(p.read_text(errors='replace')))
    return held

def active_generations(root):
    """Root reads current process references; disappearance is normal, denial is not."""
    held = set()
    prefix = str(root)+'/'
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal(): continue
        try:
            links = [proc/'cwd', *list((proc/'fd').iterdir())]
            for p in links:
                try: value = os.readlink(p)
                except FileNotFoundError: continue
                if value.startswith(prefix): held.add(value[len(prefix):].split('/')[0])
            for line in (proc/'maps').read_text().splitlines():
                fields = line.split(None, 5)
                if len(fields) == 6 and fields[5].startswith(prefix):
                    held.add(fields[5][len(prefix):].split('/')[0])
        except (FileNotFoundError, ProcessLookupError): continue
    return held

def fleet():
    ids = call(['docker','ps','-aq'], text=True).split()
    containers = json.loads(call(['docker','inspect',*ids], text=True)) if ids else []
    running = {}
    for c in containers:
        if not c['State']['Running']: continue
        health = c['State'].get('Health',{}).get('Status')
        if health not in (None,'healthy'): raise ValueError('container_health_hold')
        running[c['Id']] = (c['Image'],c['State']['StartedAt'])
    names = ' '.join(c['Name'].lower().replace('_','').replace('-','') for c in containers if c['State']['Running'])
    if not all(s in names for s in ('adguard','homeassistant','predbat','paperless')):
        raise ValueError('protected_service_missing')
    return containers, running

def health(baseline=None):
    containers, running = fleet()
    if baseline and any(running.get(k) != v for k,v in baseline.items()):
        raise ValueError('service_identity_changed')
    for tcp in (False, True):
        args = ['dig','+time=2','+tries=1','+short','@127.0.0.1','github.com','A']
        if tcp: args.append('+tcp')
        response = call(args, text=True)
        addresses = [s for s in response.splitlines() if re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}',s)]
        if not addresses: raise ValueError('dns_health_failed')
    call(['curl','--fail','--silent','--max-time','10','--resolve',
          'github.com:443:'+addresses[0],'https://github.com/'])
    if not call(['ss','-H','-ltn','sport = :22'], text=True).strip():
        raise ValueError('ssh_recovery_missing')
    thermal = Path('/sys/class/thermal/thermal_zone0/temp')
    if thermal.exists() and int(thermal.read_text()) >= 80000: raise ValueError('thermal_hold')
    memory = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    if int(memory['MemAvailable'].split()[0]) < 512*1024: raise ValueError('memory_hold')
    return containers, running

def remove_generation(rootfd, record, journal):
    """Revalidate all members before any unlink. Journal intent is durable first."""
    current = inspect(rootfd, record['generation'])
    if current != record: raise ValueError('candidate_changed')
    fd = os.open(record['generation'], NOFOLLOW | os.O_DIRECTORY, dir_fd=rootfd)
    try:
        if identity(os.fstat(fd)) != record['directory']: raise ValueError('directory_changed')
        journal.write(json.dumps({'event':'intent','record':record})+'\n')
        journal.flush(); os.fsync(journal.fileno())
        for name, expected in record['files'].items():
            if identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != expected:
                raise ValueError('file_changed')
            os.unlink(name, dir_fd=fd)
            journal.write(json.dumps({'event':'unlinked','generation':record['generation'],'file':name})+'\n')
        os.fsync(fd)
    finally: os.close(fd)
    os.rmdir(record['generation'], dir_fd=rootfd)
    journal.write(json.dumps({'event':'generation_removed','generation':record['generation']})+'\n')
    journal.flush(); os.fsync(journal.fileno())


def cleanup_lock():
    fd = os.open('/run/lock/lifeos-pa-backup-cleanup.lock', os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    f = os.fdopen(fd,'a')
    if os.fstat(fd).st_uid != 0 or os.fstat(fd).st_mode & 0o022:
        f.close(); raise ValueError('unsafe_cleanup_lock')
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return f

def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('--audit-dir', required=True, type=Path)
    ap.add_argument('--protect', action='append', default=[])
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    os.umask(0o077)
    root = args.root.absolute()
    if root.resolve() != root or root.parts[-2:] != ('automation','backups'):
        raise ValueError('unregistered_root')
    if os.geteuid() != 0: raise ValueError('existing_owner_privileged_access_required')
    audit = args.audit_dir.absolute()
    if audit.resolve() != audit or audit == root or root in audit.parents:
        raise ValueError('unsafe_audit_directory')
    audit.mkdir(mode=0o700, parents=False, exist_ok=False)
    if volume(audit)['available_bytes'] < 256*1024**2: raise ValueError('audit_headroom')
    lock = cleanup_lock()
    started = time.monotonic()
    before = volume(root); deleted = 0; unlinked = 0; held = collections.Counter()
    summary = {'before':before,'deletions_executed':0,'status':'BLOCKED'}
    rootfd = os.open(root, NOFOLLOW | os.O_DIRECTORY)
    try:
        containers, baseline = health()
        ha = next(c['Id'] for c in containers if c['State']['Running']
                  and 'homeassistant' in c['Name'].lower().replace('-','').replace('_',''))
        def yaml_validator(data):
            call(['docker','exec','-i',ha,'python3','-c',
                  'import sys,yaml; x=yaml.safe_load(sys.stdin.read()); assert isinstance(x,dict)'], input=data)
        names = [n for n in os.listdir(rootfd) if family(n)]
        born = births(root,names)
        protected = set(args.protect)
        if any(not family(n) or n not in names for n in protected): raise ValueError('invalid_designated_protection')
        for c in containers:
            protected.update(m.group() for m in PATTERN.finditer(json.dumps(c.get('Config',{}))))
            for mount in c.get('Mounts',[]):
                value = mount.get('Source','')
                if value.startswith(str(root)+'/'): protected.add(value[len(str(root))+1:].split('/')[0])
        # Root-owned/current records only, not an exhaustive historical search.
        # Permission denial is an execution-access issue: never silently override it.
        protected.update(references([Path('/etc/lifeos'),Path('/var/lib/lifeos-transactions'),root.parent/'state']))
        for registry in (Path('/proc/self/mountinfo'), Path('/etc/fstab')):
            protected.update(m.group() for m in PATTERN.finditer(registry.read_text()))
        enabled = set(SOURCES)  # Historical ownership is established by fixed family/shape, not current installed revision.
        recovery = []; witnesses = {}
        (audit/'restored').mkdir(mode=0o700)
        for kind in sorted(enabled):
            passed = []
            for name in sorted((n for n in names if family(n)==kind), key=lambda n: born.get(n,0), reverse=True)[:20]:
                try:
                    record = inspect(rootfd,name)
                    hashes = restore_check(root,record,audit/'restored'/name,yaml_validator)
                    passed.append(record); witnesses[name] = hashes; protected.add(name)
                except (OSError,ValueError,SyntaxError,subprocess.SubprocessError):
                    protected.add(name); held['recovery_candidate_failed'] += 1
                if len(passed) == 2: break
            if len(passed) != 2:
                enabled.discard(kind); held['family_without_two_recovery_copies'] += 1
            else: recovery.extend(passed)
        protected.update(active_generations(root))
        candidates = []
        for name in sorted(names, key=lambda n: born.get(n,0)):
            if name in protected: held['protected_or_active'] += 1; continue
            if family(name) not in enabled: held['unverified_producer_or_recovery'] += 1; continue
            try:
                record = inspect(rootfd,name)
                if old(record,born.get(name,0)): candidates.append(record)
                else: held['recent_or_timestamp_unknown'] += 1
            except (OSError,ValueError): held['individual_metadata_hold'] += 1
        with open(audit/'manifest.jsonl','x') as manifest:
            for record in candidates: manifest.write(json.dumps(record,sort_keys=True)+'\n')
            manifest.flush(); os.fsync(manifest.fileno())
        (audit/'recovery.json').write_text(json.dumps(witnesses,sort_keys=True))
        summary.update(planned_generations=len(candidates),
                       planned_allocated_bytes=sum(r['allocated_bytes'] for r in candidates),
                       preserved_recovery_generations=len(recovery),holds=dict(held))
        if args.execute:
            with open(audit/'journal.jsonl','x') as journal:
                for offset in range(0,len(candidates),128):
                    if time.monotonic()-started > 1200: summary['status']='TIME_LIMIT'; break
                    if volume(root)['available_bytes'] >= math.ceil(before['capacity_bytes']*0.30):
                        summary['status']='TARGET_REACHED'; break
                    health(baseline)
                    for r in recovery:
                        if inspect(rootfd,r['generation']) != r: raise ValueError('recovery_point_changed')
                    active = active_generations(root)
                    for record in candidates[offset:offset+128]:
                        if record['generation'] in active:
                            held['became_active'] += 1; continue
                        # Any candidate-specific uncertainty is a skip, not a batch-wide block.
                        try:
                            if inspect(rootfd,record['generation']) != record:
                                held['candidate_changed'] += 1; continue
                        except (OSError,ValueError):
                            held['candidate_changed'] += 1; continue
                        remove_generation(rootfd,record,journal)
                        deleted += 1; unlinked += record['allocated_bytes']
                else: summary['status']='ELIGIBLE_SCOPE_COMPLETE'
            health(baseline)
            for record in recovery:
                for name, expected in witnesses[record['generation']].items():
                    if hashlib.sha256((root/record['generation']/name).read_bytes()).hexdigest() != expected:
                        raise ValueError('retained_recovery_hash_changed')
            summary['protected_service_health']='PASS'
        else: summary['status']='DRY_RUN'
    except Exception as error:
        summary['status']='STOPPED'
        summary['error_type']=type(error).__name__
        (audit/'private-error.txt').write_text(str(error))
    finally:
        os.close(rootfd)
        lock.close()
        after = volume(root)
        summary.update(after=after,deletions_executed=deleted,unlinked_allocated_bytes=unlinked,
                       measured_available_delta_bytes=after['available_bytes']-before['available_bytes'],
                       remaining_to_30_percent_bytes=max(0,math.ceil(before['capacity_bytes']*.30)-after['available_bytes']),
                       holds=dict(held),recovery_scope='isolated_file_restore_not_full_service_DR')
        (audit/'summary.json').write_text(json.dumps(summary,sort_keys=True))
        print(json.dumps(summary,sort_keys=True))
    return 1 if summary['status'] == 'STOPPED' else 0

if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status':'PREFLIGHT_STOPPED','error_type':type(exc).__name__}))
        sys.exit(1)
