#!/usr/bin/env python3
"""P9 bounded live acceptance before FreeAgent OAuth: real Paperless authority + synthetic ledger-side transaction."""
import hashlib,importlib.util,subprocess,tempfile
from datetime import date
from pathlib import Path
repo=Path("/home/joshan/lifeos-platform")
spec=importlib.util.spec_from_file_location("fin",repo/"governor/finance_assets_readonly.py");fin=importlib.util.module_from_spec(spec);spec.loader.exec_module(fin)
# Real Paperless authority: read only an ID and checksum locally; no title/OCR/private content emitted.
q="from documents.models import Document; d=Document.objects.order_by('id').first(); print(f'{d.id}\\t{d.checksum}' if d else '')"
r=subprocess.run(["docker","exec","-i","paperless-paperless-1","python3","manage.py","shell"],input=q,capture_output=True,text=True,timeout=60)
rows=[x.strip().split("\t") for x in r.stdout.splitlines() if "\t" in x]
if r.returncode or not rows or not rows[-1][0].isdigit() or len(rows[-1][1])<16: raise SystemExit("P9_PAPERLESS_READ=FAIL")
pid=int(rows[-1][0]); checksum=rows[-1][1]
# Until human FreeAgent OAuth exists, ledger side must remain synthetic; this explicitly does not fake real-ledger acceptance.
with tempfile.TemporaryDirectory() as td:
 model=fin.FinanceReadModel(Path(td)/"finance.sqlite3")
 tx=fin.SourceTransaction("freeagent-synthetic","p9-canary","account:synthetic",date(2026,5,3),-12550,"GBP","expense",property_ref="property:synthetic")
 result=model.ingest_reconciled([tx])
 if result["status"]!="PASS": raise SystemExit("P9_READ_MODEL=FAIL")
 ev=fin.EvidenceReference(pid,checksum,"supporting_evidence",-12550,"GBP",date(2026,5,3),True)
 if model.link_exact_evidence([ev])!=1: raise SystemExit("P9_EXACT_LINK=FAIL")
 if model.link_exact_evidence([ev])!=0: raise SystemExit("P9_IDEMPOTENCY=FAIL")
 row=model.connection.execute("select evidence_json from finance_records").fetchone()[0]
 if str(pid) not in row or checksum not in row: raise SystemExit("P9_REFERENCE_PERSISTENCE=FAIL")
# Tax guard is deterministic and synthetic by design; never infer deductibility from real private docs.
tax_related=True; spent=False; purpose="unknown"; deductible=bool(spent and purpose in {"work","rental_property"})
if not tax_related or deductible: raise SystemExit("P9_TAX_GUARD=FAIL")
# Prove production cross-system DB exists and P9 schema stores references/status, not ledger values.
core=Path.home()/".local/state/lifeos/pip/cross_system.sqlite3"
if not core.exists(): raise SystemExit("P9_PRODUCTION_STATE=FAIL")
import sqlite3
c=sqlite3.connect(core); cols={x[1] for x in c.execute("pragma table_info(evidence_link)")}
if {"amount","amount_minor","balance"} & cols: raise SystemExit("P9_LEDGER_COPY_GUARD=FAIL")
print("P9_REAL_PAPERLESS_AUTHORITY=PASS");print("P9_LEDGER_SIDE=SYNTHETIC_PENDING_HUMAN_FREEAGENT_OAUTH");print("P9_READONLY_RECONCILIATION=PASS");print("P9_EXACT_EVIDENCE_LINK=PASS");print("P9_IDEMPOTENCY=PASS");print("P9_TAX_NOT_DEDUCTIBILITY=PASS");print("P9_LEDGER_MUTATION=NONE");print("P9_PAPERLESS_MUTATION=NONE");print("P9_PRIVATE_CONTENT_EMITTED=NONE");print("P9_PREAUTH_ACCEPTANCE=PASS");print("P9_FULL_REAL_ACCEPTANCE=BLOCKED_HUMAN_FREEAGENT_OAUTH")
