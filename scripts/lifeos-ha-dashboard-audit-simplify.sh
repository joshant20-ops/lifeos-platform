#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER=${LIFEOS_HA_CONTAINER:-homeassistant}
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/mnt/docker-data/automation/backups/ha-dashboard-simplify-$STAMP"

rollback() {
  rc=$?
  if (( rc == 0 )); then return; fi
  echo 'DASHBOARD_SIMPLIFY_ROLLBACK=attempting'
  if [[ -d "$BACKUP" ]]; then
    for f in "$BACKUP"/*.before; do
      [[ -e "$f" ]] || continue
      name="$(basename "$f" .before)"
      docker cp "$f" "$CONTAINER:/config/.storage/$name" || true
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

# Discover active storage dashboards and back them up before any simplification.
mapfile -t ACTIVE < <(docker exec -i "$CONTAINER" python3 - <<'PY'
import json
from pathlib import Path
root=Path('/config/.storage')
reg=root/'lovelace_dashboards'
seen=[]
if reg.exists():
    data=json.loads(reg.read_text()).get('data',{})
    for item in data.get('items',[]):
        if not isinstance(item,dict) or item.get('mode')!='storage':
            continue
        did=item.get('id')
        if did:
            key='lovelace.'+str(did)
            if (root/key).exists() and key not in seen:
                seen.append(key)
# Include default storage dashboard when present.
for key in ('lovelace','lovelace.dashboard'):
    if (root/key).exists() and key not in seen:
        seen.append(key)
for key in seen:
    print(key)
PY
)

[[ ${#ACTIVE[@]} -gt 0 ]] || { echo 'ERROR=no_active_storage_dashboards'; exit 1; }
for name in "${ACTIVE[@]}"; do
  docker cp "$CONTAINER:/config/.storage/$name" "$BACKUP/$name.before"
done

echo "ACTIVE_DASHBOARDS=${#ACTIVE[@]}"
printf 'ACTIVE_DASHBOARD=%s\n' "${ACTIVE[@]}"

# Audit + apply only mechanically safe simplifications.
docker exec -i "$CONTAINER" python3 - <<'PY'
import hashlib, json, os, re, tempfile
from pathlib import Path

root=Path('/config/.storage')
registry_path=root/'lovelace_dashboards'
registry=json.loads(registry_path.read_text()) if registry_path.exists() else {'data':{'items':[]}}
items=[x for x in registry.get('data',{}).get('items',[]) if isinstance(x,dict)]
active=[]
meta={}
for item in items:
    if item.get('mode')!='storage' or not item.get('id'):
        continue
    key='lovelace.'+str(item['id'])
    if (root/key).exists():
        active.append(key)
        meta[key]=item
for key in ('lovelace','lovelace.dashboard'):
    if (root/key).exists() and key not in active:
        active.append(key); meta.setdefault(key,{})

entity_registry=root/'core.entity_registry'
registered=set()
if entity_registry.exists():
    try:
        registered={str(e.get('entity_id')) for e in json.loads(entity_registry.read_text()).get('data',{}).get('entities',[]) if isinstance(e,dict) and e.get('entity_id')}
    except Exception:
        pass

entity_rx=re.compile(r'\b(?:sensor|binary_sensor|switch|light|button|input_boolean|input_button|input_select|input_number|input_text|input_datetime|automation|script|person|device_tracker|climate|cover|fan|media_player|camera|lock|vacuum|weather|scene|sun)\.[a-zA-Z0-9_]+\b')
retired_rx=re.compile(r'lifeos[-_](?:engineer[-_]?worker|engineer[-_]?dispatcher)|engineer_job_queue|engineer_jobs_pending',re.I)
expected_lifeos=['Overview','Execution Safety','Hosts','Network','AI Workflow','Deep Debug']
summary={'dashboards':0,'views':0,'cards_before':0,'cards_after':0,'duplicates_removed':0,'retired_cards_removed':0,'missing_entity_refs':set(),'empty_views':[],'lifeos_role_errors':[]}

def config_of(doc):
    d=doc.get('data',doc)
    if isinstance(d,dict) and isinstance(d.get('config'),dict): return d['config']
    return d if isinstance(d,dict) else {}

def atomic(path,obj):
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.audit.',dir=str(path.parent),text=True)
    try:
        with os.fdopen(fd,'w') as f: json.dump(obj,f,separators=(',',':'))
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

for key in active:
    path=root/key
    doc=json.loads(path.read_text())
    cfg=config_of(doc)
    views=cfg.get('views',[]) if isinstance(cfg,dict) else []
    if not isinstance(views,list):
        print(f'DASHBOARD={key} STATUS=INVALID_VIEWS')
        continue
    summary['dashboards']+=1
    title=(meta.get(key) or {}).get('title') or key
    print(f'== DASHBOARD {title} ({key}) ==')
    changed=False
    for vi,view in enumerate(views):
        if not isinstance(view,dict): continue
        summary['views']+=1
        vtitle=str(view.get('title') or view.get('path') or f'view-{vi+1}')
        cards=view.get('cards',[])
        if not isinstance(cards,list): cards=[]
        summary['cards_before']+=len(cards)
        if not cards: summary['empty_views'].append(f'{key}:{vtitle}')
        seen=set(); new=[]; dup=0; retired=0
        for card in cards:
            canonical=json.dumps(card,sort_keys=True,separators=(',',':'))
            digest=hashlib.sha256(canonical.encode()).hexdigest()
            if digest in seen:
                dup+=1; summary['duplicates_removed']+=1; changed=True; continue
            seen.add(digest)
            if key=='lovelace.lifeos_control' and retired_rx.search(canonical):
                retired+=1; summary['retired_cards_removed']+=1; changed=True; continue
            new.append(card)
            for ent in entity_rx.findall(canonical):
                if registered and ent not in registered:
                    summary['missing_entity_refs'].add(f'{key}:{vtitle}:{ent}')
        if dup or retired:
            view['cards']=new
        summary['cards_after']+=len(new)
        print(f'VIEW={vtitle} CARDS={len(cards)} DUPLICATES_REMOVED={dup} RETIRED_REMOVED={retired}')

    if key=='lovelace.lifeos_control':
        titles=[str(v.get('title') or '') for v in views if isinstance(v,dict)]
        if titles[:6] != expected_lifeos:
            summary['lifeos_role_errors'].append('view_order_or_titles')
        required={
          'Overview':['sensor.lifeos_control_state','sensor.tower_status'],
          'Hosts':['sensor.tower_status','switch.tower_power','binary_sensor.tower_accessible'],
          'AI Workflow':['sensor.lifeos_control_state'],
          'Deep Debug':['sensor.lifeos_control_state'],
        }
        bytitle={str(v.get('title') or ''):json.dumps(v) for v in views if isinstance(v,dict)}
        for vtitle,ents in required.items():
            blob=bytitle.get(vtitle,'')
            for ent in ents:
                if ent not in blob: summary['lifeos_role_errors'].append(f'{vtitle}_missing_{ent}')
    if changed:
        atomic(path,doc)

print('=== AUDIT SUMMARY ===')
print('DASHBOARDS_AUDITED='+str(summary['dashboards']))
print('VIEWS_AUDITED='+str(summary['views']))
print('CARDS_BEFORE='+str(summary['cards_before']))
print('CARDS_AFTER='+str(summary['cards_after']))
print('EXACT_DUPLICATES_REMOVED='+str(summary['duplicates_removed']))
print('RETIRED_LIFEOS_CARDS_REMOVED='+str(summary['retired_cards_removed']))
print('EMPTY_VIEWS='+str(len(summary['empty_views'])))
for x in summary['empty_views']: print('EMPTY_VIEW='+x)
print('ENTITY_REFS_REQUIRING_VALIDATION='+str(len(summary['missing_entity_refs'])))
for x in sorted(summary['missing_entity_refs']): print('ENTITY_REF_REVIEW='+x)
print('LIFEOS_ROLE_ERRORS='+str(len(summary['lifeos_role_errors'])))
for x in summary['lifeos_role_errors']: print('LIFEOS_ROLE_ERROR='+x)
if summary['lifeos_role_errors']:
    raise SystemExit('lifeos_page_role_validation_failed')
print('DASHBOARD_AUDIT=PASS')
print('SIMPLIFICATION_POLICY=EXACT_DUPLICATES_AND_KNOWN_RETIRED_LIFEOS_ONLY')
PY

docker restart "$CONTAINER" >/dev/null
for _ in $(seq 1 60); do
  [[ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)" == running ]] || { sleep 2; continue; }
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8123/ 2>/dev/null || true)"
  [[ "$code" =~ ^(200|301|302|401)$ ]] && break
  sleep 2
done
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8123/ 2>/dev/null || true)"
[[ "$code" =~ ^(200|301|302|401)$ ]] || { echo "ERROR=homeassistant_http_$code"; false; }

echo 'RESULT=PASS'
echo 'HA_ALL_ACTIVE_DASHBOARDS_AUDITED=YES'
echo 'HA_SAFE_SIMPLIFICATION_APPLIED=YES'
echo "BACKUP=$BACKUP"
echo 'ROLLBACK=restore backed-up active Lovelace storage files then restart Home Assistant'
