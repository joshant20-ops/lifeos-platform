#!/usr/bin/env python3
"""Fail-closed validator for LifeOS Stage 10 engineering work contracts."""
from __future__ import annotations
import json,re,sys
from pathlib import Path
STATES={"PLANNED","IMPLEMENTING","TESTING","READY_TO_DEPLOY","DEPLOYING","VERIFYING","PASS","BLOCKED","FAILED","ROLLED_BACK"}; RISK={"read-only","bounded-change","privileged-bounded"}; TERMINAL={"PASS","BLOCKED","FAILED","ROLLED_BACK"}; WORK_ID_RE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"); SHA_RE=re.compile(r"^[0-9a-f]{40}$")
def fail(msg): print(f"CONTRACT_VALIDATION=FAIL reason={msg}"); raise SystemExit(1)
def require(c,msg):
 if not c: fail(msg)
def main():
 require(len(sys.argv)==2,"usage: validate-engineering-work-contract.py CONTRACT.json"); path=Path(sys.argv[1]); require(path.is_file(),"contract_missing")
 try: data=json.loads(path.read_text())
 except Exception as exc: fail(f"invalid_json:{type(exc).__name__}")
 required={"schema_version","work_id","issue","objective","risk_class","state","plan","tests","deployment","runtime_verification","evidence"}; require(isinstance(data,dict),"top_level_not_object"); require(required<=data.keys(),"missing_required_fields"); require(data["schema_version"]==1,"schema_version"); require(isinstance(data["work_id"],str) and WORK_ID_RE.fullmatch(data["work_id"]),"work_id"); require(isinstance(data["issue"],int) and data["issue"]>0,"issue"); require(isinstance(data["objective"],str) and data["objective"].strip(),"objective"); require(data["risk_class"] in RISK,"risk_class"); require(data["state"] in STATES,"state")
 plan=data["plan"]; require(isinstance(plan,dict) and isinstance(plan.get("steps"),list) and plan["steps"],"plan_steps"); seen=set()
 for step in plan["steps"]:
  require(isinstance(step,dict),"plan_step_not_object"); sid=step.get("id"); require(isinstance(sid,str) and sid and sid not in seen,"plan_step_id"); require(isinstance(step.get("description"),str) and step["description"].strip(),"plan_step_description"); seen.add(sid)
 tests=data["tests"]; require(isinstance(tests,list) and tests,"tests")
 for test in tests:
  require(isinstance(test,dict),"test_not_object"); require(isinstance(test.get("name"),str) and test["name"].strip(),"test_name"); require(isinstance(test.get("command"),str) and test["command"].strip(),"test_command"); require(isinstance(test.get("required"),bool),"test_required")
  if "result" in test: require(test["result"] in {"PENDING","PASS","FAIL"},"test_result")
 deploy=data["deployment"]; require(isinstance(deploy,dict) and isinstance(deploy.get("required"),bool),"deployment"); op=deploy.get("gateway_operation")
 if deploy["required"]: require(isinstance(op,str) and op.strip(),"deployment_gateway_operation_required"); require(deploy.get("rollback_required") is True,"rollback_required_for_deployment")
 else: require(op is None,"gateway_operation_must_be_null_when_no_deploy")
 commit=deploy.get("source_commit")
 if commit is not None: require(isinstance(commit,str) and SHA_RE.fullmatch(commit),"source_commit")
 runtime=data["runtime_verification"]; require(isinstance(runtime,dict) and isinstance(runtime.get("required"),bool),"runtime_verification"); require(isinstance(runtime.get("checks"),list),"runtime_checks")
 if runtime["required"]: require(bool(runtime["checks"]),"runtime_checks_required")
 if "result" in runtime: require(runtime["result"] in {"PENDING","PASS","FAIL"},"runtime_result")
 evidence=data["evidence"]; require(isinstance(evidence,dict) and isinstance(evidence.get("records"),list),"evidence_records"); state=data["state"]; blocker=data.get("blocker")
 if state=="BLOCKED": require(isinstance(blocker,dict),"blocked_requires_blocker"); require(isinstance(blocker.get("reason"),str) and blocker["reason"].strip(),"blocker_reason"); require(isinstance(blocker.get("next_action"),str) and blocker["next_action"].strip(),"blocker_next_action")
 elif blocker is not None: require(isinstance(blocker,dict),"blocker_type")
 if state=="PASS":
  require(all((not t["required"]) or t.get("result")=="PASS" for t in tests),"pass_requires_tests")
  if runtime["required"]: require(runtime.get("result")=="PASS","pass_requires_runtime_verification")
  if deploy["required"]: require(any(r.get("kind")=="deployment" for r in evidence["records"] if isinstance(r,dict)),"pass_requires_deployment_evidence")
 print("CONTRACT_VALIDATION=PASS"); print(f"WORK_ID={data['work_id']}"); print(f"ISSUE={data['issue']}"); print(f"STATE={state}"); print(f"RISK_CLASS={data['risk_class']}"); print(f"TERMINAL={'YES' if state in TERMINAL else 'NO'}")
if __name__=="__main__": main()
