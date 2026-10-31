#!/usr/bin/env python3
"""Consistent initial encrypted backup and fixed scheduled-backup inclusion."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

REPO = Path('/home/joshan/lifeos-platform')
ROOT = Path('/mnt/docker-data/audiobookshelf')
HELPER = Path('/usr/local/sbin/lifeos-restic-backup')
PASSWORD = Path('/etc/lifeos/restic-password')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'RESTIC_REPOSITORY': '/mnt/synology-backups/restic/lifeos-pi5', 'RESTIC_PASSWORD_FILE': str(PASSWORD)}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def command(*args):
    return subprocess.run(args, capture_output=True, check=True, timeout=600, env=ENV).stdout


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise ValueError('root and no arguments required')
    os.umask(0o077)
    native = load('install_helpers', REPO / 'services/audiobookshelf/install.py')
    access = load('access_helpers', REPO / 'services/audiobookshelf/configure_access.py')
    access.directory(ROOT, private=True)
    if not ROOT.is_dir():
        raise ValueError('audiobook state missing')
    if PASSWORD.is_symlink() or not PASSWORD.is_file() or PASSWORD.stat().st_uid != 0 or PASSWORD.stat().st_mode & 0o077:
        raise ValueError('unsafe existing backup password file')
    command('/usr/bin/mountpoint', '-q', '/mnt/synology-backups')
    desired = (REPO / 'homelab/live/usr/local/sbin/lifeos-restic-backup').read_text()
    line = '    /mnt/docker-data/automation/secrets'
    original = desired.replace(line + ' \\' + '\n    /mnt/docker-data/audiobookshelf', line)
    if original == desired:
        raise ValueError('scheduled backup source missing audiobook root')
    if HELPER.is_symlink() or not HELPER.is_file() or HELPER.stat().st_uid != 0 or HELPER.stat().st_mode & 0o022:
        raise ValueError('unsafe installed backup helper')
    before_helper = HELPER.read_text()
    if before_helper not in (original, desired):
        raise ValueError('installed backup helper drift')
    manifest = ROOT / 'installation.json'
    access.private_file(manifest)
    digest = json.loads(manifest.read_text())['image']
    expected = (REPO / 'services/audiobookshelf/compose.yaml').read_text().replace(native.IMAGE, digest)
    compose = ROOT / 'compose.yaml'
    access.private_file(compose)
    if not re.fullmatch(r'ghcr.io/advplyr/audiobookshelf@sha256:[a-f0-9]{64}', digest) or compose.read_text() != expected:
        raise ValueError('installed compose drift')
    access.directory(ROOT / 'config', private=True)
    database_files = list((ROOT / 'config').glob('*.sqlite'))
    if not database_files or any(path.is_symlink() or not path.is_file() for path in database_files):
        raise ValueError('database proof unavailable')
    before = native.snapshot()
    def dc(*args):
        return command('/usr/bin/docker', 'compose', '-p', 'lifeos-audiobooks', '-f', str(compose), *args)
    own_ids = dc('ps', '-q').decode().split()
    if len(own_ids) != 1:
        raise ValueError('unexpected audiobook project size')
    own_id = own_ids[0]
    summary = None
    backup_error = None
    restart_error = None
    try:
        dc('stop')
        files = [manifest, *database_files]
        checksums = {path: hashlib.sha256(path.read_bytes()).digest() for path in files}
        output = command('/usr/bin/restic', 'backup', '--json', '--tag', 'lifeos-audiobooks', str(ROOT))
        for line in output.decode().splitlines():
            record = json.loads(line)
            if record.get('message_type') == 'summary':
                summary = record
        snapshot_id = (summary or {}).get('snapshot_id', '')
        if not re.fullmatch('[a-f0-9]{8,64}', snapshot_id):
            raise ValueError('backup snapshot proof missing')
        for path, expected_hash in checksums.items():
            restored = command('/usr/bin/restic', 'dump', snapshot_id, str(path))
            if hashlib.sha256(restored).digest() != expected_hash:
                raise ValueError('encrypted database restoration mismatch')
    except Exception as error:
        backup_error = error
    finally:
        try:
            dc('start')
            for _ in range(30):
                try:
                    if native.status().get('isInit') is True:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise ValueError('audiobook restart proof failed')
            after = native.snapshot()
            if any(after.get(key) != value for key, value in before.items() if key != own_id):
                raise ValueError('unrelated container regression')
            print('AUDIOBOOKS_RESTART=PASS')
            print('UNRELATED_CONTAINERS_UNCHANGED=YES')
        except Exception as error:
            restart_error = error
            print('AUDIOBOOKS_RESTART=FAILED_OPERATOR_REQUIRED')
    if restart_error:
        raise restart_error from backup_error
    if backup_error:
        raise backup_error
    if before_helper != desired:
        access.write(ROOT / 'scheduled-backup-helper.before', before_helper)
        access.write(HELPER, desired, HELPER.stat().st_mode & 0o777)
    access.write(ROOT / 'backup-proof.json', json.dumps({'snapshot': snapshot_id, 'database_restore_verified': True, 'scheduled': True}) + '\n')
    print('AUDIOBOOKS_ENCRYPTED_BACKUP=PASS')
    print('AUDIOBOOKS_DATABASE_RESTORE=PASS')
    print('AUDIOBOOKS_SCHEDULED_BACKUP=INCLUDED')
    print('AUDIOBOOKS_RESTART=PASS')
    print('UNRELATED_CONTAINERS_UNCHANGED=YES')
    print('AUDIOBOOKS_BACKUP_SNAPSHOT=' + snapshot_id)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('AUDIOBOOKS_BACKUP=FAIL')
        print('BACKUP_ERROR_CLASS=' + type(error).__name__)
        if isinstance(error, ValueError):
            print('BACKUP_ERROR_REASON=' + str(error).replace(' ', '_'))
        sys.exit(1)
