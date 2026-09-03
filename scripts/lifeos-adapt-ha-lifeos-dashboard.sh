#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER=${LIFEOS_HA_CONTAINER:-homeassistant}
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/mnt/docker-data/automation/backups/ha-lifeos-dashboard-$STAMP"
TARGET_KEY=lovelace.lifeos_control
TARGET_ID=lifeos_control
TARGET_PATH=lifeos-control

rollback() {
  rc=$?
  if (( rc == 0 )); then return; fi
  echo 'ROLLBACK=attempting'
  if [[ -d "$BACKUP" ]]; then
    for name in lovelace_dashboards lovelace.lifeos_control; do
      if [[ -f "$BACKUP/$name.before" ]]; then
        docker cp "$BACKUP/$name.before" "$CONTAINER:/config/.storage/$name" || true
      elif [[ -f "$BACKUP/$name.absent" ]]; then
        docker exec "$CONTAINER" rm -f "/config/.storage/$name" || true
      fi
    done
    docker restart "$CONTAINER" >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap rollback ERR

[[ $EUID -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo 'ERROR=homeassistant_container_missing'; exit 1; }
[[ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER")" == running ]] || { echo 'ERROR=homeassistant_not_running'; exit 1; }

mkdir -p "$BACKUP"
for name in lovelace_dashboards lovelace.lifeos_control; do
  if docker exec "$CONTAINER" test -f "/config/.storage/$name"; then
    docker cp "$CONTAINER:/config/.storage/$name" "$BACKUP/$name.before"
  else
    : > "$BACKUP/$name.absent"
  fi
done

docker exec -i "$CONTAINER" python3 - <<'PY'
import copy, json, os, tempfile
from pathlib import Path

root = Path('/config/.storage')
target = root / 'lovelace.lifeos_control'
dashboards_path = root / 'lovelace_dashboards'

sources = sorted(root.glob('lovelace.backup_lifeos_chat_*'), key=lambda p: p.name, reverse=True)
if not sources:
    raise SystemExit('preserved_lifeos_dashboard_not_found')
source = sources[0]
source_doc = json.loads(source.read_text())
source_data = source_doc.get('data', source_doc)
config = copy.deepcopy(source_data.get('config', source_data))
views = config.get('views') if isinstance(config, dict) else None
if not isinstance(views, list) or len(views) < 6:
    raise SystemExit('preserved_lifeos_dashboard_shape_invalid')

control_entity = 'sensor.lifeos_control_state'

def markdown(title, body):
    return {'type': 'markdown', 'title': title, 'content': body}

def entities(title, items):
    return {'type': 'entities', 'title': title, 'show_header_toggle': False,
            'entities': [{'entity': control_entity, 'name': name, 'type': 'attribute', 'attribute': attr}
                         if attr else {'entity': control_entity, 'name': name}
                         for name, attr in items]}

# LifeOS Control is now a concise control-plane dashboard. Preserve the old six-view
# navigation, but retain legacy cards only on Network where they still provide unique
# presentation not replaced by the current control-state feed.
for view in views:
    title = str(view.get('title') or '')
    legacy = view.get('cards') if isinstance(view.get('cards'), list) else []
    if title == 'Overview':
        view['cards'] = [
            markdown('LifeOS live control state',
                "## {{ states('sensor.lifeos_control_state') }}\n"
                "**Roadmap:** {{ state_attr('sensor.lifeos_control_state','roadmap_stage') }}/{{ state_attr('sensor.lifeos_control_state','roadmap_stages') }} — {{ state_attr('sensor.lifeos_control_state','roadmap_progress_percent') }}%  \n"
                "**Current:** #{{ state_attr('sensor.lifeos_control_state','current_issue') or '—' }} {{ state_attr('sensor.lifeos_control_state','current_title') or '' }}  \n"
                "**Job:** {{ state_attr('sensor.lifeos_control_state','current_job') or 'none' }} · {{ state_attr('sensor.lifeos_control_state','current_stage') or 'idle' }}  \n"
                "**Blocker:** {{ state_attr('sensor.lifeos_control_state','blocker') or 'none' }}  \n"
                "**Next:** {{ state_attr('sensor.lifeos_control_state','next_action') or 'none' }}"),
            entities('Queue / progress', [('LifeOS state', None), ('Open issues','open_issue_count'), ('Eligible','eligible_count'), ('Blocked','blocked_count'), ('Last completed job','last_completed_job')]),
        ]
    elif title == 'Execution Safety':
        view['cards'] = [
            markdown('Execution safety',
                "## {{ states('sensor.lifeos_control_state') }}\n"
                "**GitHub runner:** {{ state_attr('sensor.lifeos_control_state','github_runner')['state'] if state_attr('sensor.lifeos_control_state','github_runner') else 'unknown' }}  \n"
                "**Semaphore:** {{ state_attr('sensor.lifeos_control_state','semaphore')['state'] if state_attr('sensor.lifeos_control_state','semaphore') else 'unknown' }}  \n"
                "**Blocked jobs:** {{ state_attr('sensor.lifeos_control_state','blocked_count') or 0 }}  \n"
                "**Blocker:** {{ state_attr('sensor.lifeos_control_state','blocker') or 'none' }}")
        ]
    elif title == 'Hosts':
        view['cards'] = [
            markdown('Automation hosts',
                "**Pi runner:** {{ state_attr('sensor.lifeos_control_state','github_runner')['state'] if state_attr('sensor.lifeos_control_state','github_runner') else 'unknown' }}  \n"
                "**Semaphore:** {{ state_attr('sensor.lifeos_control_state','semaphore')['state'] if state_attr('sensor.lifeos_control_state','semaphore') else 'unknown' }}  \n"
                "**Latest automation:** {{ state_attr('sensor.lifeos_control_state','automation')['state'] if state_attr('sensor.lifeos_control_state','automation') else 'unknown' }}")
        ]
    elif title == 'Network':
        view['cards'] = legacy
    elif title == 'AI Workflow':
        view['cards'] = [
            markdown('Current AI workflow',
                "**Issue:** #{{ state_attr('sensor.lifeos_control_state','current_issue') or '—' }} {{ state_attr('sensor.lifeos_control_state','current_title') or '' }}  \n"
                "**Job:** {{ state_attr('sensor.lifeos_control_state','current_job') or 'none' }}  \n"
                "**Stage:** {{ state_attr('sensor.lifeos_control_state','current_stage') or 'idle' }}  \n"
                "**Detail:** {{ state_attr('sensor.lifeos_control_state','stage_detail') or '—' }}  \n"
                "**Next:** {{ state_attr('sensor.lifeos_control_state','next_action') or '—' }}")
        ]
    elif title == 'Deep Debug':
        view['cards'] = [
            markdown('Current blocker / debug',
                "**State:** {{ states('sensor.lifeos_control_state') }}  \n"
                "**Blocker:** {{ state_attr('sensor.lifeos_control_state','blocker') or 'none' }}  \n"
                "**Stalled for:** {{ state_attr('sensor.lifeos_control_state','stalled_for_seconds') or 0 }} seconds  \n"
                "**Last progress epoch:** {{ state_attr('sensor.lifeos_control_state','last_progress_at') or 'unknown' }}  \n"
                "**Last terminal:** {{ state_attr('sensor.lifeos_control_state','last_completed_job') or 'none' }} / {{ state_attr('sensor.lifeos_control_state','last_completed_status') or '—' }}")
        ]

out = copy.deepcopy(source_doc)
out['key'] = 'lovelace.lifeos_control'
if 'data' in out and isinstance(out['data'], dict):
    out['data']['config'] = config
else:
    out['data'] = {'config': config}

def atomic_write(path, obj):
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(obj, fh, separators=(',', ':'))
        os.replace(tmp, path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

atomic_write(target, out)
registry = json.loads(dashboards_path.read_text()) if dashboards_path.exists() else {'version':1,'minor_version':1,'key':'lovelace_dashboards','data':{'items':[]}}
data = registry.setdefault('data', {})
items = data.setdefault('items', [])
if not isinstance(items, list): raise SystemExit('lovelace_dashboard_registry_invalid')
item = next((x for x in items if isinstance(x, dict) and (x.get('id') == 'lifeos_control' or x.get('url_path') == 'lifeos-control')), None)
if item is None:
    item = {'id':'lifeos_control','show_in_sidebar':True,'icon':'mdi:state-machine','title':'LifeOS Control','require_admin':False,'mode':'storage','url_path':'lifeos-control'}
    items.append(item)
else:
    item.update({'id':'lifeos_control','show_in_sidebar':True,'icon':'mdi:state-machine','title':'LifeOS Control','require_admin':False,'mode':'storage','url_path':'lifeos-control'})
atomic_write(dashboards_path, registry)
print('SOURCE_DASHBOARD=' + source.name)
print('TARGET_DASHBOARD=lovelace.lifeos_control')
print('VIEWS=' + str(len(views)))
print('VIEW_TITLES=' + ','.join(str(v.get('title') or '') for v in views))
print('LIFEOS_CONTROL_SIMPLIFIED=YES')
PY

docker restart "$CONTAINER" >/dev/null
for _ in $(seq 1 60); do
  state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
  [[ "$state" == running ]] || { sleep 2; continue; }
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8123/ 2>/dev/null || true)"
  if [[ "$code" =~ ^(200|301|302|401)$ ]]; then break; fi
  sleep 2
done
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8123/ 2>/dev/null || true)"
[[ "$code" =~ ^(200|301|302|401)$ ]] || { echo "ERROR=homeassistant_http_$code"; false; }

docker exec "$CONTAINER" python3 - <<'PY'
import json
from pathlib import Path
root=Path('/config/.storage')
doc=json.loads((root/'lovelace.lifeos_control').read_text())
reg=json.loads((root/'lovelace_dashboards').read_text())
config=doc.get('data',{}).get('config',{})
views=config.get('views',[])
assert [v.get('title') for v in views[:6]] == ['Overview','Execution Safety','Hosts','Network','AI Workflow','Deep Debug']
items=reg.get('data',{}).get('items',[])
assert any(x.get('id')=='lifeos_control' and x.get('url_path')=='lifeos-control' for x in items if isinstance(x,dict))
text=json.dumps(config)
assert 'sensor.lifeos_control_state' in text
assert len(next(v for v in views if v.get('title')=='Overview').get('cards',[])) == 2
assert len(next(v for v in views if v.get('title')=='Execution Safety').get('cards',[])) == 1
assert len(next(v for v in views if v.get('title')=='Hosts').get('cards',[])) == 1
assert len(next(v for v in views if v.get('title')=='AI Workflow').get('cards',[])) == 1
assert len(next(v for v in views if v.get('title')=='Deep Debug').get('cards',[])) == 1
print('DASHBOARD_VALIDATION=PASS')
print('CONTROL_ENTITY_REFERENCED=YES')
print('LIFEOS_CONTROL_BASE_CARDS=11')
PY

echo 'RESULT=PASS'
echo 'LIFEOS_CONTROL_DASHBOARD_ADAPTED=YES'
echo 'LIFEOS_CONTROL_SIMPLIFIED=YES'
echo 'HOME_ASSISTANT_RESTART=PASS'
echo 'DASHBOARD_PATH=/lifeos-control/overview'
echo "BACKUP=$BACKUP"
echo 'ROLLBACK=restore lovelace_dashboards and lovelace.lifeos_control backups then restart Home Assistant'
