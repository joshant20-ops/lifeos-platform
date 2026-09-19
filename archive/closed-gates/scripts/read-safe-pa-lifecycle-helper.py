#!/usr/bin/env python3
"""Emit safe PA lifecycle helper source and structural producer/scheduler references."""
import subprocess
code=r'''
import pathlib,re
p=pathlib.Path('/config/scripts/lifeos_pa_lifecycle_export.py')
raw=p.read_text()
patterns=[r'(?i)(password|passwd|token|api[_-]?key|secret)\s*=\s*["\'][^"\']+["\']',r'https?://[^\s]+@']
if any(re.search(x,raw) for x in patterns):
 print('SAFE_SOURCE=REFUSED'); raise SystemExit(2)
print('SAFE_SOURCE=PASS')
print('---BEGIN---'); print(raw,end='' if raw.endswith('\n') else '\n'); print('---END---')
needles=('open_loops_attention.json','open_loops_active.json','pa_dashboard_summary.json')
for root in ('/config/scripts','/config/packages'):
 for q in pathlib.Path(root).rglob('*'):
  if not q.is_file() or q.stat().st_size>300000: continue
  try: text=q.read_text(errors='ignore')
  except Exception: continue
  if any(n in text for n in needles): print('CONFIG_REFERENCE='+str(q))
'''
r=subprocess.run(['docker','exec','homeassistant','python3','-c',code],text=True,capture_output=True)
print(r.stdout,end='')
if r.returncode: raise SystemExit(r.returncode)
s=subprocess.run(['sh','-lc',"grep -RIlE 'open_loops_attention\\.json|pa_dashboard_summary\\.json' /etc/systemd/system /usr/local/lib/systemd/system 2>/dev/null | sed 's#^.*/##' | sort -u"],text=True,capture_output=True)
for x in s.stdout.splitlines(): print('SYSTEMD_REFERENCE='+x)
u=subprocess.run(['sh','-lc',"systemctl list-unit-files --no-legend 2>/dev/null | awk '{print $1}' | grep -Ei 'energy|opportun|negative|octopus' | sort -u"],text=True,capture_output=True)
for x in u.stdout.splitlines(): print('ENERGY_UNIT='+x)
for unit in ('lifeos-energy-forecast.service','lifeos-energy-shadow-learning.service'):
 sh=subprocess.run(['systemctl','show',unit,'--property=User,ExecStart,WorkingDirectory,ActiveState'],text=True,capture_output=True)
 for line in sh.stdout.splitlines():
  if line.startswith('ExecStart='):
   # Emit only executable path/basename section, not environment/arguments after semicolons.
   v=line.split(';',1)[0][:500]
   print('UNIT_'+unit+'_'+v)
  elif line.startswith(('User=','WorkingDirectory=','ActiveState=')): print('UNIT_'+unit+'_'+line)
ur=subprocess.run(['systemctl','--user','is-system-running'],text=True,capture_output=True)
print('USER_SYSTEMD_RC='+str(ur.returncode)); print('USER_SYSTEMD_STATE='+(ur.stdout.strip() or 'none'))
