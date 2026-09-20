#!/usr/bin/env python3
"""Sanitised P8-P10 readiness audit. No private content leaves the Pi."""
import os,sqlite3,subprocess
from pathlib import Path
repo=Path("/home/joshan/lifeos-platform")
db=Path.home()/".local/state/lifeos/pip/cross_system.sqlite3"
# Functional contracts first.
r=subprocess.run(["python3","-m","pytest","-q","tests/test_pip_p6_p10_functional.py"],cwd=repo)
if r.returncode: raise SystemExit(r.returncode)
print("P8_FUNCTIONAL_CONTRACT=PASS");print("P9_FUNCTIONAL_CONTRACT=PASS");print("P10_FUNCTIONAL_CONTRACT=PASS")
# Live readiness is deliberately stricter than code existence.
if db.exists():
 c=sqlite3.connect(db)
 tables={x[0] for x in c.execute("select name from sqlite_master where type='table'")}
 print("P8_LIVE_DB_PRESENT=YES")
 print("P8_RELATIONSHIP_SCHEMA="+("PASS" if "relationship" in tables else "FAIL"))
 print("P9_EVIDENCE_SCHEMA="+("PASS" if "evidence_link" in tables else "FAIL"))
 print("P10_EXCEPTION_SCHEMA="+("PASS" if "exception_queue" in tables else "FAIL"))
 print("P10_DB_MODE="+oct(db.stat().st_mode&0o777)[2:])
else:
 print("P8_LIVE_DB_PRESENT=NO");print("P8_RELATIONSHIP_SCHEMA=UNPROVEN");print("P9_EVIDENCE_SCHEMA=UNPROVEN");print("P10_EXCEPTION_SCHEMA=UNPROVEN")
# Acceptance requirements: don't promote merely because schemas/tests exist.
print("P8_ACCEPTANCE_NEEDED=real_cross_system_reference_creation_idempotency_authority_and_cleanup")
print("P9_ACCEPTANCE_NEEDED=real_readonly_ledger_to_paperless_reconciliation_plus_tax_guards_no_claim_mutation")
print("P10_ACCEPTANCE_NEEDED=live_continuous_end_to_end_recovery_exception_privacy_permissions_and_regression_audit")
print("P8_ACCEPTED=NO");print("P9_ACCEPTED=NO");print("P10_ACCEPTED=NO")
