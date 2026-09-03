#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
ENV_FILE=/etc/lifeos/semaphore.env
SECRETS=/etc/lifeos/semaphore-secrets
PROJECT_NAME='LifeOS Shadow Proof'
TEMPLATE_NAME='Read-only platform proof'

[[ $EUID -eq 0 ]] || { echo 'ERROR: run via sudo'; exit 1; }
[[ -r "$ENV_FILE" ]] || { echo 'ERROR: semaphore env missing'; exit 1; }
for f in admin_user admin_password; do [[ -r "$SECRETS/$f" ]] || { echo "ERROR: missing secret $f"; exit 1; }; done

BIND_IP=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE")
[[ -n "$BIND_IP" ]] || { echo 'ERROR: Semaphore bind IP missing'; exit 1; }
BASE="http://${BIND_IP}:3000/api"

HEAD_BEFORE=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
INDEX_OWNER_BEFORE=$(stat -c '%U:%G' "$PLATFORM/.git/index")

units=(
  lifeos-backlog-runner.timer
  lifeos-engineer-dispatcher.timer
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
)

snapshot_units() {
  local u
  for u in "${units[@]}"; do
    printf '%s=%s/%s\n' "$u" \
      "$(systemctl is-active "$u" 2>/dev/null || true)" \
      "$(systemctl is-enabled "$u" 2>/dev/null || true)"
  done
}

UNITS_BEFORE=$(snapshot_units)

echo 'SEMAPHORE_READONLY_PROOF_VERSION=3'
echo 'MUTATIONS=SEMAPHORE_CATALOGUE_ONLY'
echo "platform_head=$HEAD_BEFORE"
echo "semaphore_base=$BASE"

curl -fsS --max-time 5 "$BASE/ping" >/dev/null || { echo 'ERROR: Semaphore API unavailable'; exit 1; }

export LIFEOS_SEMAPHORE_BASE="$BASE"
export LIFEOS_SEMAPHORE_ADMIN_USER_FILE="$SECRETS/admin_user"
export LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE="$SECRETS/admin_password"
export LIFEOS_SEMAPHORE_PROJECT_NAME="$PROJECT_NAME"
export LIFEOS_SEMAPHORE_TEMPLATE_NAME="$TEMPLATE_NAME"
export LIFEOS_PLATFORM_HEAD="$HEAD_BEFORE"

python3 - <<'PY'
import http.cookiejar
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

