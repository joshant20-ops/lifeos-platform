#!/usr/bin/env python3
"""Package the accepted DEV implementation for a versioned Live release.

Only enumerated environment identity, loader, and development-marker substitutions
are permitted. Reverse normalization must reproduce the DEV source byte for byte.
"""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

PACKAGER_VERSION = 1
REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO / 'homeassistant' / 'www' / 'house-status-dev'

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def replace_exact(text: str, old: str, new: str, count: int) -> str:
    got = text.count(old)
    if got != count:
        raise ValueError(f'packager input drift: expected {count} occurrences of {old!r}, found {got}')
    return text.replace(old, new)

def normalize_app(dev: str, release: str, doorbell_hash: str) -> str:
    n = int(release[1:])
    out = dev
    pairs = [
        ("try{ await import('/local/house-status-dev/lifeos-house-status-doorbell.js?dev='+Date.now()); } catch(error) { console.warn('House Status Doorbell module load failed',error); }",
         f"try{{ await import('/local/house-status/lifeos-house-status-doorbell-{release}.js?v={doorbell_hash[:12]}'); }} catch(error) {{ console.warn('House Status Doorbell module load failed',error); }}", 1),
        ('lifeos-house-status-dev-editor-v2', 'lifeos-house-status-editor', 3),
        ('LifeOS House Status Development v2', f'LifeOS House Status {release}', 1),
        ('lifeos-house-status-dev', f'lifeos-house-status-{release}', 3),
        ('LifeOSHouseStatusDevModules', 'LifeOSHouseStatusModules', 3),
        ('LifeOSHouseStatusModules?.doorbell', f'LifeOSHouseStatusModules?.doorbellV{n}', 3),
        ('House Status DEV', 'House Status', 2),
        ('Doorbell DEV', f'Doorbell {release}', 1),
        ('House DEV', 'House v1', 1),
        ('Energy DEV', f'Energy {release}', 1),
        ('border:2px solid #b568ff;', '', 1),
        ('--blue:#a55cff', '--blue:#168cff', 1),
    ]
    for old, new, count in pairs:
        out = replace_exact(out, old, new, count)
    return out

def normalize_doorbell(dev: str, release: str) -> str:
    n = int(release[1:])
    out=replace_exact(dev, 'LifeOSHouseStatusDevModules', 'LifeOSHouseStatusModules', 3)
    out=replace_exact(out, 'window.LifeOSHouseStatusModules.doorbell=', f'window.LifeOSHouseStatusModules.doorbellV{n}=', 1)
    return replace_exact(out, 'Doorbell DEV', f'Doorbell {release}', 1)

def denormalize_doorbell(live: str, release: str) -> str:
    n = int(release[1:])
    out=replace_exact(live, f'Doorbell {release}', 'Doorbell DEV', 1)
    out=replace_exact(out, f'window.LifeOSHouseStatusModules.doorbellV{n}=', 'window.LifeOSHouseStatusModules.doorbell=', 1)
    return replace_exact(out, 'LifeOSHouseStatusModules', 'LifeOSHouseStatusDevModules', 3)

