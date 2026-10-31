#!/usr/bin/env python3
"""Fixed first-install transaction; invoked only by the reviewed root gateway."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.request

REPO = Path('/home/joshan/lifeos-platform')
ROOT = Path('/mnt/docker-data/audiobookshelf')
IMAGE = 'ghcr.io/advplyr/audiobookshelf:2.37.2'
DOCKER = '/usr/bin/docker'
PROJECT = 'lifeos-audiobooks'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=300).stdout.strip()


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request('http://127.0.0.1:13378' + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with OPENER.open(req, timeout=10) as response:
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError('response too large')
        return body


def status():
    value = json.loads(request('/status'))
    if not isinstance(value, dict) or value.get('app') != 'audiobookshelf' or value.get('serverVersion') != '2.37.2':
        raise ValueError('wrong application')
    return value


def durable_credentials(path, value):
    with path.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(value) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def snapshot():
    ids = run(DOCKER, 'ps', '-q').split()
    if not ids:
        raise ValueError('no baseline containers')
    values = json.loads(run(DOCKER, 'inspect', *ids))
    if any(v['State'].get('Status') != 'running' or v['State'].get('Health', {}).get('Status') not in (None, 'healthy') for v in values):
        raise ValueError('baseline container not healthy')
    return {v['Id']: (v['State']['StartedAt'], v['State'].get('Health', {}).get('Status')) for v in values}


def resumable_bootstrap(source):
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise ValueError('existing audiobook state preserved; inspect before retry')
    if {p.name for p in ROOT.iterdir()} - {'config', 'metadata', 'audiobooks', 'compose.yaml', 'startup.log'}:
        raise ValueError('existing audiobook state is not uninitialized bootstrap')
    for path in [ROOT, *(ROOT / name for name in ('config', 'metadata', 'audiobooks'))]:
        if path.is_symlink() or not path.is_dir() or path.stat().st_uid != 0 or path.stat().st_mode & 0o777 != 0o700:
            raise ValueError('unsafe bootstrap directory')
    path = ROOT / 'compose.yaml'
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o777 != 0o600:
        raise ValueError('unsafe bootstrap definition')
    log = ROOT / 'startup.log'
    if log.exists() or log.is_symlink():
        if log.is_symlink() or not log.is_file() or log.stat().st_uid != 0 or log.stat().st_mode & 0o777 != 0o600:
            raise ValueError('unsafe bootstrap log')
    actual = path.read_text()
    found = re.findall(r'ghcr.io/advplyr/audiobookshelf@sha256:[a-f0-9]{64}', actual)
    if len(found) != 1:
        raise ValueError('unrecognized bootstrap image')
    expected = source.replace(IMAGE, found[0]).replace('reverse_proxy', 'audiobooks_bootstrap')
    if actual not in (expected.replace('external: true', 'internal: true'), expected.replace('external: true', 'internal: false')):
        raise ValueError('unrecognized bootstrap definition')
    return found[0]


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise ValueError('root and no arguments required')
    os.umask(0o077)
    # No guessed disks: require the established SSD and stack bind mount identity.
    stack = run('/usr/bin/findmnt', '-n', '-o', 'UUID', '-T', '/opt/stacks')
    ssd = run('/usr/bin/findmnt', '-n', '-o', 'UUID', '-T', '/mnt/docker-data')
    system = run('/usr/bin/findmnt', '-n', '-o', 'UUID', '-T', '/')
    if not stack or stack != ssd or stack == system:
        raise ValueError('SSD stack mount not proven')
    if Path('/mnt/docker-data/.lifeos-opt-stacks-stage.partial').exists():
        raise ValueError('incomplete storage migration')
    if os.stat('/opt/stacks').st_dev != os.stat('/mnt/docker-data').st_dev:
        raise ValueError('storage device mismatch')
    if os.statvfs('/opt/stacks').f_bavail * os.statvfs('/opt/stacks').f_frsize < 5 * 1024**3:
        raise ValueError('less than 5 GiB available')
    source = (REPO / 'services/audiobookshelf/compose.yaml').read_text()
    resume_digest = resumable_bootstrap(source) if ROOT.exists() or ROOT.is_symlink() else None
    run(DOCKER, 'network', 'inspect', 'reverse_proxy')
    before = snapshot()
    # Refuse a conflicting project or occupied listening port before writing data.
    if run(DOCKER, 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + PROJECT):
        raise ValueError('project already exists')
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 13378))
    requested_image = resume_digest or IMAGE
    run(DOCKER, 'pull', '--platform', 'linux/arm64', requested_image)
    info = json.loads(run(DOCKER, 'image', 'inspect', requested_image))[0]
    if info.get('Architecture') != 'arm64' or info.get('Os') != 'linux':
        raise ValueError('wrong image architecture')
    digest = next((x for x in info.get('RepoDigests', []) if re.fullmatch(r'ghcr.io/advplyr/audiobookshelf@sha256:[a-f0-9]{64}', x)), None)
    if not digest or (resume_digest and digest != resume_digest):
        raise ValueError('immutable image digest unavailable')
    compose = source.replace(IMAGE, digest)
    # Never put the uninitialized server on the shared proxy network.
    bootstrap = compose.replace('reverse_proxy', 'audiobooks_bootstrap').replace('external: true', 'internal: false')
    if not resume_digest:
        ROOT.mkdir(mode=0o700)
        for name in ('config', 'metadata', 'audiobooks'):
            (ROOT / name).mkdir(mode=0o700)
    path = ROOT / 'compose.yaml'
    path.write_text(bootstrap)
    def dc(*args):
        return run(DOCKER, 'compose', '-p', PROJECT, '-f', str(path), *args)
    started = False
    try:
        dc('config', '-q')
        started = True
        dc('up', '-d', '--no-build', '--pull', 'never')
        for _ in range(30):
            try:
                state = status()
                break
            except (OSError, ValueError):
                time.sleep(2)
        else:
            raise ValueError('server startup timed out')
        if state.get('isInit') is not False:
            raise ValueError('unexpected initialized state')
        credentials = {'username': 'lifeos-admin', 'password': secrets.token_urlsafe(32)}
        # Persist before sending: an interrupted /init must not lose the password.
        durable_credentials(ROOT / 'initial-admin.json', credentials)
        request('/init', {'newRoot': credentials})
        if status().get('isInit') is not True:
            raise ValueError('initialization failed')
        path.write_text(compose)
        dc('up', '-d', '--no-build', '--pull', 'never')
        for _ in range(30):
            try:
                if status().get('isInit') is True:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(2)
        else:
            raise ValueError('initialized server restart timed out')
        after = snapshot()
        if any(after.get(key) != value for key, value in before.items()):
            raise ValueError('baseline container regression')
        # Evidence intentionally excludes credentials and private book metadata.
        (ROOT / 'installation.json').write_text(json.dumps({'image': digest, 'initialized': True, 'baseline_preserved': True}) + '\n')
        print('AUDIOBOOKS_INSTALL=PASS')
        print('AUDIOBOOKS_INITIALIZED=YES')
        print('BASELINE_CONTAINERS_UNCHANGED=YES')
        print('AUDIOBOOKS_IMAGE=' + digest)
        print('PRIVATE_PROXY_CONFIGURED=NO')
        print('PHONE_PLAYBACK_VERIFIED=NO')
    except Exception:
        if started:
            try:
                (ROOT / 'startup.log').write_text(dc('logs', '--no-color', '--tail', '200'))
            except Exception:
                print('AUDIOBOOKS_LOCAL_LOG_CAPTURE=FAILED')
            try:
                dc('down')
                print('AUDIOBOOKS_ROLLBACK=PASS_DATA_PRESERVED')
            except Exception:
                print('AUDIOBOOKS_ROLLBACK=FAILED_OPERATOR_REQUIRED')
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('AUDIOBOOKS_INSTALL=FAIL')
        print('AUDIOBOOKS_ERROR_CLASS=' + type(exc).__name__)
        if isinstance(exc, ValueError):
            print('AUDIOBOOKS_ERROR_REASON=' + str(exc).replace(' ', '_'))
        sys.exit(1)
