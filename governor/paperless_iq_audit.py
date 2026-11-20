"""Fixed, privacy-preserving inspection of the existing IQ runtime; no writes."""
import json
import os
from pathlib import Path
import re
import subprocess

CHILD = r'''
import ast, hashlib, ipaddress, json, os, pathlib, re, signal, socket, sqlite3
import importlib.metadata
import urllib.request, urllib.error, urllib.parse
signal.alarm(35)
out = {'mutations': 'NONE'}
out['secret_key_env_present'] = bool(os.environ.get('SECRET_KEY'))
env_key = os.environ.get('SECRET_KEY', '').strip()
out['secret_key_env_usable'] = bool(env_key) and env_key != 'change-me-in-production'
for label, name in (('secret_key_file', '/data/.secret_key'),):
    path = pathlib.Path(name)
    try:
        info = path.lstat()
        out[label + '_present'] = True
        out[label + '_private_regular'] = __import__('stat').S_ISREG(info.st_mode) and info.st_mode & 0o777 == 0o600 and info.st_uid == os.geteuid()
    except FileNotFoundError:
        out[label + '_present'] = False
        out[label + '_private_regular'] = False
    except OSError:
        out[label + '_present'] = 'UNKNOWN'
        out[label + '_private_regular'] = 'UNKNOWN'
try:
    version = importlib.metadata.version('paperless-iq')
    out['version'] = version if re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', version) else 'UNKNOWN'
except Exception:
    out['version'] = 'UNKNOWN'
def number(value):
    return value if type(value) is int and 0 <= value <= 10000000 else 'UNKNOWN'
def boolean(value):
    return value if type(value) is bool else 'UNKNOWN'
try:
    db = pathlib.Path('/data/paperless_iq.db')
    allocated_bytes = sum(path.stat().st_blocks * 512 for path in
        (db, pathlib.Path(str(db) + '-wal')) if path.exists())
    out['db_allocated_kib'] = number(allocated_bytes // 1024)
except OSError:
    out['db_allocated_kib'] = 'UNKNOWN'
try:
    mem = dict(line.split(':', 1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())
    available = int(mem['MemAvailable'].split()[0]) * 1024
    temp = int(pathlib.Path('/sys/class/thermal/thermal_zone0/temp').read_text())
    stats = os.statvfs('/data')
    out['inside_resource_budget_ok'] = (os.getloadavg()[0] < 3 and available >= 2 * 1024**3
        and 0 < temp < 75000
        and stats.f_bavail * stats.f_frsize >= max(10 * 1024**3, stats.f_blocks * stats.f_frsize // 10)
        and stats.f_favail >= max(50000, stats.f_files // 10))
except (OSError, KeyError, ValueError, IndexError):
    out['inside_resource_budget_ok'] = 'UNKNOWN'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
def get(url, headers=None):
    try:
        parsed = urllib.parse.urlsplit(url)
        assert parsed.scheme in ('http', 'https') and not parsed.username and not parsed.password
        host = parsed.hostname or ''
        try:
            assert ipaddress.ip_address(host).is_private
        except ValueError:
            assert '.' not in host or host.endswith(('.lan', '.local')) or host == 'host.docker.internal'
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        assert addresses and all(ipaddress.ip_address(row[4][0]).is_private for row in addresses)
        request = urllib.request.Request(url, headers=headers or {})
        with opener.open(request, timeout=4) as response:
            raw = response.read(131073)
            if len(raw) > 131072:
                return response.status, None
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return 0, None
try:
    connection = sqlite3.connect('file:/data/paperless_iq.db?mode=ro', uri=True, timeout=2)
    connection.execute('PRAGMA query_only=ON')
    row = connection.execute('SELECT config_json FROM settings WHERE id=1').fetchone()
    config = json.loads(row[0]) if row else {}
    for key in ('automation_enabled', 'auto_apply'):
        out['db_' + key] = boolean(config.get(key))
    for key in ('batch_size', 'poll_interval_seconds'):
        out['db_' + key] = number(config.get(key))
    cron = config.get('schedule_cron')
    out['db_cron_configured'] = bool(cron)
    out['db_inbox_tag_configured'] = type(config.get('inbox_tag_id')) is int
    out['db_model_expected'] = config.get('llm_model') == 'gpt-oss:20b'
    out['db_provider_local'] = config.get('llm_provider') == 'ollama'
    queries = {
        'tracked_documents': 'SELECT count(*) FROM document_tracking',
        'tracked_unanalysed': 'SELECT count(*) FROM document_tracking WHERE last_analyzed_at IS NULL',
        'suggestions_total': 'SELECT count(*) FROM suggestions',
        'suggestion_documents': 'SELECT count(DISTINCT document_id) FROM suggestions',
        'pending_total': "SELECT count(*) FROM suggestions WHERE status='pending'",
        'pending_documents': "SELECT count(DISTINCT document_id) FROM suggestions WHERE status='pending'",
        'pending_duplicate_groups': "SELECT count(*) FROM (SELECT document_id FROM suggestions WHERE status='pending' GROUP BY document_id HAVING count(*) > 1)",
        'config_backup_rows': 'SELECT count(*) FROM automation_config_backup',
    }
    for key, sql in queries.items():
        try:
            out[key] = number(connection.execute(sql).fetchone()[0])
        except sqlite3.Error:
            out[key] = 'UNKNOWN'
    connection.close()
    base = next((root for root in (pathlib.Path.cwd(), pathlib.Path('/app'), pathlib.Path('/app/src')) if (root / 'backend/main.py').is_file()), None)
    sources = {}
    for key, relative in {'main': 'backend/main.py', 'settings': 'backend/settings_service.py', 'monitor': 'backend/inbox_monitor.py', 'ollama': 'backend/providers/ollama_provider.py', 'models': 'backend/models.py', 'queue': 'backend/approval_queue.py'}.items():
        if base is None:
            continue
        try:
            path = base / relative
            if path.is_symlink() or path.stat().st_size > 2097152:
                continue
            raw = path.read_bytes()
            code = raw.decode()
            ast.parse(code)
        except (OSError, UnicodeError, SyntaxError):
            continue
        sources[key] = code
        out['source_' + key + '_sha256'] = hashlib.sha256(raw).hexdigest()
    features = {
        'feature_settings_cached': ('settings', 'self._config'),
        'feature_put_rewires': ('main', 'new_automation and not old_automation'),
        'feature_seen_exclusion': ('monitor', 'did not in seen_ids'),
        'feature_all_batches_loop': ('monitor', 'for i in range(num_batches)'),
        'feature_explicit_temperature': ('ollama', 'temperature'),
        'feature_explicit_seed': ('ollama', 'seed'),
    }
    for key, (source, needle) in features.items():
        out[key] = needle in sources[source] if source in sources else 'UNKNOWN'
    status, payload = get('http://127.0.0.1:8080/health')
    out['iq_health_http'] = number(status)
    out['iq_health_ok'] = isinstance(payload, dict) and payload.get('status') == 'ok'
    status, _ = get('http://127.0.0.1:8080/api/settings')
    out['iq_settings_unauthenticated_http'] = number(status)
    base_url = os.environ.get('PAPERLESS_URL', '').rstrip('/')
    token = os.environ.get('PAPERLESS_TOKEN', '')
    if base_url and token:
        status, payload = get(base_url + '/api/statistics/', {'Authorization': 'Token ' + token})
        out['paperless_http'] = number(status)
        out['paperless_documents'] = number(payload.get('documents_total')) if isinstance(payload, dict) else 'UNKNOWN'
    if config.get('llm_provider') == 'ollama' and isinstance(config.get('ollama_url'), str):
        status, payload = get(config['ollama_url'].rstrip('/') + '/api/tags')
        out['ollama_http'] = number(status)
        out['ollama_model_available'] = isinstance(payload, dict) and any(model.get('name') == config.get('llm_model') or model.get('model') == config.get('llm_model') for model in payload.get('models', []) if isinstance(model, dict))
except Exception:
    out['result'] = 'PARTIAL_OR_UNAVAILABLE'
else:
    out['result'] = 'READ_ONLY_COMPLETE' if len(sources) == 6 else 'PARTIAL_OR_UNAVAILABLE'
print(json.dumps(out, sort_keys=True))
'''

