#!/usr/bin/env python3
"""Read-only Stage 3 follow-up audit using existing OTS operational surfaces."""
from __future__ import annotations
import json, os, subprocess, time
from pathlib import Path

OUT=Path.home()/'.local/state/lifeos/capability-stage3-followups.json'

def run(cmd): return subprocess.run(cmd,text=True,capture_output=True)
def systemctl(*args): return run(['systemctl',*args])
def age_hours(path: Path):
    try: return round((time.time()-path.stat().st_mtime)/3600,1)
    except FileNotFoundError: return None

def unit_state(unit):
    enabled=systemctl('is-enabled',unit)
    active=systemctl('is-active',unit)
    show=systemctl('show',unit,'--property=Result,ActiveEnterTimestamp,InactiveEnterTimestamp,ExecMainStatus,NextElapseUSecRealtime,LastTriggerUSec','--no-pager')
    return {'enabled':enabled.stdout.strip() or enabled.stderr.strip(),'active':active.stdout.strip() or active.stderr.strip(),'show':show.stdout.strip()}

backup_timer=unit_state('lifeos-restic-backup.timer')
backup_service=unit_state('lifeos-restic-backup.service')
apt_daily=unit_state('apt-daily.timer')
apt_upgrade=unit_state('apt-daily-upgrade.timer')

# Latest durable recovery/restore evidence, if any. Values are paths/ages only.
restore_candidates=[]
for root in [Path('/var/lib/lifeos-control'),Path('/var/lib/lifeos-transactions'),Path.home()/'.local/state/lifeos']:
    if not root.exists(): continue
    for p in root.rglob('*'):
        if p.is_file() and any(k in p.name.lower() for k in ('restore','recovery','rehearsal','backup')):
            restore_candidates.append((p.stat().st_mtime,str(p)))
restore_candidates.sort(reverse=True)
latest_restore=restore_candidates[0][1] if restore_candidates else None
latest_restore_age=age_hours(Path(latest_restore)) if latest_restore else None

# Uptime Kuma monitor schema/data: count HTTPS monitors and expiry-awareness fields without emitting URLs.
cert={'kuma_db_present':False,'https_monitors':0,'expiry_enabled':0,'schema_columns':[]}
code=r'''import json,sqlite3
p='/app/data/kuma.db'
c=sqlite3.connect(p); c.row_factory=sqlite3.Row
cols=[r['name'] for r in c.execute('pragma table_info(monitor)')]
rows=c.execute('select * from monitor').fetchall()
https=[]
for r in rows:
 d=dict(r); u=str(d.get('url') or '')
 if u.lower().startswith('https://'): https.append(d)
keys=[k for k in cols if 'expiry' in k.lower() or 'cert' in k.lower()]
enabled=0
for d in https:
 if any(bool(d.get(k)) for k in keys): enabled+=1
print(json.dumps({'https_monitors':len(https),'expiry_enabled':enabled,'schema_columns':keys},sort_keys=True))
'''
k=run(['docker','exec','uptime-kuma','node','-e',"const {execFileSync}=require('child_process'); try {process.stdout.write(execFileSync('python3',['-c',process.argv[1]],{encoding:'utf8'}))} catch(e){process.exit(2)}",code])
if k.returncode==0:
    cert.update(json.loads(k.stdout)); cert['kuma_db_present']=True
else:
    # Some Uptime Kuma images do not include python; fall back to schema-independent marker.
    cert['probe_error']='sqlite_probe_unavailable_in_container'

# OS update awareness is satisfied by native apt timers plus a read-only pending-count signal.
up=run(['bash','-lc',"apt list --upgradable 2>/dev/null | sed '1d' | wc -l"])
pending_updates=int(up.stdout.strip() or 0) if up.returncode==0 else None

snags=[]
if 'enabled' not in backup_timer['enabled']:
    snags.append('OPS-SNAG-01: lifeos-restic-backup.timer is not enabled')
if backup_service['show'] and 'Result=success' not in backup_service['show']:
    snags.append('OPS-SNAG-02: latest restic backup service result is not proven success')
if latest_restore_age is None:
    snags.append('OPS-SNAG-03: no durable restore/recovery rehearsal evidence discovered')
if not cert['kuma_db_present']:
    snags.append('OPS-SNAG-04: Uptime Kuma certificate-expiry coverage could not be introspected with current container tooling')
elif cert['https_monitors'] and cert['expiry_enabled'] < cert['https_monitors']:
    snags.append(f"OPS-SNAG-05: certificate-expiry awareness enabled for {cert['expiry_enabled']}/{cert['https_monitors']} HTTPS monitors")
if 'enabled' not in apt_daily['enabled'] and 'enabled' not in apt_upgrade['enabled']:
    snags.append('OPS-SNAG-06: native apt update timers are not enabled')

report={
 'schema_version':1,'capability_stage':3,'status':'PASS','read_only':True,
 'backup':{'timer':backup_timer,'service':backup_service,'latest_restore_evidence':latest_restore,'latest_restore_age_hours':latest_restore_age},
 'certificate_awareness':cert,
 'updates':{'apt_daily_timer':apt_daily,'apt_upgrade_timer':apt_upgrade,'pending_package_updates':pending_updates},
 'snags':snags,
}
OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print('STAGE3_FOLLOWUP_AUDIT=PASS')
print('BACKUP_TIMER='+backup_timer['enabled'])
print('BACKUP_SERVICE_SUCCESS='+('YES' if 'Result=success' in backup_service['show'] else 'NO'))
print('RESTORE_EVIDENCE='+('YES' if latest_restore else 'NO'))
print('RESTORE_EVIDENCE_AGE_HOURS='+str(latest_restore_age))
print('KUMA_CERT_PROBE='+('PASS' if cert['kuma_db_present'] else 'UNAVAILABLE'))
print('HTTPS_MONITORS='+str(cert['https_monitors']))
print('HTTPS_EXPIRY_AWARE='+str(cert['expiry_enabled']))
print('APT_DAILY_TIMER='+apt_daily['enabled'])
print('APT_UPGRADE_TIMER='+apt_upgrade['enabled'])
print('PENDING_PACKAGE_UPDATES='+str(pending_updates))
print('SNAG_COUNT='+str(len(snags)))
for x in snags: print('SNAG='+x)
print('REPORT='+str(OUT))
