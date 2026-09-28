import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
links=load("links",ROOT/"scripts/lifeos-pip-document-links.py")
core=load("core",ROOT/"scripts/lifeos-pip-p6-p10-core.py")
def intel(org="Acme",date="2026-01-01",amount="£10"):
 return {"document_type":"invoice","summary":"synthetic","obligations":[],"dates":[date],"amounts":[amount],"organisations":[org],"confidence":.9}
def test_candidates_require_deterministic_shared_feature():
 rows=[(1,intel()),(2,intel()),(3,intel("Other","2025-02-02","£99"))]
 result=links.candidates(rows,10)
 assert [(x[0],x[2]) for x in result]==[(1,2)]
 assert "organisation:acme" in result[0][4]
def test_local_model_proposal_must_cite_shared_evidence():
 shared=["organisation:acme","date:2026-01-01"]
 def generate(*args,**kwargs):
  assert kwargs=={"privacy":"local-only","force_provider":"ollama"}
  return {"provider":"ollama","model":"openai/gpt-oss:20b","text":json.dumps({"linked":True,"relation":"same_contract","evidence":shared,"confidence":.82})}
 proposal,model=links.analyse_pair(intel(),intel(),shared,generate)
 assert proposal["relation"]=="same_contract"
 assert model=="openai/gpt-oss:20b"
def test_unsupported_or_invented_evidence_fails_closed():
 try: links.validate_proposal({"linked":True,"relation":"same_asset","evidence":["asset:invented"],"confidence":.9},["organisation:acme"])
 except ValueError as exc: assert str(exc)=="unsupported_evidence"
 else: raise AssertionError("invented evidence accepted")
def test_ai_proposal_requires_review_before_authoritative_link(tmp_path):
 db=core.connect(tmp_path/"relationships.db")
 status=core.propose_relationship(db,"paperless",1,"paperless",2,"same_contract",.85,["organisation:acme"],"openai/gpt-oss:20b")
 assert status=="REVIEW"
 assert db.execute("select count(*) from relationship").fetchone()[0]==0
 proposal_id=db.execute("select id from relationship_proposal").fetchone()[0]
 core.accept_relationship_proposal(db,proposal_id,"manual:test")
 assert db.execute("select count(*) from relationship").fetchone()[0]==1
 assert db.execute("select status from relationship_proposal").fetchone()[0]=="ACCEPTED"
def test_low_confidence_proposal_is_rejected(tmp_path):
 db=core.connect(tmp_path/"relationships.db")
 assert core.propose_relationship(db,"paperless",1,"paperless",2,"supports",.4,["date:2026-01-01"],"model")=="REJECTED"