COUNTS = frozenset(('db_batch_size', 'db_poll_interval_seconds', 'tracked_documents',
    'tracked_unanalysed', 'suggestions_total', 'suggestion_documents', 'pending_total',
    'pending_documents', 'pending_duplicate_groups', 'config_backup_rows', 'iq_health_http',
    'iq_settings_unauthenticated_http', 'paperless_http', 'paperless_documents', 'ollama_http', 'db_allocated_kib'))
BOOLS = frozenset(('db_automation_enabled', 'db_auto_apply', 'db_cron_configured',
    'db_inbox_tag_configured', 'db_model_expected', 'db_provider_local',
    'feature_settings_cached', 'feature_put_rewires', 'feature_seen_exclusion',
    'feature_all_batches_loop', 'feature_explicit_temperature', 'feature_explicit_seed',
    'iq_health_ok', 'ollama_model_available'))
BOOLS = BOOLS | frozenset(('secret_key_env_present', 'secret_key_env_usable',
    'secret_key_file_present', 'secret_key_file_private_regular', 'inside_resource_budget_ok'))
HASHES = frozenset('source_' + name + '_sha256' for name in ('main', 'settings', 'monitor', 'ollama', 'models', 'queue'))

COMPOSE_ROOTS = {
    '/home/joshan/paperless': 'HOME_PAPERLESS',
    '/home/joshan/paperless-iq': 'HOME_PAPERLESS_IQ',
    '/opt/stacks/paperless-iq': 'STACKS_PAPERLESS_IQ',
}
COMPOSE_FILES = frozenset(('compose.yml', 'compose.yaml', 'docker-compose.yml', 'docker-compose.yaml'))


