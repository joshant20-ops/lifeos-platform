import csv,io
from datetime import date
from governor.finance_assets_readonly import FinanceReadModel,SourceTransaction,EvidenceReference
from governor.finance_workflows import FinanceWorkflows,Classification
def seeded(tmp_path):
 m=FinanceReadModel(tmp_path/"f.sqlite3");rows=[
 SourceTransaction("synthetic","rent-1","a",date(2025,5,1),140000,"GBP","income",property_ref="property:p1"),
 SourceTransaction("synthetic","repair-1","a",date(2025,5,3),-12550,"GBP","expense",property_ref="property:p1"),
 SourceTransaction("synthetic","mortgage-1","a",date(2025,5,4),-30000,"GBP","expense",property_ref="property:p1"),
 SourceTransaction("synthetic","unknown-1","a",date(2025,5,5),-999,"GBP","expense",property_ref="property:p1"),
 SourceTransaction("synthetic","repair-2","a",date(2025,6,3),-12550,"GBP","expense",property_ref="property:p1")]
 m.ingest(rows);return m,rows
def test_copilot_and_ai_review_boundary(tmp_path):
 m,rows=seeded(tmp_path);f=FinanceWorkflows(m)
 for row,cat,origin in [(rows[0],"rental_income","deterministic"),(rows[1],"repairs_maintenance","deterministic"),(rows[2],"residential_finance_cost","deterministic"),(rows[3],"other_allowable","local-ai-proposal"),(rows[4],"repairs_maintenance","deterministic")]:f.propose(Classification(row.record_id,cat,origin,.71 if origin=="local-ai-proposal" else 1))
 r=f.copilot(date(2025,4,6),date(2026,4,5),"property:p1")
 assert r["income_minor"]==140000 and r["expense_minor"]==56099
 assert rows[3].record_id in r["unresolved_record_ids"] and r["recurring_candidates"][0]["occurrences"]==2
 f.review_ai(rows[3].record_id,True)
 assert rows[3].record_id not in f.copilot(date(2025,4,6),date(2026,4,5),"property:p1")["unresolved_record_ids"]
def test_tax_pack_is_versioned_provenance_preserving_and_no_submission(tmp_path):
 m,rows=seeded(tmp_path);f=FinanceWorkflows(m);cats=["rental_income","repairs_maintenance","residential_finance_cost",None,"repairs_maintenance"]
 for row,cat in zip(rows,cats):
  if cat:f.propose(Classification(row.record_id,cat,"deterministic"))
 m.link_exact_evidence([EvidenceReference(42,"a"*64,"invoice",-12550,"GBP",date(2025,5,3))])
 p=f.rental_tax_pack("2025-26","governor/contracts/uk-property-tax/2025-26.json","property:p1")
 assert p["sa105_boxes_minor"]["20"]==140000 and p["sa105_boxes_minor"]["25"]==25100 and p["sa105_boxes_minor"]["44"]==30000
 assert p["allowable_expenses_minor"]==25100 and p["accounting_result_before_residential_finance_cost_minor"]==114900
 assert p["residential_finance_cost_minor"]==30000 and rows[3].record_id in p["unresolved_record_ids"]
 assert rows[2].record_id in p["missing_evidence_record_ids"] and p["evidence_index"][0]["paperless_document_id"]==42
 assert p["hmrc_submission_performed"] is False
def test_accountant_export_reproducible_and_references_only(tmp_path):
 m,rows=seeded(tmp_path);f=FinanceWorkflows(m);f.propose(Classification(rows[0].record_id,"rental_income","deterministic"))
 a=f.accountant_csv("2025-26","property:p1");b=f.accountant_csv("2025-26","property:p1");assert a==b
 parsed=list(csv.DictReader(io.StringIO(a)));assert len(parsed)==5 and parsed[0]["record_id"]==rows[0].record_id
 assert "description" not in parsed[0] and "document_content" not in parsed[0]
def test_unsupported_tax_year_fails_closed(tmp_path):
 m,_=seeded(tmp_path);f=FinanceWorkflows(m)
 try:f.rental_tax_pack("2026-27","governor/contracts/uk-property-tax/2025-26.json","property:p1")
 except ValueError as e:assert "unsupported tax year" in str(e)
 else:raise AssertionError("unsupported tax year accepted")
def test_module_has_no_network_or_authority_mutation():
 text=open("governor/finance_workflows.py",encoding="utf-8").read().lower()
 for forbidden in ("urllib","requests","method=\\\"post\\\"","hmrc.gov.uk/api","paperless_url"):assert forbidden not in text
