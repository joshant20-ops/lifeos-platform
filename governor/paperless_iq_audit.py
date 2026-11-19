"""Fixed, privacy-preserving inspection of the existing IQ runtime; no writes."""
import json
import os
from pathlib import Path
import re
import subprocess

CHILD = r'''
import ast, hashlib, ipaddress, json, os, pathlib, signal, socket, sqlite3
import urllib.request, urllib.error, urllib.parse
signal.alarm(35)
out = {'mutations': 'NONE'}
def number(value):
    return value if type(value) is int and 0 <= value <= 10000000 else 'UNKNOWN'
def boolean(value):
    return value if type(value) is bool else 'UNKNOWN'
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
    for key, relative in {'main': 'backend/main.py', 'settings': 'backend/settings_service.py', 'monitor': 'backend/inbox_monitor.py', 'ollama': 'backend/providers/ollama_provider.py'}.items():
        if base is None:
            continue
        path = base / relative
        if path.is_symlink() or path.stat().st_size > 2097152:
            continue
        raw = path.read_bytes()
        sources[key] = raw.decode()
        ast.parse(sources[key])
        out['source_' + key + '_sha256'] = hashlib.sha256(raw).hexdigest()
    out['feature_settings_cached'] = 'self._config' in sources.get('settings', '')
    out['feature_put_rewires'] = 'new_automation and not old_automation' in sources.get('main', '')
    out['feature_seen_exclusion'] = 'did not in seen_ids' in sources.get('monitor', '')
    out['feature_all_batches_loop'] = 'for i in range(num_batches)' in sources.get('monitor', '')
    out['feature_explicit_temperature'] = 'temperature' in sources.get('ollama', '')
    out['feature_explicit_seed'] = 'seed' in sources.get('ollama', '')
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
    out['result'] = 'READ_ONLY_COMPLETE'
print(json.dumps(out, sort_keys=True))
'''

COUNTS = frozenset(('db_batch_size', 'db_poll_interval_seconds', 'tracked_documents',
    'tracked_unanalysed', 'suggestions_total', 'suggestion_documents', 'pending_total',
    'pending_documents', 'pending_duplicate_groups', 'config_backup_rows', 'iq_health_http',
    'iq_settings_unauthenticated_http', 'paperless_http', 'paperless_documents', 'ollama_http'))
BOOLS = frozenset(('db_automation_enabled', 'db_auto_apply', 'db_cron_configured',
    'db_inbox_tag_configured', 'db_model_expected', 'db_provider_local',
    'feature_settings_cached', 'feature_put_rewires', 'feature_seen_exclusion',
    'feature_all_batches_loop', 'feature_explicit_temperature', 'feature_explicit_seed',
    'iq_health_ok', 'ollama_model_available'))
HASHES = frozenset('source_' + name + '_sha256' for name in ('main', 'settings', 'monitor', 'ollama'))


def sanitise(raw):
    if len(raw) > 16384:
        raise ValueError('output_limit')
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) - (COUNTS | BOOLS | HASHES | {'result', 'mutations'}):
        raise ValueError('output_schema')
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
        if os.getloadavg()[0] >= 3:
            print('PAPERLESS_IQ_AUDIT_RESULT=DEFERRED_LOAD')
            return
        inspected = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}', 'paperless-iq'], capture_output=True, text=True, timeout=5, check=True)
        state, image, revision = inspected.stdout.strip().split('|')
        if state != 'running' or not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise ValueError('container_identity')
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
