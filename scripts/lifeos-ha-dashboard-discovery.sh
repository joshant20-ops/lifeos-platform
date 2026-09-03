#!/usr/bin/env bash
set -Eeuo pipefail

printf '%s\n' 'LIFEOS_HA_DASHBOARD_DISCOVERY_VERSION=1' 'MUTATIONS=NONE'

container=${LIFEOS_HA_CONTAINER:-homeassistant}
if ! docker inspect "$container" >/dev/null 2>&1; then
  echo 'RESULT=FAIL'
  echo 'BARRIER=homeassistant_container_not_found'
  exit 1
fi

state=$(docker inspect -f '{{.State.Status}}' "$container")
printf 'HOMEASSISTANT_CONTAINER=%s\nHOMEASSISTANT_STATE=%s\n' "$container" "$state"
[[ "$state" == running ]] || { echo 'RESULT=FAIL'; echo 'BARRIER=homeassistant_not_running'; exit 1; }

# Read only HA's dashboard storage from inside the container. Emit structure and
# entity IDs only; never print credentials, tokens, user records, or arbitrary
# state/config values.
docker exec -i "$container" python3 - <<'PY'
import json
from pathlib import Path

root = Path('/config/.storage')
files = []
if root.is_dir():
    files = sorted(p for p in root.iterdir() if p.is_file() and (
        p.name == 'lovelace' or p.name.startswith('lovelace.') or
        p.name == 'lovelace_dashboards'
    ))

print(f'DASHBOARD_STORAGE_FILES={len(files)}')

seen_entities = set()
views_total = 0
cards_total = 0

def walk(node):
    global cards_total
    if isinstance(node, dict):
        if 'type' in node and isinstance(node.get('type'), str):
            cards_total += 1
        for key, value in node.items():
            if key in {'entity', 'entity_id'} and isinstance(value, str):
                if '.' in value and len(value) < 160:
                    seen_entities.add(value)
            elif key == 'entities' and isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and '.' in item and len(item) < 160:
                        seen_entities.add(item)
                    elif isinstance(item, dict):
                        ent = item.get('entity')
                        if isinstance(ent, str) and '.' in ent and len(ent) < 160:
                            seen_entities.add(ent)
            walk(value)
    elif isinstance(node, list):
        for item in node:
            walk(item)

for path in files:
    try:
        doc = json.loads(path.read_text())
    except Exception as exc:
        print(f'FILE={path.name} PARSE=ERROR TYPE={type(exc).__name__}')
        continue
    data = doc.get('data', doc) if isinstance(doc, dict) else doc
    print(f'FILE={path.name} PARSE=PASS')

    if path.name == 'lovelace_dashboards' and isinstance(data, dict):
        items = data.get('items', [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Metadata only: dashboard title/url/mode are presentation structure.
                print('DASHBOARD title=%s url_path=%s mode=%s' % (
                    str(item.get('title', ''))[:120],
                    str(item.get('url_path', ''))[:120],
                    str(item.get('mode', ''))[:40],
                ))
        continue

    if isinstance(data, dict):
        cfg = data.get('config', data)
    else:
        cfg = data
    if isinstance(cfg, dict):
        views = cfg.get('views', [])
    else:
        views = []
    if isinstance(views, list):
        for idx, view in enumerate(views):
            if not isinstance(view, dict):
                continue
            views_total += 1
            title = str(view.get('title', ''))[:120]
            pathv = str(view.get('path', ''))[:120]
            icon = str(view.get('icon', ''))[:120]
            cards = view.get('cards', [])
            count = len(cards) if isinstance(cards, list) else 0
            print(f'VIEW index={idx} title={title!r} path={pathv!r} icon={icon!r} cards={count}')
            walk(view)

print(f'VIEWS_TOTAL={views_total}')
print(f'CARDS_DISCOVERED={cards_total}')
print(f'ENTITY_REFERENCES={len(seen_entities)}')
for entity in sorted(seen_entities):
    low = entity.lower()
    if any(token in low for token in ('lifeos', 'engineer', 'watchman', 'issue_queue', 'backlog', 'semaphore', 'governor')):
        print(f'LIFEOS_ENTITY={entity}')
PY

printf '%s\n' 'RESULT=PASS' 'NEXT_ACTION=adapt_existing_lifeos_views_to_current_control_plane_entities'
