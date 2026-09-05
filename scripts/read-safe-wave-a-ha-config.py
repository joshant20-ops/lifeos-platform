#!/usr/bin/env python3
"""Emit selected small HA package sources after a conservative credential scan."""
import subprocess
code=r'''
import pathlib,re
files=['/config/packages/lifeos_attention.yaml','/config/packages/lifeos_pa_lifecycle.yaml']
patterns=[r'(?i)(password|passwd|token|api[_-]?key|secret)\s*[:=]\s*["\']?[^\s"\']+',r'https?://[^\s]+@']
for f in files:
 p=pathlib.Path(f); raw=p.read_text()
 if any(re.search(x,raw) for x in patterns):
  print('SAFE_CONFIG=REFUSED '+f); raise SystemExit(2)
 print('---BEGIN '+f+'---'); print(raw,end='' if raw.endswith('\n') else '\n'); print('---END '+f+'---')
print('SAFE_CONFIG=PASS')
'''
r=subprocess.run(['docker','exec','homeassistant','python3','-c',code],text=True,capture_output=True)
print(r.stdout,end='')
if r.returncode: raise SystemExit(r.returncode)
