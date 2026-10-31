#!/usr/bin/env python3
"""Read-only LAN access discovery; never emits addresses, secrets or full config."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

NPM = Path('/opt/stacks/npm')
ADGUARD = Path('/opt/stacks/adguard/conf/AdGuardHome.yaml')
HOST = 'audiobooks.lan'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=20, check=True).stdout


def certificates():
    """Public certs only; private keys are never opened."""
    candidates = []
    for root in (NPM / 'data/custom_ssl', NPM / 'letsencrypt/live'):
        if root.is_dir():
            candidates.extend(root.glob('*/fullchain.pem'))
    suitable = []
    for path in candidates:
        try:
            match = command('/usr/bin/openssl', 'x509', '-in', str(path), '-noout', '-checkhost', HOST)
            if 'does match certificate' not in match:
                continue
            command('/usr/bin/openssl', 'x509', '-in', str(path), '-noout', '-checkend', '86400')
            suitable.append(path)
        except (OSError, subprocess.SubprocessError):
            pass
    return suitable


def adguard_base():
    text = ADGUARD.read_text()
    match = re.search(r'(?m)^  address:\s*[^\n]*:(\d+)\s*$', text)
    if not match:
        raise ValueError('adguard address unknown')
    port = int(match.group(1))
    if not 1 <= port <= 65535:
        raise ValueError('adguard port invalid')
    return 'http://127.0.0.1:' + str(port)


def has_server_name(text, hostname):
    text = re.sub(r'#[^\n]*', '', text)
    return any(hostname in names.split() for names in re.findall(r'(?m)^\s*server_name\s+([^;]+);', text))


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise ValueError('root without arguments required')
    configs = list((NPM / 'data/nginx/proxy_host').glob('*.conf'))
    for host, label in (('vaultwarden.lan', 'VAULTWARDEN'), ('ha.lan', 'HA')):
        matches = [p.read_text() for p in configs if has_server_name(p.read_text(), host)]
        print('NPM_' + label + '_ROUTE=' + ('PRESENT' if matches else 'ABSENT'))
        print('NPM_' + label + '_TLS=' + ('YES' if any('ssl_certificate ' in s for s in matches) else 'NO'))
    addresses = [('LOOPBACK', '127.0.0.1')]
    try:
        route = command('ip', '-4', 'route', 'get', '1.1.1.1')
        source = re.search(r'\bsrc\s+(\d{1,3}(?:\.\d{1,3}){3})\b', route)
        if source:
            addresses.append(('LAN', source.group(1)))
    except (OSError, subprocess.SubprocessError):
        pass
    for label, address in addresses:
        for name, scheme, port, host_label in [('ha.lan', 'http', 80, 'HA'), ('vaultwarden.lan', 'https', 443, 'VAULTWARDEN')]:
            try:
                code = command('/usr/bin/curl', '--noproxy', '*', '--resolve', name + ':' + str(port) + ':' + address, '-k', '-sS', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '10', scheme + '://' + name + '/').strip()
                code = code if re.fullmatch('[0-9]{3}', code) else 'INVALID'
            except (OSError, subprocess.SubprocessError):
                code = 'UNAVAILABLE'
            print('NPM_' + host_label + '_' + label + '_HTTP=' + code)
    print('NPM_AUDIOBOOKS_CERT_READY=' + ('YES' if certificates() else 'NO'))
    try:
        with OPENER.open(adguard_base() + '/control/rewrite/list', timeout=10) as response:
            rows = json.loads(response.read(1048576))
            if not isinstance(rows, list):
                raise ValueError('invalid rewrite response')
            print('ADGUARD_REWRITE_API=READY')
            print('ADGUARD_AUDIOBOOKS_REWRITE=' + ('PRESENT' if any(r.get('domain') == HOST for r in rows if isinstance(r, dict)) else 'ABSENT'))
    except urllib.error.HTTPError as error:
        print('ADGUARD_REWRITE_API=' + ('AUTH_REQUIRED' if error.code in (401, 403) else 'HTTP_ERROR'))
    except (OSError, ValueError):
        print('ADGUARD_REWRITE_API=UNAVAILABLE')
    try:
        result = json.loads(command('/usr/bin/docker', 'exec', 'nginx-proxy-manager', 'curl', '--noproxy', '*', '-fsS', '--max-time', '10', 'http://lifeos-audiobooks/status'))
        ready = isinstance(result, dict) and result.get('app') == 'audiobookshelf' and result.get('isInit') is True
        print('NPM_AUDIOBOOKS_UPSTREAM=' + ('READY' if ready else 'INVALID'))
    except (OSError, ValueError, subprocess.SubprocessError):
        print('NPM_AUDIOBOOKS_UPSTREAM=UNAVAILABLE')
    print('AUDIOBOOKS_ACCESS_AUDIT=PASS')
    print('AUDIT_MUTATIONS=NONE')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('AUDIOBOOKS_ACCESS_AUDIT=FAIL')
        print('AUDIT_ERROR_CLASS=' + type(error).__name__)
        sys.exit(1)
