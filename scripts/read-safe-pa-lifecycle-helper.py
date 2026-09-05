#!/usr/bin/env python3
"""Emit the small live PA lifecycle helper only after a conservative secret scan.
Used to establish canonical source before Wave A mutation.
"""
import subprocess
code=r'''
import pathlib,re
p=pathlib.Path('/config/scripts/lifeos_pa_lifecycle_export.py')
raw=p.read_text()
# Refuse to emit if it appears to contain embedded credentials or network secrets.
patterns=[r'(?i)(password|passwd|token|api[_-]?key|secret)\s*=\s*["\'][^"\']+["\']',r'https?://[^\s]+@']
if any(re.search(x,raw) for x in patterns):
 print('SAFE_SOURCE=REFUSED'); raise SystemExit(2)
print('SAFE_SOURCE=PASS')
print('---BEGIN---')
print(raw,end='' if raw.endswith('\n') else '\n')
print('---END---')
'''
r=subprocess.run(['docker','exec','homeassistant','python3','-c',code],text=True,capture_output=True)
print(r.stdout,end='')
if r.returncode: raise SystemExit(r.returncode)