def denormalize_app(live: str, release: str, doorbell_hash: str) -> str:
    n = int(release[1:])
    pairs = [
        (f"try{{ await import('/local/house-status/lifeos-house-status-doorbell-{release}.js?v={doorbell_hash[:12]}'); }} catch(error) {{ console.warn('House Status Doorbell module load failed',error); }}",
         "try{ await import('/local/house-status-dev/lifeos-house-status-doorbell.js?dev='+Date.now()); } catch(error) { console.warn('House Status Doorbell module load failed',error); }", 1),
        ('lifeos-house-status-editor', 'lifeos-house-status-dev-editor-v2', 3),
        (f'LifeOS House Status {release}', 'LifeOS House Status Development v2', 1),
        (f'lifeos-house-status-{release}', 'lifeos-house-status-dev', 3),
        (f'LifeOSHouseStatusModules?.doorbellV{n}', 'LifeOSHouseStatusDevModules?.doorbell', 3),
        (f'Doorbell {release}', 'Doorbell DEV', 1),
        ('House v1', 'House DEV', 1),
        (f'Energy {release}', 'Energy DEV', 1),
        ('--blue:#168cff', '--blue:#a55cff', 1),
    ]
    out = live
    for old, new, count in pairs:
        out = replace_exact(out, old, new, count)
    out = replace_exact(out, '<div class="title">⌂ House Status <span', '<div class="title">⌂ House Status DEV <span', 1)
    out = replace_exact(out, "console.warn('House Status source-backed energy history load failed',e)", "console.warn('House Status DEV source-backed energy history load failed',e)", 1)
    out = replace_exact(out, ':host{display:block;--bg:', ':host{display:block;border:2px solid #b568ff;--bg:', 1)
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--release', required=True, help='Versioned release identity, for example v30')
    ap.add_argument('--source-dir', type=pathlib.Path, default=DEFAULT_SOURCE)
    ap.add_argument('--out-dir', type=pathlib.Path)
    ap.add_argument('--source-commit')
    ap.add_argument('--packager-commit')
    ap.add_argument('--check', action='store_true', help='build in memory and verify the reversible transform')
    args = ap.parse_args()
    if not re.fullmatch(r'v(?:3[0-9]|[4-9][0-9]|[1-9][0-9]{2,})', args.release):
        raise SystemExit('release must be v30 or later; v28 is the pinned baseline and v29 is inert')
    app_path = args.source_dir / 'lifeos-house-status-dev.js'
    bell_path = args.source_dir / 'lifeos-house-status-doorbell.js'
    app = app_path.read_text()
    bell = bell_path.read_text()
    # A release uses production namespaces and versioned sibling module URLs.
    n = int(args.release[1:])
    live_bell = normalize_doorbell(bell, args.release)
    if denormalize_doorbell(live_bell, args.release) != bell:
        raise SystemExit('HOUSE_STATUS_DOORBELL_REVERSIBILITY=FAIL')
    bell_hash = sha256(live_bell.encode())
    live_app = normalize_app(app, args.release, bell_hash)
    if denormalize_app(live_app, args.release, bell_hash) != app:
        raise SystemExit('HOUSE_STATUS_RELEASE_REVERSIBILITY=FAIL')
    if not re.search(r"this\.period\(\)==='year'\?'':powerdownWindows\.map", live_app):
        raise SystemExit('HOUSE_STATUS_RELEASE_YEAR_POWER_DOWN=FAIL')
    if 'periodWindow(){return [this.periodStart(),this.periodEnd()];}' not in live_app:
        raise SystemExit('HOUSE_STATUS_RELEASE_ROLLING_PERIODS=FAIL')
    if any(x in live_app + live_bell for x in ('/local/house-status-dev/', 'lifeos-house-status-dev', 'LifeOSHouseStatusDevModules', 'DEV source-backed')):
        raise SystemExit('HOUSE_STATUS_RELEASE_ENVIRONMENT_ISOLATION=FAIL')
    app_bytes = live_app.encode()
    source_identity = args.source_commit or subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    packager_identity = args.packager_commit or subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    result = {
        'packager_version': PACKAGER_VERSION,
        'release': args.release,
        'source_commit': source_identity,
        'packager_commit': packager_identity,
        'dev_app_sha256': sha256(app.encode()),
        'dev_doorbell_sha256': sha256(bell.encode()),
        'live_app_sha256': sha256(app_bytes),
        'live_doorbell_sha256': bell_hash,
    }
    if args.out_dir:
        args.out_dir.mkdir(parents=True,exist_ok=True)
        (args.out_dir / f'lifeos-house-status-{args.release}.js').write_bytes(app_bytes)
        (args.out_dir / f'lifeos-house-status-doorbell-{args.release}.js').write_bytes(live_bell.encode())
        (args.out_dir / 'release-attestation.json').write_text(json.dumps(result,indent=2)+'\n')
    print('HOUSE_STATUS_RELEASE_REVERSIBILITY=PASS')
    print('HOUSE_STATUS_DOORBELL_REVERSIBILITY=PASS')
    print('HOUSE_STATUS_RELEASE_ENVIRONMENT_ISOLATION=PASS')
    print('HOUSE_STATUS_RELEASE_ROLLING_WEEK_MONTH_YEAR=PASS')
    print('YEAR_POWER_DOWN_RENDERING=HIDDEN')
    print('HOUSE_STATUS_RELEASE_CANDIDATE='+args.release+':'+result['live_app_sha256'])
    print('HOUSE_STATUS_RELEASE_ATTESTATION='+json.dumps(result,sort_keys=True))
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f'HOUSE_STATUS_RELEASE_BUILD=FAIL:{exc}', file=sys.stderr)
        raise SystemExit(1)