def runtime_metadata(data):
    """Project only fixed labels and bounded values from private inspect data."""
    config = data.get('Config') or {}
    labels = config.get('Labels') or {}
    root = labels.get('com.docker.compose.project.working_dir')
    files = labels.get('com.docker.compose.project.config_files', '').split(',')
    layout = COMPOSE_ROOTS.get(root, 'UNKNOWN')
    if layout != 'UNKNOWN' and (not files or any(
            str(Path(name).parent) != root or Path(name).name not in COMPOSE_FILES
            for name in files)):
        layout = 'UNKNOWN'
    environment = dict(entry.split('=', 1) for entry in config.get('Env', [])
                       if isinstance(entry, str) and '=' in entry)
    entrypoint, arguments = config.get('Entrypoint') or [], config.get('Cmd') or []
    command = entrypoint + arguments if isinstance(entrypoint, list) and isinstance(arguments, list) else []
    uvicorn = any(isinstance(word, str) and Path(word).name == 'uvicorn' for word in command)
    workers = []
    for index, word in enumerate(command):
        if word == '--workers' and index + 1 < len(command):
            workers.append(command[index + 1])
        elif isinstance(word, str) and word.startswith('--workers='):
            workers.append(word.partition('=')[2])
    workers.extend(environment[key] for key in ('WEB_CONCURRENCY', 'UVICORN_WORKERS') if key in environment)
    project = labels.get('com.docker.compose.project')
    service = labels.get('com.docker.compose.service')
    mounts = [item.get('Type') for item in data.get('Mounts', []) if item.get('Destination') == '/data']
    restart = (data.get('HostConfig') or {}).get('RestartPolicy', {}).get('Name')
    return {
        'compose_project': project if project in ('paperless', 'paperless-iq') else 'UNKNOWN',
        'compose_service': service if service in ('paperless-iq', 'iq') else 'UNKNOWN',
        'compose_layout': layout,
        'data_mount_type': mounts[0] if len(mounts) == 1 and mounts[0] in ('bind', 'volume', 'tmpfs') else 'UNKNOWN',
        'application_mount_overlay': any(str(item.get('Destination', '')).rstrip('/') in ('/app', '/app/backend', '/app/src', '/app/src/backend') or str(item.get('Destination', '')).startswith(('/app/backend/', '/app/src/backend/')) for item in data.get('Mounts', [])),
        'single_worker_default_command': command == ['uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', '8080', '--log-level', 'info'] and not workers,
        'restart_policy': restart if restart in ('no', 'always', 'unless-stopped', 'on-failure') else 'UNKNOWN',
        'single_worker_declared': all(value == '1' for value in workers) if workers and uvicorn else 'UNKNOWN',
    }


