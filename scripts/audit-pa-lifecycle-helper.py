#!/usr/bin/env python3
"""Read-only structural inspection of the live PA lifecycle exporter.

Prints AST-level program structure and non-sensitive local file paths/JSON keys only.
It does not emit file contents, states, record values or secrets.
"""
import json,subprocess

HA='homeassistant'
code=r'''
import ast,json,pathlib,hashlib
p=pathlib.Path('/config/scripts/lifeos_pa_lifecycle_export.py')
if not p.exists():
 print(json.dumps({'exists':False})); raise SystemExit
raw=p.read_text(); t=ast.parse(raw)
imports=[]; functions=[]; constants=[]; dict_keys=set(); calls=set(); path_args=set(); argv_literals=set(); comparison_literals=set()
for n in ast.walk(t):
 if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
  functions.append({'name':n.name,'args':[a.arg for a in n.args.args]})
 elif isinstance(n,ast.Import): imports += [x.name for x in n.names]
 elif isinstance(n,ast.ImportFrom): imports.append((n.module or '')+':'+','.join(x.name for x in n.names))
 elif isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):
  for target in n.targets:
   if isinstance(target,ast.Name):
    v=n.value.value
    if (v.startswith('/config/') or v.startswith('/data/') or v.startswith('/tmp/') or 'lifeos' in v.lower()) and len(v)<180: constants.append({'name':target.id,'value':v})
 elif isinstance(n,ast.Constant) and isinstance(n.value,str):
  v=n.value
  if len(v)<80 and v.replace('_','').replace('-','').isalnum() and any(k in v.lower() for k in ('attention','loop','status','severity','source','id','title','summary','state','overdue','confirm')): dict_keys.add(v)
 elif isinstance(n,ast.Call):
  f=n.func
  if isinstance(f,ast.Name): calls.add(f.id)
  elif isinstance(f,ast.Attribute): calls.add(f.attr)
  if ((isinstance(f,ast.Name) and f.id=='Path') or (isinstance(f,ast.Attribute) and f.attr=='Path')) and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str):
   v=n.args[0].value
   if v.startswith(('/config/','/data/','/tmp/')) or 'lifeos' in v.lower(): path_args.add(v)
 elif isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and isinstance(n.value.value,ast.Name) and n.value.value.id=='sys' and n.value.attr=='argv':
  pass
 elif isinstance(n,ast.Compare):
  for c in n.comparators:
   if isinstance(c,ast.Constant) and isinstance(c.value,str) and len(c.value)<80: comparison_literals.add(c.value)
print(json.dumps({'exists':True,'sha256':hashlib.sha256(raw.encode()).hexdigest(),'imports':sorted(set(imports)),'functions':functions,'local_constants':constants,'path_args':sorted(path_args),'key_literals':sorted(dict_keys),'comparison_literals':sorted(comparison_literals),'calls':sorted(calls)},sort_keys=True))
'''
r=subprocess.run(['docker','exec',HA,'python3','-c',code],text=True,capture_output=True)
if r.returncode: raise SystemExit(r.stderr)
d=json.loads(r.stdout)
print('PA_LIFECYCLE_HELPER_AUDIT=PASS')
print(json.dumps(d,sort_keys=True))
print('SOURCE_CONTENT_EMITTED=NO')
print('RECORD_VALUES_EMITTED=NO')
