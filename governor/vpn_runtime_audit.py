#!/usr/bin/env python3
"""Read-only WireGuard/router evidence; never output keys or peer addresses."""
import ipaddress
import json
import os
from pathlib import Path
import platform
import pwd
import re
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET


def run(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def wireguard_summary(port, handshakes, transfers):
    received = {}
    for line in (transfers or '').splitlines():
        values = line.split()
        if len(values) == 3 and all(x.isdigit() for x in values[1:]):
            received[values[0]] = [int(x) for x in values[1:]]
    peers = []
    for line in (handshakes or '').splitlines():
        values = line.split()
        if len(values) == 2 and values[1].isdigit():
            stamp = int(values[1])
            peers.append({'peer': len(peers) + 1, 'handshake_age_seconds': max(0, int(time.time()) - stamp) if stamp else None,
                          'received_bytes': received.get(values[0], [0, 0])[0], 'sent_bytes': received.get(values[0], [0, 0])[1]})
    return {'listen_port': int(port) if str(port).isdigit() else None, 'peers': peers}


def capture_reports(directory, owner):
    reports = []
    for path in sorted(directory.glob('lifeos-vpn-check.*'), key=lambda p: p.lstat().st_mtime, reverse=True)[:3]:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_size > 4096
                or info.st_mode & 0o077 or time.time() - info.st_mtime > 7200):
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                lines = stream.read(4096).splitlines()
        except OSError:
            continue
        result = {'age_seconds': max(0, int(time.time() - info.st_mtime)), 'complete': False}
        for line in lines:
            if line == 'VPN_PACKET_CHECK=FINISHED':
                result['complete'] = True
            match = re.fullmatch(r'VPN_PACKETS_(IN|OUT)=(\d+)', line)
            if match:
                result[match[1].lower()] = int(match[2])
        reports.append(result)
    return reports


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def router_url(url, gateway):
    parsed = urlsplit(url)
    if parsed.hostname != gateway or parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password:
        raise ValueError('non_router_url')
    return url


def endpoint_metadata(text):
    values = {}
    for key in ('pivpnHOST', 'pivpnPORT'):
        match = re.search(r'^' + key + r'=(.*)$', text, re.M)
        if match:
            values[key] = match[1].strip().strip('\"\'')
    host = values.get('pivpnHOST', '')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host):
        return None, None
    port = values.get('pivpnPORT', '')
    return host, int(port) if port.isdigit() and 0 < int(port) < 65536 else None


def router_status(gateway, local_address, port, endpoint_addresses=()):
    if not gateway or not local_address or not port:
        return {'status': 'NO_ROUTE_OR_LISTENER'}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    location = None
    message = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
               'MAN: "ssdp:discover"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n').encode()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            stream.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_address))
            stream.settimeout(0.5)
            stream.sendto(message, ('239.255.255.250', 1900))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    data, peer = stream.recvfrom(8192)
                except socket.timeout:
                    continue
                if peer[0] != gateway:
                    continue
                for line in data.decode(errors='replace').splitlines():
                    if line.lower().startswith('location:'):
                        location = router_url(line.split(':', 1)[1].strip(), gateway)
                if location:
                    break
        if not location:
            return {'status': 'UPNP_NOT_AVAILABLE'}
        with opener.open(location, timeout=4) as response:
            root = ET.fromstring(response.read(262144))
        result = {'status': 'UPNP_AVAILABLE'}
        for field in ('manufacturer', 'modelName', 'modelNumber'):
            value = root.findtext('.//{*}' + field) or ''
            result[field] = re.sub(r'[^A-Za-z0-9 ._+()-]', '', value)[:100]
        services = [s for s in root.findall('.//{*}service')
                    if any(x in (s.findtext('{*}serviceType') or '') for x in (':WANIPConnection:', ':WANPPPConnection:'))]
        for service in services[:1]:
            kind = service.findtext('{*}serviceType')
            control = router_url(urljoin(location, service.findtext('{*}controlURL') or ''), gateway)
            for action, arguments in (
                ('GetStatusInfo', ''),
                ('GetExternalIPAddress', ''),
                ('GetSpecificPortMappingEntry', '<NewRemoteHost></NewRemoteHost><NewExternalPort>' + str(port) +
                 '</NewExternalPort><NewProtocol>UDP</NewProtocol>'),
            ):
                body = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:' + action +
                        ' xmlns:u="' + kind + '">' + arguments + '</u:' + action + '></s:Body></s:Envelope>').encode()
                request = urllib.request.Request(control, data=body, method='POST', headers={
                    'Content-Type': 'text/xml; charset="utf-8"', 'SOAPAction': '"' + kind + '#' + action + '"'})
                try:
                    with opener.open(request, timeout=4) as response:
                        reply = ET.fromstring(response.read(65536))
                    if action == 'GetStatusInfo':
                        for field in ('NewConnectionStatus', 'NewLastConnectionError'):
                            value = reply.findtext('.//{*}' + field) or ''
                            result[field] = value if re.fullmatch(r'[A-Za-z_]{1,80}', value) else 'UNKNOWN'
                    elif action == 'GetExternalIPAddress':
                        address = ipaddress.IPv4Address(reply.findtext('.//{*}NewExternalIPAddress') or '')
                        result['wan_ipv4_is_public'] = address.is_global
                        if endpoint_addresses:
                            result['saved_endpoint_matches_wan'] = str(address) in endpoint_addresses
                    else:
                        result['udp_mapping_listed'] = True
                        result['mapping_targets_pi'] = reply.findtext('.//{*}NewInternalClient') == local_address
                        value = reply.findtext('.//{*}NewInternalPort') or ''
                        result['mapping_internal_port'] = int(value) if value.isdigit() else None
                        result['mapping_enabled'] = reply.findtext('.//{*}NewEnabled') in {'1', 'true'}
                except urllib.error.HTTPError as error:
                    reply = ET.fromstring(error.read(65536))
                    code = reply.findtext('.//{*}errorCode') or ''
                    result[action + '_error'] = int(code) if code.isdigit() else error.code
        return result
    except (OSError, ValueError, ET.ParseError, urllib.error.URLError):
        return {'status': 'ROUTER_QUERY_UNAVAILABLE'}


