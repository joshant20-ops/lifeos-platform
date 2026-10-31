#!/usr/bin/env python3
"""Fixed audiobooks.lan DNS/TLS/proxy transaction; no user-controlled inputs."""
import base64
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = Path('/home/joshan/lifeos-platform')
STATE = Path('/mnt/docker-data/audiobookshelf/access')
NPM = Path('/opt/stacks/npm/data')
CUSTOM = NPM / 'nginx/custom'
ROUTE = CUSTOM / 'lifeos-audiobooks.conf'
INCLUDE = CUSTOM / 'http.conf'
CERTS = NPM / 'custom_ssl/lifeos-audiobooks'
HOST = 'audiobooks.lan'
INCLUDE_LINE = 'include /data/nginx/custom/lifeos-audiobooks.conf;\n'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def api(base, path, value=None):
    data = None if value is None else json.dumps(value).encode()
    request = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
    with OPENER.open(request, timeout=10) as response:
        body = response.read(1048576)
        if not body or body.strip() == b'OK':
            return None
        return json.loads(body)


def safe(path):
    if path.is_symlink():
        raise ValueError('symlink refused')


def private_file(path):
    safe(path)
    if path.exists() and (not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o077):
        raise ValueError('unsafe private file')


def directory(path, private=False):
    safe(path)
    if path.exists():
        meta = path.stat()
        if not path.is_dir() or meta.st_uid not in ((0,) if private else (0, 1000)) or meta.st_mode & (0o077 if private else 0o002):
            raise ValueError('unsafe directory')


def write(path, data, mode=0o600, owner=None):
    safe(path)
    tmp = path.with_name(path.name + '.lifeos-new')
    safe(tmp)
    created = False
    try:
        with tmp.open('x') as handle:
            created = True
            os.chmod(tmp, mode)
            if owner is not None:
                os.chown(tmp, *owner)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        if created:
            tmp.unlink(missing_ok=True)


