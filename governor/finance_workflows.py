"""Deterministic local-only Finance co-pilot and UK rental tax-pack primitives."""
from __future__ import annotations
import csv, io, json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from governor.finance_assets_readonly import FinanceReadModel, uk_tax_year
ALLOWED_ORIGINS={"deterministic","accounting-ots","local-ai-proposal"}
AUTHORITATIVE_ORIGINS={"deterministic","accounting-ots"}
@dataclass(frozen=True)
class Classification:
    record_id:str; category:str; origin:str; confidence:float=1.0; reason:str=""
class FinanceWorkflows:
    def __init__(self,model:FinanceReadModel):
        self.model=model; c=model.connection
        c.execute("""CREATE TABLE IF NOT EXISTS finance_classifications(
        record_id TEXT PRIMARY KEY,category TEXT NOT NULL,origin TEXT NOT NULL,
        confidence REAL NOT NULL,reason TEXT NOT NULL DEFAULT '',accepted INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(record_id) REFERENCES finance_records(record_id))"""); c.commit()
    def propose(self,item:Classification)->None:
        if item.origin not in ALLOWED_ORIGINS: raise ValueError("invalid classification origin")
        if not 0<=item.confidence<=1: raise ValueError("confidence outside 0..1")
        if not self.model.connection.execute("select 1 from finance_records where record_id=?",(item.record_id,)).fetchone(): raise KeyError(item.record_id)
        accepted=1 if item.origin in AUTHORITATIVE_ORIGINS else 0
        self.model.connection.execute("""insert into finance_classifications(record_id,category,origin,confidence,reason,accepted)
        values(?,?,?,?,?,?) on conflict(record_id) do update set category=excluded.category,origin=excluded.origin,
        confidence=excluded.confidence,reason=excluded.reason,accepted=excluded.accepted""",
        (item.record_id,item.category,item.origin,item.confidence,item.reason,accepted)); self.model.connection.commit()
    def review_ai(self,record_id:str,accept:bool)->None:
        row=self.model.connection.execute("select origin from finance_classifications where record_id=?",(record_id,)).fetchone()
        if row is None: raise KeyError(record_id)
        if row["origin"]!="local-ai-proposal": raise ValueError("only AI proposals require review")
        self.model.connection.execute("update finance_classifications set accepted=? where record_id=?",(1 if accept else 0,record_id)); self.model.connection.commit()
    def _rows(self,start:date,end:date,property_ref:str|None=None):
        q="""select r.*,c.category,c.origin,c.confidence,c.accepted from finance_records r
        left join finance_classifications c using(record_id) where r.booked_on between ? and ?"""
        p=[start.isoformat(),end.isoformat()]
        if property_ref is not None:q+=" and r.property_ref=?";p.append(property_ref)
        return self.model.connection.execute(q,p).fetchall()
    def copilot(self,start:date,end:date,property_ref:str|None=None)->dict[str,Any]:
        rows=self._rows(start,end,property_ref);categories={};recurring={};unresolved=[];missing=[]
        for r in rows:
            if r["category"] and r["accepted"]:categories[r["category"]]=categories.get(r["category"],0)+r["amount_minor"]
            else:unresolved.append(r["record_id"])
            if r["evidence_json"]=="[]" and r["amount_minor"]<0:missing.append(r["record_id"])
            key=(r["amount_minor"],r["currency"],r["category"] or "unclassified");recurring[key]=recurring.get(key,0)+1
        income=sum(r["amount_minor"] for r in rows if r["amount_minor"]>0);expense=-sum(r["amount_minor"] for r in rows if r["amount_minor"]<0)
        return {"privacy":"local-only","mode":"read-only","period":{"start":start.isoformat(),"end":end.isoformat()},
        "property_ref":property_ref,"record_count":len(rows),"income_minor":income,"expense_minor":expense,
        "net_cash_flow_minor":income-expense,"category_totals_minor":categories,"unresolved_record_ids":unresolved,
        "missing_evidence_record_ids":missing,"recurring_candidates":[{"amount_minor":k[0],"currency":k[1],"category":k[2],"occurrences":v}
        for k,v in sorted(recurring.items()) if v>=2],"facts_authoritative":False,
        "facts_basis":"derived-from-authoritative-source-references","ai_observations":[]}
    @staticmethod
    def load_tax_rules(path:str|Path,tax_year:str)->dict[str,Any]:
        data=json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("tax_year")!=tax_year:raise ValueError("unsupported tax year")
        return data
    def rental_tax_pack(self,tax_year:str,rules_path:str|Path,property_ref:str)->dict[str,Any]:
        rules=self.load_tax_rules(rules_path,tax_year);sy=int(tax_year[:4]);rows=self._rows(date(sy,4,6),date(sy+1,4,5),property_ref)
        boxes={str(k):0 for k in rules["boxes"]};unresolved=[];evidence=[];finance_cost=0
        for r in rows:
            if uk_tax_year(date.fromisoformat(r["booked_on"]))!=tax_year:continue
            ev=json.loads(r["evidence_json"]);evidence.extend({"record_id":r["record_id"],**x} for x in ev)
            if not r["category"] or not r["accepted"]:unresolved.append(r["record_id"]);continue
            rule=rules["categories"].get(r["category"])
            if rule is None:unresolved.append(r["record_id"]);continue
            box=str(rule["box"]);value=r["amount_minor"] if r["amount_minor"]>0 else -r["amount_minor"];boxes[box]=boxes.get(box,0)+value
            if rule.get("finance_cost"):finance_cost+=value
        missing=[r["record_id"] for r in rows if r["amount_minor"]<0 and r["evidence_json"]=="[]"]
        allowable=sum(v for b,v in boxes.items() if b in {"24","25","26","27","28","29","36"});income=boxes.get("20",0)
        return {"privacy":"local-only","mode":"draft-review-only","tax_year":tax_year,"property_ref":property_ref,
        "rules_version":rules["version"],"authority":rules["authority"],"sa105_boxes_minor":boxes,"rental_income_minor":income,
        "allowable_expenses_minor":allowable,"accounting_result_before_residential_finance_cost_minor":income-allowable,
        "residential_finance_cost_minor":finance_cost,"unresolved_record_ids":sorted(set(unresolved)),
        "missing_evidence_record_ids":sorted(set(missing)),"evidence_index":evidence,"hmrc_submission_performed":False}
    def accountant_csv(self,tax_year:str,property_ref:str)->str:
        sy=int(tax_year[:4]);rows=self._rows(date(sy,4,6),date(sy+1,4,5),property_ref);out=io.StringIO();w=csv.writer(out)
        w.writerow(["record_id","source_system","source_record_id","booked_on","amount_minor","currency","property_ref","category","classification_origin","classification_accepted","evidence_refs"])
        for r in rows:
            refs=json.loads(r["evidence_json"]);w.writerow([r["record_id"],r["source_system"],r["source_record_id"],r["booked_on"],r["amount_minor"],r["currency"],r["property_ref"],r["category"] or "",r["origin"] or "",int(r["accepted"] or 0),";".join(f"paperless:{x['paperless_document_id']}:{x['sha256']}" for x in refs)])
        return out.getvalue()
