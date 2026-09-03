#!/usr/bin/env bash
set -Eeuo pipefail

printf '%s\n' 'LIFEOS_HA_DASHBOARD_DISCOVERY_VERSION=2' 'MUTATIONS=NONE'

container=${LIFEOS_HA_CONTAINER:-homeassistant}
if ! docker inspect "$container" >/dev/null 2>&1; then
  echo 'RESULT=FAIL'
  echo 'BARRIER=homeassistant_container_not_found'
  exit 1
fi

state=$(docker inspect -f '{{.State.Status}}' "$container")
printf 'HOMEASSISTANT_CONTAINER=%s\nHOMEASSISTANT_STATE=%s\n' "$container" "$state"
[[ "$state" == running ]] || { echo 'RESULT=FAIL'; echo 'BARRIER=homeassistant_not_running'; exit 1; }

docker exec -i "$container" python3 - <<'PY'
import json
from pathlib import Path

root = Path('/config/.storage')
if not root.is_dir():
    print('DASHBOARD_STORAGE=missing')
    raise SystemExit(1)

# Keep only active dashboards and the known preserved LifeOS dashboard. Skip the
# large set of historical .bak/pre_* files so the migration map stays useful.
files = []
for p in sorted(root.iterdir()):
    if not p.is_file():
        continue
    n = p.name
    if n in {'lovelace', 'lovelace_dashboards', 'lovelace.dashboard_homelab'}:
        files.append(p)
    elif n.startswith('lovelace.backup_lifeos_chat_'):
        files.append(p)

print(f'TARGET_STORAGE_FILES={len(files)}')

entity_refs = {}
card_types = {}

def record_entity(file_name, entity):
    if isinstance(entity, str) and '.' in entity and len(entity) < 160:
        entity_refs.setdefault(file_name, set()).add(entity)

def walk(file_name, node):
    if isinstance(node, dict):
        typ = node.get('type')
        if isinstance(typ, str):
            card_types.setdefault(file_name, set()).add(typ)
        for key, value in node.items():
            if key in {'entity', 'entity_id'}:
                record_entity(file_name, value)
            elif key == 'entities' and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        record_entity(file_name, item)
                    elif isinstance(item, dict):
                        record_entity(file_name, item.get('entity'))
            walk(file_name, value)
    elif isinstance(node, list):
        for item in node:
            walk(file_name, item)

for path in files:
    try:
        doc = json.loads(path.read_text())
    except Exception as exc:
        print(f'FILE={path.name} PARSE=ERROR TYPE={type(exc).__name__}')
        continue
    data = doc.get('data', doc) if isinstance(doc, dict) else doc
    print(f'FILE={path.name} PARSE=PASS')

    if path.name == 'lovelace_dashboards' and isinstance(data, dict):
        for item in data.get('items', []) if isinstance(data.get('items', []), list) else []:
            if isinstance(item, dict):
                print('DASHBOARD title=%r url_path=%r mode=%r' % (
                    str(item.get('title', ''))[:120],
                    str(item.get('url_path', ''))[:120],
                    str(item.get('mode', ''))[:40],
                ))
        continue

    cfg = data.get('config', data) if isinstance(data, dict) else data
    views = cfg.get('views', []) if isinstance(cfg, dict) else []
    if not isinstance(views, list):
        views = []
    for idx, view in enumerate(views):
        if not isinstance(view, dict):
            continue
        cards = view.get('cards', [])
        print('VIEW file=%s index=%s title=%r path=%r icon=%r cards=%s' % (
            path.name,
            idx,
            str(view.get('title', ''))[:120],
            str(view.get('path', ''))[:120],
            str(view.get('icon', ''))[:120],
            len(cards) if isinstance(cards, list) else 0,
        ))
        walk(path.name, view)

for file_name in sorted(entity_refs):
    for entity in sorted(entity_refs[file_name]):
        low = entity.lower()
        if any(token in low for token in (
            'lifeos', 'engineer', 'watchman', 'issue_queue', 'backlog',
            'semaphore', 'governor', 'github', 'runner'
        )):
            print(f'LIFEOS_ENTITY file={file_name} entity={entity}')

for file_name in sorted(card_types):
    print('CARD_TYPES file=%s values=%s' % (
        file_name,
        ','.join(sorted(card_types[file_name]))[:1200]
    ))
PY

printf '%s\n' 'RESULT=PASS' 'NEXT_ACTION=map_preserved_lifeos_views_to_current_control_plane_entities'