def cert_pair():
    """Reuse only a known local CA that verifies the existing Vaultwarden cert."""
    refs = []
    for path in (NPM / 'nginx/proxy_host').glob('*.conf'):
        text = path.read_text()
        if re.search(r'(?m)^\s*server_name\s+vaultwarden\.lan\s*;', text):
            found = re.search(r'(?m)^\s*ssl_certificate\s+(/data/custom_ssl/[a-zA-Z0-9_-]+/fullchain.pem);', text)
            if found:
                refs.append(NPM / found.group(1).removeprefix('/data/'))
    roots = [Path('/home/joshan/.local/share/mkcert'), Path('/root/.local/share/mkcert'), NPM / 'custom_ssl']
    for root in roots:
        cert, key = root / 'rootCA.pem', root / 'rootCA-key.pem'
        if cert.is_file() and key.is_file() and not cert.is_symlink() and not key.is_symlink() and key.stat().st_uid in (0, 1000) and not key.stat().st_mode & 0o077 and not root.is_symlink() and not root.parent.is_symlink():
            for leaf in refs:
                try:
                    run('/usr/bin/openssl', 'verify', '-CAfile', str(cert), str(leaf))
                    run('/usr/bin/openssl', 'x509', '-in', str(cert), '-noout', '-checkend', '31622400')
                    return cert, key, True
                except (OSError, subprocess.SubprocessError):
                    pass
    cert, key = STATE / 'local-ca.crt', STATE / 'local-ca.key'
    private_file(cert); private_file(key)
    if cert.exists() != key.exists():
        raise ValueError('incomplete local CA state')
    if not cert.exists():
        run('/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '3650', '-subj', '/CN=LifeOS Audiobooks Local CA', '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', str(key), '-out', str(cert))
    private_file(cert); private_file(key)
    os.chmod(key, 0o600)
    return cert, key, False


def render():
    acl = 'allow 127.0.0.1; allow 10.0.0.0/8; allow 172.16.0.0/12; allow 192.168.0.0/16; deny all;'
    return '''# LifeOS managed audiobook route. Source: services/audiobookshelf/configure_access.py
server {
 listen 80;
 server_name audiobooks.lan;
 location / { %s return 301 https://audiobooks.lan$request_uri; }
}
server {
 listen 443 ssl;
 server_name audiobooks.lan;
 ssl_certificate /data/custom_ssl/lifeos-audiobooks/fullchain.pem;
 ssl_certificate_key /data/custom_ssl/lifeos-audiobooks/privkey.pem;
 ssl_protocols TLSv1.2 TLSv1.3;
 %s
 client_max_body_size 2000m;
 location / {
  proxy_pass http://lifeos-audiobooks:80;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 3600s;
  proxy_buffering off;
 }
}
''' % (acl, acl)


def verify(ca):
    body = run('/usr/bin/curl', '--noproxy', '*', '--resolve', HOST + ':443:127.0.0.1', '--cacert', str(ca), '-fsS', '--max-time', '10', 'https://' + HOST + '/status')
    value = json.loads(body)
    if not isinstance(value, dict) or value.get('app') != 'audiobookshelf' or value.get('isInit') is not True:
        raise ValueError('proxy app identity invalid')
    code = run('/usr/bin/curl', '--noproxy', '*', '--resolve', HOST + ':443:127.0.0.1', '--cacert', str(ca), '-sS', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '10', 'https://' + HOST + '/api/libraries')
    if code != '401':
        raise ValueError('unauthenticated API not rejected')


def existing_routes():
    codes = {}
    for name, scheme, port in [('ha.lan', 'http', 80), ('vaultwarden.lan', 'https', 443)]:
        codes[name] = run('/usr/bin/curl', '--noproxy', '*', '--resolve', name + ':' + str(port) + ':127.0.0.1', '-k', '-sS', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '10', scheme + '://' + name + '/')
        if codes[name] not in ('200', '301', '302', '303', '307', '308', '401'):
            raise ValueError('existing application not ready')
    return codes


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise ValueError('root and no arguments required')
    os.umask(0o077)
    audit = module('access_audit', REPO / 'services/audiobookshelf/access_audit.py')
    dns = module('dns_helper', REPO / 'scripts/lifeos-configure-ai-dns.py')
    native = module('install_helpers', REPO / 'services/audiobookshelf/install.py')
    before = native.snapshot()
    routes_before = existing_routes()
    base = audit.adguard_base()
    address = dns.pi_ipv4()
    if not ipaddress.ip_address(address).is_private:
        raise ValueError('private Pi address required')
    rows = api(base, '/control/rewrite/list')
    if not isinstance(rows, list):
        raise ValueError('invalid rewrite list')
    existing = [row for row in rows if row.get('domain') == HOST]
    if existing and existing != [{'domain': HOST, 'answer': address}]:
        raise ValueError('conflicting audiobook rewrite')
    for path in (STATE.parent, STATE):
        directory(path, private=True)
    for path in (NPM, NPM / 'nginx', CUSTOM, NPM / 'custom_ssl', CERTS):
        directory(path)
    for path in (ROUTE, INCLUDE):
        safe(path)
        if path.exists() and (not path.is_file() or path.stat().st_uid not in (0, 1000) or path.stat().st_mode & 0o002):
            raise ValueError('unsafe proxy file')
    for path in (NPM / 'nginx/proxy_host').glob('*.conf'):
        if audit.has_server_name(path.read_text(), HOST):
            raise ValueError('existing unmanaged audiobook route')
    STATE.mkdir(mode=0o700, parents=False, exist_ok=True)
    CUSTOM.mkdir(mode=0o755, parents=False, exist_ok=True)
    CERTS.mkdir(mode=0o755, parents=False, exist_ok=True)
    expected = render()
    if ROUTE.exists() and ROUTE.read_text() != expected:
        raise ValueError('managed route drift')
    old_route = ROUTE.read_text() if ROUTE.exists() else None
    old_include = INCLUDE.read_text() if INCLUDE.exists() else None
    route_mode = ROUTE.stat().st_mode & 0o777 if ROUTE.exists() else 0o644
    include_mode = INCLUDE.stat().st_mode & 0o777 if INCLUDE.exists() else 0o644
    route_owner = (ROUTE.stat().st_uid, ROUTE.stat().st_gid) if ROUTE.exists() else None
    include_owner = (INCLUDE.stat().st_uid, INCLUDE.stat().st_gid) if INCLUDE.exists() else None
    ca, ca_key, reused = cert_pair()
    key, csr, leaf, ext = (STATE / name for name in ('server.key', 'server.csr', 'server.crt', 'server.ext'))
    for path in (key, csr, leaf, ext):
        private_file(path)
    if not leaf.exists():
        ext.write_text('subjectAltName=DNS:audiobooks.lan\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
        run('/usr/bin/openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=audiobooks.lan', '-keyout', str(key), '-out', str(csr))
        run('/usr/bin/openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca), '-CAkey', str(ca_key), '-set_serial', str(secrets.randbits(159) + 1), '-days', '365', '-sha256', '-extfile', str(ext), '-out', str(leaf))
    run('/usr/bin/openssl', 'verify', '-CAfile', str(ca), '-verify_hostname', HOST, str(leaf))
    materials = {'privkey.pem': (key.read_text(), 0o600), 'fullchain.pem': (leaf.read_text() + ca.read_text(), 0o644), 'ca.crt': (ca.read_text(), 0o644)}
    created_certs = []
    for name, (content, mode) in materials.items():
        path = CERTS / name
        safe(path)
        if path.exists() and (not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o777 != mode or path.read_text() != content):
            raise ValueError('existing certificate drift')
    added = False
    try:
        for name, (content, mode) in materials.items():
            path = CERTS / name
            if not path.exists():
                created_certs.append(path)
                write(path, content, mode)
        write(ROUTE, expected, route_mode, route_owner)
        include = old_include or ''
        if INCLUDE_LINE.strip() not in include.splitlines():
            include += ('\n' if include and not include.endswith('\n') else '') + INCLUDE_LINE
        write(INCLUDE, include, include_mode, include_owner)
        run('/usr/bin/docker', 'exec', 'nginx-proxy-manager', 'nginx', '-t')
        run('/usr/bin/docker', 'exec', 'nginx-proxy-manager', 'nginx', '-s', 'reload')
        if not existing:
            added = True
            api(base, '/control/rewrite/add', {'domain': HOST, 'answer': address})
        answers, _ = dns.adguard_ipv4_answers(HOST, '127.0.0.1')
        if address not in answers:
            raise ValueError('DNS answer verification failed')
        for attempt in range(10):
            try:
                verify(ca)
                break
            except (OSError, ValueError, subprocess.SubprocessError):
                if attempt == 9:
                    raise
                time.sleep(1)
        if existing_routes() != routes_before:
            raise ValueError('existing route regression')
        after = native.snapshot()
        if any(after.get(name) != value for name, value in before.items()):
            raise ValueError('baseline container regression')
    except Exception:
        failures = []
        actions = [
            lambda: ROUTE.unlink(missing_ok=True) if old_route is None else write(ROUTE, old_route, route_mode, route_owner),
            lambda: INCLUDE.unlink(missing_ok=True) if old_include is None else write(INCLUDE, old_include, include_mode, include_owner),
        ]
        actions.extend(lambda path=path: path.unlink(missing_ok=True) for path in created_certs)
        if added:
            actions.append(lambda: api(base, '/control/rewrite/delete', {'domain': HOST, 'answer': address}))
        actions.extend([
            lambda: run('/usr/bin/docker', 'exec', 'nginx-proxy-manager', 'nginx', '-t'),
            lambda: run('/usr/bin/docker', 'exec', 'nginx-proxy-manager', 'nginx', '-s', 'reload'),
        ])
        for action in actions:
            try:
                action()
            except Exception:
                failures.append(True)
        print('AUDIOBOOKS_ACCESS_ROLLBACK=' + ('FAILED_OPERATOR_REQUIRED' if failures else 'PASS'))
        raise
    fingerprint = run('/usr/bin/openssl', 'x509', '-in', str(ca), '-noout', '-fingerprint', '-sha256').split('=', 1)[-1]
    print('AUDIOBOOKS_DNS=PASS')
    print('AUDIOBOOKS_TLS_HOSTNAME_CHAIN=PASS')
    print('AUDIOBOOKS_UNAUTH_API_REJECTION=PASS')
    print('AUDIOBOOKS_PROXY=PASS')
    print('BASELINE_CONTAINERS_UNCHANGED=YES')
    print('EXISTING_LOCAL_CA_REUSED=' + ('YES' if reused else 'NO'))
    print('AUDIOBOOKS_CA_SHA256=' + fingerprint)
    if not reused:
        # Only our newly generated generic PUBLIC certificate is exported.
        # The private CA key stays on the Pi; existing user CA identity is not exported.
        print('AUDIOBOOKS_PUBLIC_CA_PEM_B64=' + base64.b64encode((run('/usr/bin/openssl', 'x509', '-in', str(ca), '-outform', 'PEM').strip() + chr(10)).encode('ascii')).decode('ascii'))
    print('PHONE_TRUST_VERIFIED=NO')
    print('AUDIOBOOKS_ACCESS=PASS')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('AUDIOBOOKS_ACCESS=FAIL')
        print('ACCESS_ERROR_CLASS=' + type(error).__name__)
        if isinstance(error, ValueError):
            print('ACCESS_ERROR_REASON=' + str(error).replace(' ', '_'))
        sys.exit(1)