base = os.environ['LIFEOS_SEMAPHORE_BASE'].rstrip('/')
login = pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_USER_FILE']).read_text().strip()
password = pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE']).read_text().strip()
project_name = os.environ['LIFEOS_SEMAPHORE_PROJECT_NAME']
template_name = os.environ['LIFEOS_SEMAPHORE_TEMPLATE_NAME']
expected_head = os.environ['LIFEOS_PLATFORM_HEAD']

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def request(method, path, body=None, token=None, timeout=15):
    data = None if body is None else json.dumps(body).encode()
    headers = {'Accept': 'application/json'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read()
            ctype = r.headers.get('Content-Type', '')
            if 'json' in ctype and raw:
                return json.loads(raw)
            return raw.decode(errors='replace')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')[:1200]
        raise RuntimeError(f'{method} {path} HTTP {exc.code}: {detail}') from exc

request('POST', '/auth/login', {'auth': login, 'password': password})
tok = request('POST', '/user/tokens')
token = tok['id'] if isinstance(tok, dict) else None
if not token:
    raise RuntimeError('Semaphore token creation returned no id')

try:
    projects = request('GET', '/projects', token=token)
    project = next((p for p in projects if p.get('name') == project_name), None)

    if project is None:
        backup = {
            'meta': {
                'name': project_name,
                'alert': False,
                'alert_chat': '',
                'max_parallel_tasks': 1,
                'type': ''
            },
            'keys': [
                {'name': 'None', 'type': 'none'}
            ],
            'repositories': [
                {
                    'name': 'LifeOS Platform Read Only',
                    'git_url': '/workspace/lifeos-platform',
                    'git_branch': 'main',
                    'ssh_key': 'None'
                }
            ],
            'inventories': [
                {
                    'name': 'Localhost Read Only',
                    'inventory': 'localhost ansible_connection=local',
                    'ssh_key': 'None',
                    'become_key': 'None',
                    'type': 'static'
                }
            ],
            'environments': [
                {'name': 'Empty', 'password': None, 'json': '{}', 'env': '{}'}
            ],
            'views': [
                {'title': 'Proof', 'position': 0}
            ],
            'templates': [
                {
                    'inventory': 'Localhost Read Only',
                    'repository': 'LifeOS Platform Read Only',
                    'environment': 'Empty',
                    'view': 'Proof',
                    'name': template_name,
                    'playbook': 'orchestration/semaphore/playbooks/read-only-proof.yml',
                    'arguments': '[]',
                    'allow_override_args_in_task': False,
                    'description': 'Read-only LifeOS execution-plane proof',
                    'app': 'ansible',
                    'type': '',
                    'start_version': '',
                    'build_template': None,
                    'autorun': False,
                    'survey_vars': [],
                    'suppress_success_alerts': True,
                    'cron': ''
                }
            ]
        }
        request('POST', '/projects/restore', backup, token=token, timeout=30)
        projects = request('GET', '/projects', token=token)
        project = next((p for p in projects if p.get('name') == project_name), None)
        if project is None:
            raise RuntimeError('restored proof project not found')
        print(f'PROJECT_STATE=CREATED id={project["id"]}')
    else:
        print(f'PROJECT_STATE=REUSED id={project["id"]}')

    pid = int(project['id'])
    templates = request('GET', f'/project/{pid}/templates', token=token)
    template = next((t for t in templates if t.get('name') == template_name), None)
    if template is None:
        raise RuntimeError('proof template missing from project')
    tid = int(template['id'])

    if str(template.get('app') or '').lower() != 'ansible':
        repaired = dict(template)
        repaired['app'] = 'ansible'
        repaired['type'] = repaired.get('type') or ''
        repaired['arguments'] = repaired.get('arguments') or '[]'
        repaired['allow_override_args_in_task'] = False
        repaired['suppress_success_alerts'] = True
        request('PUT', f'/project/{pid}/templates/{tid}', repaired, token=token, timeout=30)
        template = request('GET', f'/project/{pid}/templates/{tid}', token=token)
        if str(template.get('app') or '').lower() != 'ansible':
            raise RuntimeError('proof template app repair did not persist')
        print('TEMPLATE_APP_REPAIRED=ansible')
    else:
        print('TEMPLATE_APP=ansible')

    print(f'TEMPLATE_ID={tid}')

    task = request('POST', f'/project/{pid}/tasks', {'template_id': tid}, token=token, timeout=30)
    task_id = int(task['id']) if isinstance(task, dict) and task.get('id') is not None else None
    if task_id is None:
        raise RuntimeError(f'task launch returned no id: {task!r}')
    print(f'TASK_ID={task_id}')

    terminal = None
    final = None
    for _ in range(90):
        final = request('GET', f'/project/{pid}/tasks/{task_id}', token=token)
        status = str(final.get('status') or '').lower()
        if status in {'success', 'error', 'failed', 'stopped', 'canceled', 'cancelled'}:
            terminal = status
            break
        time.sleep(2)
    if terminal is None:
        raise RuntimeError('Semaphore proof task did not reach terminal state within 180s')

    print(f'TASK_STATUS={terminal}')

    def raw_output():
        value = request('GET', f'/project/{pid}/tasks/{task_id}/raw_output', token=token, timeout=30)
        if isinstance(value, str):
            return value
        return json.dumps(value, separators=(',', ':'))

    output = raw_output()
    if terminal != 'success':
        print(output[-4000:])
        raise RuntimeError(f'proof task terminal status is {terminal}')

    # Semaphore persists task status and task-output rows separately. A task can
    # report success a moment before the final output rows (including our proof
    # marker) are visible through raw_output. Poll only the immutable completed
    # task output for a bounded 30 seconds rather than treating that race as a
    # failed execution proof.
    marker_seen = False
    commit_seen = False
    for attempt in range(16):
        marker_seen = 'LIFEOS_SEMAPHORE_PROOF=PASS' in output
        commit_seen = expected_head in output
        if marker_seen and commit_seen:
            break
        if attempt < 15:
            time.sleep(2)
            output = raw_output()

    if not marker_seen or not commit_seen:
        print(output[-6000:])
        try:
            structured = request('GET', f'/project/{pid}/tasks/{task_id}/output', token=token, timeout=30)
            print('STRUCTURED_OUTPUT_DIAGNOSTIC=' + json.dumps(structured, separators=(',', ':'))[-6000:])
        except Exception as exc:
            print(f'STRUCTURED_OUTPUT_DIAGNOSTIC=ERROR:{type(exc).__name__}')
        if not marker_seen:
            raise RuntimeError('proof PASS marker absent after output persistence window')
        raise RuntimeError('proof output does not contain expected platform commit after persistence window')

    print('OUTPUT_PERSISTENCE=PASS')
    print('SEMAPHORE_TASK_EXECUTION=PASS')
    print('RESULT_PROPAGATION=PASS')
finally:
    if token:
        try:
            request('DELETE', f'/user/tokens/{token}', token=token)
            print('TEMP_API_TOKEN_REVOKED=YES')
        except Exception as exc:
            print(f'TEMP_API_TOKEN_REVOKED=ERROR:{type(exc).__name__}', file=sys.stderr)
PY

HEAD_AFTER=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
INDEX_OWNER_AFTER=$(stat -c '%U:%G' "$PLATFORM/.git/index")
UNITS_AFTER=$(snapshot_units)

[[ "$HEAD_AFTER" == "$HEAD_BEFORE" ]] || { echo 'ERROR: platform HEAD changed during proof'; exit 1; }
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform working tree changed during proof'; exit 1; }
[[ "$INDEX_OWNER_AFTER" == "$INDEX_OWNER_BEFORE" ]] || { echo 'ERROR: git metadata ownership changed'; exit 1; }
[[ "$UNITS_AFTER" == "$UNITS_BEFORE" ]] || {
  echo 'ERROR: custom execution unit state changed during Semaphore proof'
  diff -u <(printf '%s\n' "$UNITS_BEFORE") <(printf '%s\n' "$UNITS_AFTER") || true
  exit 1
}

echo
echo 'RESULT=PASS'
echo 'SEMAPHORE_ALLOWLISTED_ANSIBLE=PASS'
echo 'RESULT_PROPAGATION=PASS'
echo 'PLATFORM_MUTATION=NONE'
echo 'CUSTOM_EXECUTION_PATH_CHANGED=NO'
echo 'ROOT_BROKER_CHANGED=NO'
echo 'NEXT_ACTION=design_shadow_adapter_for_backlog_runner_replacement'
