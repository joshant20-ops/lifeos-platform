"""Bounded local REST inventory. Only explicitly selected aggregates leave host."""
import json
import os
import pathlib
import re
import subprocess
import urllib.request

BASE = "http://127.0.0.1:8010/api/"
TOKEN = pathlib.Path("/etc/lifeos/secrets/paperless-api-token")
LIMIT = 131072
COUNTS = ("workflows", "custom_fields", "saved_views", "mail_accounts", "mail_rules")
STATS = ("documents_total", "documents_inbox", "character_count", "tag_count",
         "correspondent_count", "document_type_count", "storage_path_count")
NATIVE_COUNTS = frozenset(('DOCUMENTS', 'MISSING_CORRESPONDENT', 'MISSING_TYPE',
    'UNTAGGED', 'EMPTY_OCR', 'ADDED_LAST_30_DAYS', 'PROCESSEDMAIL_COUNT',
    'PAPERLESSTASK_COUNT', 'WORKFLOW_COUNT', 'MAILRULE_COUNT', 'SAVEDVIEW_COUNT',
    'WORKFLOW_ENABLED', 'MAILRULE_ENABLED', 'TASK_WORKERS', 'THREADS_PER_WORKER',
    'CONSUMER_POLLING', 'TASKS_FAILED_UNACKNOWLEDGED', 'TASKS_PENDING', 'TASKS_STARTED',
    'MAIL_SUCCESS_LAST_30_DAYS', 'MAIL_FAILED_COUNT'))
NATIVE_BOOLS = frozenset(('AUDIT_LOG_ENABLED', 'TIKA_ENABLED', 'CONSUMER_DELETE_DUPLICATES'))


def native_result(raw):
    """Treat even container stdout as untrusted; never forward it."""
    if len(raw) > 32768:
        return {'RESULT': 'OUTPUT_REJECTED'}
    lines = [s.removeprefix('PAPERLESS_NATIVE_JSON=') for s in raw.splitlines() if s.startswith('PAPERLESS_NATIVE_JSON=')]
    if len(lines) != 1:
        return {'RESULT': 'OUTPUT_REJECTED'}
    try:
        data = json.loads(lines[0])
    except ValueError:
        return {'RESULT': 'OUTPUT_REJECTED'}
    if not isinstance(data, dict) or set(data) - (NATIVE_COUNTS | NATIVE_BOOLS | {'VERSION', 'RESULT'}):
        return {'RESULT': 'OUTPUT_REJECTED'}
    out = {}
    for key in NATIVE_COUNTS:
        out[key] = number(data.get(key))
    for key in NATIVE_BOOLS:
        value = data.get(key)
        out[key] = value if value in ('TRUE', 'FALSE') else 'UNKNOWN'
    v = data.get('VERSION')
    out['VERSION'] = v if isinstance(v, str) and re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', v) else 'UNKNOWN'
    v = data.get('RESULT')
    out['RESULT'] = v if v in ('READ_ONLY_COMPLETE', 'UNAVAILABLE', 'DATABASE_UNSUPPORTED') else 'OUTPUT_REJECTED'
    return out


def native_inventory():
    try:
        listing = subprocess.run(['docker', 'ps', '--quiet', '--filter',
            'label=com.docker.compose.project=paperless', '--filter',
            'label=com.docker.compose.service=paperless'], capture_output=True, text=True, timeout=4, check=True)
        cid = listing.stdout.strip()
        if not re.fullmatch(r'[0-9a-f]{12,64}', cid):
            return {'RESULT': 'CONTAINER_IDENTITY_UNAVAILABLE'}
        source = pathlib.Path(__file__).with_name('paperless_native_inventory.py')
        if source.is_symlink() or source.stat().st_size > 16384:
            return {'RESULT': 'SOURCE_REJECTED'}
        script = source.read_text()
        result = subprocess.run(['docker', 'exec', cid, 'timeout', '--kill-after=2s', '30s', 'python3', 'manage.py', 'shell', '-c', script],
            capture_output=True, text=True, timeout=35, check=False)
        if result.returncode:
            return {'RESULT': 'UNAVAILABLE'}
        return native_result(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'RESULT': 'UNAVAILABLE'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def number(value):
    return value if type(value) is int and 0 <= value <= 10**15 else "UNKNOWN"


def collect(get):
    out = {"SCOPE": "TOKEN_VISIBLE_ONLY", "MUTATIONS": "NONE"}
    stats = get("statistics/")
    for key in STATS:
        out[key.upper()] = number(stats.get(key)) if isinstance(stats, dict) else "UNKNOWN"
    for endpoint in COUNTS:
        payload = get(endpoint + "/?page_size=1")
        out[endpoint.upper() + "_COUNT"] = number(payload.get("count")) if isinstance(payload, dict) else "UNKNOWN"
    out["COMPLETENESS"] = "PARTIAL" if "UNKNOWN" in out.values() else "AVAILABLE"
    return out


def main():
    try:
        if os.getloadavg()[0] >= 3:
            print("PAPERLESS_CAPABILITY_RESULT=DEFERRED_LOAD")
            return
    except OSError:
        print("PAPERLESS_CAPABILITY_RESULT=RESOURCE_UNKNOWN")
        return
    try:
        if TOKEN.is_symlink() or not TOKEN.is_file() or TOKEN.stat().st_size > 4096:
            raise ValueError()
        token = TOKEN.read_text().strip()
        if not token or any(c in token for c in "\r\n"):
            raise ValueError()
    except (OSError, ValueError, UnicodeError):
        print("PAPERLESS_CAPABILITY_RESULT=TOKEN_UNAVAILABLE")
        return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(path):
        try:
            request = urllib.request.Request(BASE + path, headers={"Authorization": "Token " + token, "Accept": "application/json"})
            with opener.open(request, timeout=4) as response:
                raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                return None
            return json.loads(raw)
        except Exception:
            # Exception text can contain private response content: suppress it.
            return None

    for key, value in collect(get).items():
        print(f"PAPERLESS_CAPABILITY_{key}={value}")
    if os.getloadavg()[0] < 3:
        for key, value in sorted(native_inventory().items()):
            print(f"PAPERLESS_NATIVE_{key}={value}")
    else:
        print('PAPERLESS_NATIVE_RESULT=DEFERRED_LOAD')


if __name__ == "__main__":
    main()