def main():
    if platform.node() != 'Docker' or os.geteuid() != 0:
        print('VPN_AUDIT=WRONG_RUNTIME')
        return 20
    try:
        summary = wireguard_summary(run('wg', 'show', 'wg0', 'listen-port'),
            run('wg', 'show', 'wg0', 'latest-handshakes'), run('wg', 'show', 'wg0', 'transfer'))
        print('VPN_RUNTIME=' + json.dumps(summary, separators=(',', ':')))
        print('VPN_SAVED_PACKET_TESTS=' + json.dumps(capture_reports(Path('/tmp'), pwd.getpwnam('joshan').pw_uid)))
        print('VPN_IPV4_FORWARDING=' + ('ENABLED' if Path('/proc/sys/net/ipv4/ip_forward').read_text().strip() == '1' else 'DISABLED'))
        routes = json.loads(run('ip', '-j', '-4', 'route', 'get', '1.1.1.1') or '[]')
        route = routes[0] if routes else {}
        gateway, local = route.get('gateway'), route.get('prefsrc')
        if gateway and local:
            ipaddress.IPv4Address(gateway)
            ipaddress.IPv4Address(local)
        endpoint, endpoint_port, addresses = None, None, set()
        setup = Path('/etc/pivpn/wireguard/setupVars.conf')
        if setup.is_file() and not setup.is_symlink():
            endpoint, endpoint_port = endpoint_metadata(setup.read_text()[:16384])
        if endpoint:
            try:
                addresses.add(str(ipaddress.IPv4Address(endpoint)))
                kind = 'IPV4'
            except ipaddress.AddressValueError:
                kind = 'HOSTNAME'
                for line in (run('getent', 'ahostsv4', endpoint) or '').splitlines():
                    try:
                        addresses.add(str(ipaddress.IPv4Address(line.split()[0])))
                    except (ipaddress.AddressValueError, IndexError):
                        pass
            print('VPN_SAVED_ENDPOINT=' + json.dumps({'kind': kind, 'resolution_available': bool(addresses),
                  'port_matches_listener': endpoint_port == summary['listen_port']}))
        else:
            print('VPN_SAVED_ENDPOINT=NOT_AVAILABLE')
        print('VPN_ROUTER=' + json.dumps(router_status(gateway, local, summary['listen_port'], addresses), separators=(',', ':')))
        print('VPN_AUDIT_MUTATIONS=NONE')
        print('VPN_AUDIT=PASS')
        return 0
    except Exception:
        print('VPN_AUDIT=EVIDENCE_UNAVAILABLE')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