def build_cache_manifest(raw):
    """Conservative engineering-cache candidates, never deletion permission."""
    if len(raw) > 1048576:
        raise ValueError('build_cache_limit')
    records, seen = [], set()
    for line in raw.splitlines():
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError('build_cache_object')
        identifier = row.get('ID')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9]{12,64}', identifier):
            raise ValueError('build_cache_id')
        if identifier in seen:
            raise ValueError('build_cache_duplicate')
        seen.add(identifier)
        size = str(row.get('Size', ''))
        if (row.get('Reclaimable') is True and row.get('Mutable') is False
                and row.get('Shared') is False and row.get('Type') == 'regular'
                and re.fullmatch(r'[0-9]{1,13}', size) and 0 < int(size) <= 10**12):
            records.append({'id': identifier, 'estimated_bytes': int(size)})
    records.sort(key=lambda row: (row['estimated_bytes'], row['id']))
    # A review packet, not an unbounded inventory or permission to clean.
    selected, total = [], 0
    for row in records:
        if len(selected) >= 20 or total >= 512 * 1024**2:
            break
        if total + row['estimated_bytes'] <= 1024**3:
            selected.append(row)
            total += row['estimated_bytes']
    import hashlib
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'records': selected, 'estimated_bytes': total, 'manifest_sha256': digest,
            'basis': 'BUILDKIT_UNUSED_IMMUTABLE_UNSHARED_REGULAR', 'deletion_authorised': False}


def docker_capacity_summary():
    """Bounded daemon accounting only; no prune, scans or private inventory."""
    result = {}
    try:
        raw = subprocess.run(['docker', 'system', 'df', '--format', '{{json .}}'],
            capture_output=True, text=True, timeout=12, check=True).stdout
        if len(raw) > 16384:
            raise ValueError('summary_limit')
        for line in raw.splitlines():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('summary_object')
            kind = row.get('Type')
            if kind not in ('Images', 'Containers', 'Local Volumes', 'Build Cache'):
                continue
            clean = {}
            for key in ('TotalCount', 'Active'):
                value = str(row.get(key, ''))
                clean[key] = int(value) if re.fullmatch(r'[0-9]{1,7}', value) else 'UNKNOWN'
            for key in ('Size', 'Reclaimable'):
                value = str(row.get(key, ''))
                clean[key] = value if re.fullmatch(r'[0-9]+(?:\.[0-9]+)? ?(?:B|kB|KB|MB|GB|TB)(?: \([0-9]+%\))?', value) else 'UNKNOWN'
            result[kind] = clean
        root = subprocess.run(['docker', 'info', '--format', '{{.DockerRootDir}}'],
            capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        data_root = Path('/mnt/docker-data')
        result['docker_root_on_hdd'] = (data_root.is_mount()
            and Path(root).resolve().is_relative_to(data_root)
            and Path(root).stat().st_dev == data_root.stat().st_dev)
        try:
            builder = subprocess.run(['docker', 'buildx', 'inspect', 'default'],
                capture_output=True, text=True, timeout=5, check=True).stdout
            if len(builder) > 16384:
                raise ValueError('builder_limit')
            fields = [line.strip().split(':', 1) for line in builder.splitlines() if ':' in line]
            drivers = [value.strip() for key, value in fields if key == 'Driver']
            endpoints = [value.strip() for key, value in fields if key == 'Endpoint']
            context = subprocess.run(['docker', 'context', 'inspect', 'default', '--format', '{{.Endpoints.docker.Host}}'],
                capture_output=True, text=True, timeout=5, check=True).stdout.strip()
            result['default_builder_local_docker'] = (drivers == ['docker'] and len(endpoints) == 1
                and endpoints[0] in ('default', 'unix:///var/run/docker.sock')
                and context == 'unix:///var/run/docker.sock')
            if not result['default_builder_local_docker']:
                raise ValueError('unverified_builder')
            usage = subprocess.run(['docker', 'buildx', 'du', '--builder', 'default', '--format=json'],
                capture_output=True, text=True, timeout=8, check=True).stdout
            result['build_cache_manifest'] = build_cache_manifest(usage)
        except (OSError, ValueError, subprocess.SubprocessError):
            result['build_cache_manifest'] = {'status': 'UNAVAILABLE', 'deletion_authorised': False}

    except (OSError, ValueError, subprocess.SubprocessError):
        result['status'] = 'PARTIAL_OR_UNAVAILABLE'
    return result


def host_resources():
    report = {'cpu_load_milli': 'UNKNOWN', 'memory_available_mib': 'UNKNOWN',
              'temperature_millicelsius': 'UNKNOWN', 'free_data_bytes': 'UNKNOWN',
              'data_reserve_met': 'UNKNOWN'}
    try:
        load = round(os.getloadavg()[0] * 1000)
        if 0 <= load <= 10000000:
            report['cpu_load_milli'] = load
    except (OSError, ValueError, OverflowError):
        pass
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                available = int(line.split()[1]) // 1024
                if 0 <= available <= 10000000:
                    report['memory_available_mib'] = available
    except (OSError, ValueError, IndexError):
        pass
    try:
        temperature = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())
        if 0 <= temperature <= 150000:
            report['temperature_millicelsius'] = temperature
    except (OSError, ValueError, IndexError):
        pass
    try:
        root = Path('/mnt/docker-data')
        if root.is_mount():
            info = os.statvfs(root)
            report['free_data_bytes'] = info.f_bavail * info.f_frsize
            report['data_reserve_met'] = (report['free_data_bytes'] >= max(10 * 1024**3, info.f_blocks * info.f_frsize // 10)
                                          and info.f_files > 0 and info.f_favail * 10 >= info.f_files)
    except OSError:
        pass
    return report


def sanitise(raw):
    if len(raw) > 16384:
        raise ValueError('output_limit')
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) - (COUNTS | BOOLS | HASHES | {'result', 'mutations', 'version'}):
        raise ValueError('output_schema')
    if data.get('version', 'UNKNOWN') != 'UNKNOWN' and (not isinstance(data['version'], str) or not re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', data['version'])):
        raise ValueError('version')
    for key, value in data.items():
        if key in COUNTS and value != 'UNKNOWN' and not (type(value) is int and 0 <= value <= 10000000):
            raise ValueError('count')
        if key in BOOLS and value != 'UNKNOWN' and type(value) is not bool:
            raise ValueError('boolean')
        if key in HASHES and (not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)):
            raise ValueError('source_hash')
    if data.get('mutations') != 'NONE' or data.get('result') not in ('READ_ONLY_COMPLETE', 'PARTIAL_OR_UNAVAILABLE'):
        raise ValueError('result')
    return data


