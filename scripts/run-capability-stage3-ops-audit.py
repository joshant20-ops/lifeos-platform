#!/usr/bin/env python3
"""Capability Stage 3 OTS production-operations audit.
Compact PASS output; detailed diagnostics on first blocker. Read-only.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
POLICY=REPO/'governor/capability-roadmap/stage3-production-operations.json'
REPORT=Path.home()/'.local/state/lifeos/capability-stage3-ops-report.json'

def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def fail(gate,detail=''):
    print(f'CAPABILITY_STAGE3=FAIL gate={gate}')
    if detail: print(detail)
    print('===== DIAGNOSTICS =====')
    for label,cmd in [
        ('git',['git','status','--short','--branch']),
        ('containers',['docker','ps','-a','--format','{{.Names}}\t{{.Status}}']),
        ('failed-systemd',['systemctl','--failed','--no-legend']),
        ('disk',['df','-h','/','/mnt/docker-data']),
    ]:
        r=cp(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
    raise SystemExit(1)
def gate(name,condition,detail=''):
    if not condition: fail(name,detail)
    print(f'PASS: {name}')

try: policy=json.loads(POLICY.read_text())
except Exception as e: fail('policy',repr(e))
gate('policy',policy.get('capability_stage')==3 and 'required_capabilities' in policy)

# Canonical repository must be clean and synchronized.
r=cp(['git','status','--porcelain','--untracked-files=all']); gate('repository-clean',r.returncode==0 and not r.stdout.strip(),r.stdout.strip())
h=cp(['git','rev-parse','HEAD']); o=cp(['git','rev-parse','origin/main']); gate('repository-sync',h.returncode==0 and o.returncode==0 and h.stdout.strip()==o.stdout.strip(),f'HEAD={h.stdout.strip()} origin/main={o.stdout.strip()}')

# Docker is an OTS runtime; reject unhealthy/exited production containers.
r=cp(['docker','ps','-a','--format','{{.Names}}|{{.Status}}'])
gate('docker-query',r.returncode==0,(r.stdout+r.stderr).strip())
containers=[]; bad=[]
for line in r.stdout.splitlines():
    if '|' not in line: continue
    name,status=line.split('|',1); containers.append({'name':name,'status':status})
    s=status.lower()
    if 'exited' in s or 'dead' in s or 'unhealthy' in s: bad.append(f'{name}:{status}')
gate('container-health',not bad,'; '.join(bad))

names={x['name'] for x in containers}
required_runtime={'homeassistant','uptime-kuma','mosquitto','vaultwarden'}
missing=sorted(required_runtime-names)
gate('core-ots-runtime',not missing,'missing='+','.join(missing))

# Orchestration OTS runtime and control-plane units.
gate('semaphore-runtime',any('semaphore' in n for n in names),'no Semaphore container found')
runner=cp(['systemctl','list-units','--type=service','--state=running','--no-legend'])
gate('github-runner',runner.returncode==0 and 'actions.runner.' in runner.stdout,'self-hosted GitHub Actions runner not running')

# systemd should not have failed units. Existing transient ignored units must be explicitly fixed/waived, not hidden.
r=cp(['systemctl','--failed','--no-legend','--plain'])
failed=[x for x in r.stdout.splitlines() if x.strip()]
gate('systemd-health',r.returncode==0 and not failed,'\n'.join(failed))

# Storage pressure: use OTS/Linux filesystem truth, not a bespoke database.
def usage(path):
    try:
        u=shutil.disk_usage(path); return round(u.used/u.total*100,1)
    except Exception: return None
root_pct=usage('/')
docker_pct=usage('/mnt/docker-data') if Path('/mnt/docker-data').exists() else None
crit=policy.get('disk_critical_percent',90)
gate('root-storage',root_pct is not None and root_pct < crit,f'root_usage={root_pct}')
if docker_pct is not None: gate('docker-storage',docker_pct < crit,f'docker_usage={docker_pct}')
else: print('PASS: docker-storage path=absent')

# Backup/recovery evidence: require an existing backup surface, but do not invent a new backup engine.
backup_candidates=[Path('/mnt/docker-data/automation/backups'),Path('/var/lib/lifeos-transactions'),Path('/mnt/docker-data/backups')]
existing=[str(p) for p in backup_candidates if p.exists()]
gate('backup-surface',bool(existing),'no known backup/recovery state path exists')

# Existing Stage 9 recovery proofs are repository-native evidence that rollback/service recovery is tested.
proofs=[REPO/'scripts/lifeos-stage9-exit-gate-audit.sh',REPO/'scripts/lifeos-stage9-service-recovery-rehearsal.sh']
gate('recovery-proof-artifacts',all(p.exists() for p in proofs),'missing Stage 9 recovery proof artifacts')

# HA control surface should remain repository-native and healthy.
r=cp([sys.executable,'homeassistant/verify-lifeos-dashboard.py'])
gate('homeassistant-control-surface',r.returncode==0 and 'LIFEOS_HA_GATE=PASS' in r.stdout,(r.stdout+r.stderr).strip())

# Uptime Kuma presence is our OTS reachability/endpoint monitor. This audit deliberately does not build a second monitor.
gate('uptime-kuma', 'uptime-kuma' in names)

# Report concrete coverage/gaps for later OTS configuration work.
report={
  'schema_version':1,'capability_stage':3,'status':'PASS','ots_first':True,
  'containers':containers,'root_usage_percent':root_pct,'docker_usage_percent':docker_pct,
  'backup_surfaces':existing,
  'coverage':{
    'container_health':'Docker/Uptime Kuma','service_health':'systemd/Uptime Kuma',
    'network_reachability':'Uptime Kuma','home_automation':'Home Assistant',
    'orchestration':'Semaphore + GitHub Actions runner','rollback_recovery':'Stage 9 governed proof surface'
  },
  'known_followups':['verify backup freshness/restore cadence','verify certificate-expiry monitoring','verify update-awareness source'],
}
REPORT.parent.mkdir(parents=True,exist_ok=True); REPORT.write_text(json.dumps(report,indent=2)+'\n')
print('PASS: durable-report')

# Audit is non-mutating with respect to canonical source.
r=cp(['git','status','--porcelain','--untracked-files=all'])
gate('final-non-mutating',r.returncode==0 and not r.stdout.strip(),r.stdout.strip())

print('CAPABILITY_STAGE3_AUDIT=PASS')
print(f'containers={len(containers)} root_usage={root_pct}% docker_usage={docker_pct if docker_pct is not None else "n/a"}%')
print(f'REPORT={REPORT}')
print('CAPABILITY_STAGE3=IN_PROGRESS')
print('NEXT=prove backup freshness/restore cadence, certificate-expiry monitoring and update-awareness coverage using OTS tooling')
