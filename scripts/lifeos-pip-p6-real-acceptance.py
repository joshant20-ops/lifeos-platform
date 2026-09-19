#!/usr/bin/env python3
"""P6 real acceptance: reuse Wave-B Gmail->local AI->deterministic policy->Paperless path,
then prove the new two-axis disposition contract without creating a second importer."""
from __future__ import annotations
import importlib.util, pathlib, subprocess, sys, tempfile
REPO=pathlib.Path("/home/joshan/lifeos-platform")
# Existing Wave-B adapter performs a reversible synthetic message+PDF through real Gmail,
# Tower local AI, deterministic policy, real Paperless submission/verification and cleanup.
adapter=str(REPO/"homelab/live/home/joshan/automation/lifeos_email_paperless_selective.py")
# Reuse Wave B's established systemd credential boundary. Secrets stay root-owned and
# are exposed only to the transient User=joshan unit through CREDENTIALS_DIRECTORY.
password_candidates=("gmail-imap-password","gmail-app-password","imap-password")
password_source=next((f"/etc/lifeos/secrets/{name}" for name in password_candidates
                      if subprocess.run(["sudo","-n","test","-s",f"/etc/lifeos/secrets/{name}"]).returncode==0),None)
if not password_source:
    print("P6_WAVEB_REUSE=FAIL")
    print("P6_WAVEB_FAILURE_CLASS=CREDENTIAL_OR_BOUNDARY")
    raise SystemExit(1)
cmd=["sudo","-n","systemd-run","--quiet","--wait","--pipe","--collect",
     "--unit=lifeos-p6-selective-acceptance",
     "--property=User=joshan",
     "--property=WorkingDirectory=/home/joshan/lifeos-platform",
     "--property=LoadCredential=gmail-imap-user:/etc/lifeos/secrets/gmail-imap-user",
     "--property=LoadCredential=gmail-imap-password:"+password_source,
     "--property=LoadCredential=paperless-api-token:/etc/lifeos/secrets/paperless-api-token",
     sys.executable,adapter,"acceptance"]
r=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
required={"EMAIL_ADAPTER=REAL","LOCAL_TRIAGE=REAL_LOCAL_AI","DETERMINISTIC_POLICY=REAL","PAPERLESS_SUBMISSION=REAL","PAPERLESS_VERIFICATION=REAL","EVIDENCE_LINK=REAL","PAPERLESS_CLEANUP=PASS","EMAIL_CLEANUP=PASS","RESULT=PASS"}
seen={line.strip() for line in r.stdout.splitlines()}
if r.returncode or not required.issubset(seen):
    # Preserve privacy: expose only aggregate boundary/error class and missing public markers.
    missing=sorted(required-seen)
    stderr=(r.stderr or "").lower()
    if "unavailable" in stderr or "credential" in stderr: failure_class="CREDENTIAL_OR_BOUNDARY"
    elif "connection" in stderr or "urlopen" in stderr or "timeout" in stderr: failure_class="DEPENDENCY_OR_CONNECTIVITY"
    elif "deterministic_policy_rejected" in stderr: failure_class="POLICY_REJECTION"
    else: failure_class="ADAPTER_EXECUTION"
    print("P6_WAVEB_REUSE=FAIL")
    print("P6_WAVEB_RETURN_CODE="+str(r.returncode))
    print("P6_WAVEB_FAILURE_CLASS="+failure_class)
    print("P6_WAVEB_MISSING_MARKERS="+",".join(missing))
    raise SystemExit(1)
spec=importlib.util.spec_from_file_location("pipcore",REPO/"scripts/lifeos-pip-p6-p10-core.py")
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
cases=[
 ({"known_noise":True},"IGNORE"),
 ({"explicit_action":True},"ACTION"),
 ({"durable_evidence":True},"RETAIN"),
 ({"explicit_action":True,"durable_evidence":True},"ACTION_AND_RETAIN"),
 ({},"REVIEW"),
]
for features,want in cases:
    if core.disposition(features)!=want: raise SystemExit("p6_disposition_contract_failed")
with tempfile.TemporaryDirectory() as td:
    db=core.connect(pathlib.Path(td)/"p6.sqlite3")
    core.record_email(db,"synthetic-message-ref","ACTION_AND_RETAIN","p6_acceptance",paperless_id=1,action_ref="synthetic-action")
    core.record_email(db,"synthetic-message-ref","ACTION_AND_RETAIN","p6_acceptance",paperless_id=1,action_ref="synthetic-action")
    n=db.execute("select count(*) from email_disposition where message_ref='synthetic-message-ref'").fetchone()[0]
    if n!=1: raise SystemExit("p6_idempotency_failed")
print("P6_EXISTING_GMAIL_PATH=REUSED")
print("P6_SECOND_IMPORTER=NONE")
print("P6_PRIVATE_CONTENT_EMITTED=NONE")
print("P6_TWO_AXIS_DISPOSITION=PASS")
print("P6_IDEMPOTENCY=PASS")
print("P6_REAL_ACCEPTANCE=PASS")
