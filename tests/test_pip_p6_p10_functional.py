import importlib.util
from pathlib import Path
P=Path(__file__).parents[1]/"scripts/lifeos-pip-p6-p10-core.py";s=importlib.util.spec_from_file_location("pip",P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_p6_disposition_axes():
 assert m.disposition({"explicit_action":1,"durable_evidence":1})=="ACTION_AND_RETAIN"
 assert m.disposition({"explicit_action":1})=="ACTION";assert m.disposition({"durable_evidence":1})=="RETAIN";assert m.disposition({"known_noise":1})=="IGNORE";assert m.disposition({})=="REVIEW"
def test_p7_idempotent_email_state(tmp_path):
 d=m.connect(tmp_path/"x.db");m.record_email(d,"gmail:1","RETAIN","synthetic",10);m.record_email(d,"gmail:1","RETAIN","synthetic",10);assert d.execute("select count(*) from email_disposition").fetchone()[0]==1
def test_p8_relationship_idempotent(tmp_path):
 d=m.connect(tmp_path/"x.db");m.link(d,"gmail","1","paperless","10","evidence");m.link(d,"gmail","1","paperless","10","evidence");assert d.execute("select count(*) from relationship").fetchone()[0]==1
def test_p9_evidence_is_reference_not_ledger(tmp_path):
 d=m.connect(tmp_path/"x.db");m.evidence(d,"freeagent","txn-synthetic",10,"MATCHED","synthetic");cols={x[1] for x in d.execute("pragma table_info(evidence_link)")};assert "amount" not in cols and "balance" not in cols
def test_p10_private_permissions_and_exception_queue(tmp_path):
 p=tmp_path/"state"/"x.db";d=m.connect(p);m.exception(d,"email","gmail:2","ambiguous");m.service(d,"pipeline","RUNNING");assert p.stat().st_mode&0o777==0o600;assert d.execute("select count(*) from exception_queue").fetchone()[0]==1