def main():
    try:
        print('PAPERLESS_IQ_RESOURCES=' + json.dumps(host_resources(), sort_keys=True))
        if os.getloadavg()[0] >= 3:
            print('PAPERLESS_IQ_AUDIT_RESULT=DEFERRED_LOAD')
            return
        print('PAPERLESS_IQ_DOCKER_CAPACITY=' + json.dumps(docker_capacity_summary(), sort_keys=True))
        inspected = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}', 'paperless-iq'], capture_output=True, text=True, timeout=5, check=True)
        state, image, revision = inspected.stdout.strip().split('|')
        if state != 'running' or not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise ValueError('container_identity')
        template = '{"Config":{"Labels":{{json .Config.Labels}},"Env":{{json .Config.Env}},"Entrypoint":{{json .Config.Entrypoint}},"Cmd":{{json .Config.Cmd}}},"Mounts":{{json .Mounts}},"HostConfig":{"RestartPolicy":{{json .HostConfig.RestartPolicy}}}}'
        raw_metadata = subprocess.run(['docker', 'inspect', '--format', template, 'paperless-iq'], capture_output=True, text=True, timeout=5, check=True).stdout
        if len(raw_metadata) > 262144:
            raise ValueError('metadata_limit')
        print('PAPERLESS_IQ_RUNTIME=' + json.dumps(runtime_metadata(json.loads(raw_metadata)), sort_keys=True))
        print('PAPERLESS_IQ_IMAGE=' + image)
        if re.fullmatch('[a-f0-9]{40}', revision):
            print('PAPERLESS_IQ_UPSTREAM_REVISION=' + revision)
        application = subprocess.run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=paperless', '--filter', 'label=com.docker.compose.service=paperless'], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        if re.fullmatch('[a-f0-9]{12,64}', application):
            raw = subprocess.run(['docker', 'inspect', '--format', '{{json .Config.Env}}', application], capture_output=True, text=True, timeout=5, check=True).stdout
            if len(raw) <= 65536:
                environment = dict(entry.split('=', 1) for entry in json.loads(raw) if '=' in entry)
                available = bool(environment.get('PAPERLESS_ADMIN_USER') and environment.get('PAPERLESS_ADMIN_PASSWORD'))
                print('PAPERLESS_IQ_EXISTING_LOGIN_CREDENTIALS_PRESENT=' + ('YES' if available else 'NO'))
        result = subprocess.run(['docker', 'exec', 'paperless-iq', 'python3', '-I', '-B', '-c', CHILD], capture_output=True, text=True, timeout=40, check=True)
        print('PAPERLESS_IQ_AUDIT=' + json.dumps(sanitise(result.stdout), sort_keys=True))
    except (OSError, ValueError, subprocess.SubprocessError):
        print('PAPERLESS_IQ_AUDIT_RESULT=UNAVAILABLE')


if __name__ == '__main__':
    main()
