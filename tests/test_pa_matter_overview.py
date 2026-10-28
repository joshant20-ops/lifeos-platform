"""Source recognition, event-scoped decisions and informational read model."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"homelab/live/home/joshan/automation"))
from governor import pa_user_state as state
import lifeos_task_reconciler as reconciler

def source(n="a", **kw):
    return {"from":"OpenAI <noreply@tm.openai.com>","message_id":f"<{n}@example.test>","subject":"New login to your account", "body":"Was this you? If this was you, no action required.","date":"Wed, 28 Oct 2026 11:42:00 +0000",**kw}

def row(messages):
    return {"id":"synthetic-alert", "title":"Review OpenAI account security", "status":"OPEN", "source_message_ids":[m["message_id"] for m in messages],"sign_in_events":[reconciler.sign_in_event(m) for m in messages]}

def payload(task):
    return {"schema":"lifeos_tasks_v3","generated_time":int(time.time()),"tasks":[task],"resolved":[]}

class MatterOverviewTests(unittest.TestCase):
    def test_actual_alert_exempts_conditional_no_action_but_otp_and_advice_do_not(self):
        self.assertIsNotNone(reconciler.sign_in_event(source()))
        with patch.object(reconciler.ai_broker,"_ollama",side_effect=AssertionError("no inference needed")):
            self.assertTrue(reconciler.classify(source())["actionable"])
        self.assertFalse(reconciler.has_explicit_no_action_required(source()))
        for message in [source(subject="Your verification code",body="Your one-time code is 123456"),source(subject="Account security",body="Enable MFA to protect your account"),source(subject="Password changed",body="Was this you? Sign in to review your account."),source(**{"from":"OpenAI <sender@example.test>"})]:
            self.assertIsNone(reconciler.sign_in_event(message))
        event=reconciler.sign_in_event(source(date="invalid"))
        self.assertIsNone(event["email_received_at"])
        self.assertIsNone(event["device"])

    def test_native_card_guard_accepts_the_actual_dynamic_button_implementation(self):
        # The attribute is assembled from an answer value at render time.
        card=(ROOT/"homeassistant/www/lifeos-pa-task-card.js").read_text()
        audit=(ROOT/"scripts/accept-pa-governed-actions.py").read_text()
        import ast
        tree=ast.parse(audit)
        marker_tuples=[node for node in ast.walk(tree) if isinstance(node,ast.Tuple) and any(isinstance(value,ast.Constant) and value.value=="_overviewMarkup" for value in node.elts)]
        self.assertEqual(len(marker_tuples),1)
        self.assertTrue(all(marker in card for marker in ast.literal_eval(marker_tuples[0])))

    def test_all_yes_replay_and_new_alert_remain_event_scoped(self):
        a,b=source(),source("b")
        task=row([a]);event=task["sign_in_events"][0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"overlay.json"
            state.mutate_action(task["id"],"signin_yes",note=event["id"],path=path)
            overlay=state.read_user_state(path)
            first=state.apply_user_state(payload(task),overlay)
            self.assertEqual(first["resolved"][0]["status"],"DONE")
            self.assertEqual(state.apply_user_state(first,overlay)["resolved"][0]["status"],"DONE")
            task=row([a,b]); fresh=state.apply_user_state(payload(task),overlay)
            self.assertEqual(fresh["tasks"][0]["sign_in_events"][1]["answer"],None)
            self.assertEqual(fresh["tasks"][0]["status"],"OPEN")
            task=row([a]);task["source_message_ids"].append("<unrelated@example.test>")
            self.assertEqual(state.apply_user_state(payload(task),overlay)["tasks"][0]["status"],"OPEN")

    def test_no_supersedes_previous_close_and_unsure_survives_replay(self):
        task=row([source()]);event=task["sign_in_events"][0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"overlay.json"
            state.mutate_action(task["id"],"close",path=path,now=1)
            state.mutate_action(task["id"],"signin_no",note=event["id"],path=path,now=2)
            view=state.apply_user_state(payload(task),state.read_user_state(path))
            self.assertEqual(view["tasks"][0]["sign_in_events"][0]["answer"],"no")
            self.assertEqual(view["tasks"][0]["status"],"OPEN")
            state.mutate_action(task["id"],"signin_unsure",note=event["id"],path=path,now=3)
            self.assertEqual(state.apply_user_state(view,state.read_user_state(path))["tasks"][0]["status"],"OPEN")

    def test_information_retains_notes_without_attention_or_duplicates(self):
        task={**row([source()]),"id":"synthetic-quote","sign_in_events":[],"obligation_suppressed":"quote_only_no_verified_policy"}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"overlay.json"
            state.mutate_action(task["id"],"comment",note="Keep the quote",path=path)
            original={**payload(task),"tasks":[],"resolved":[{**task,"status":"DONE"}],"informational":[task]}
            view=state.apply_user_state(original,state.read_user_state(path))
            self.assertEqual(view["tasks"],[]);self.assertEqual(view["resolved"],[])
            self.assertEqual(view["attention"]["counts"]["needs_me"],0)
            self.assertEqual(view["informational"][0]["user_comments"][0]["text"],"Keep the quote")
            self.assertEqual(state.apply_user_state(view,state.read_user_state(path))["informational"],view["informational"])

    def test_bridge_rejects_unknown_event_and_information_close_before_mutation(self):
        action_path=ROOT/"homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_user_action.py"
        with patch.dict(sys.modules,{"lifeos_pa_user_state":state}):
            spec=importlib.util.spec_from_file_location("overview_action",action_path);bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"view.json"; task=row([source()]);path.write_text(json.dumps(payload(task)))
            with patch.object(bridge,"STATE",path),patch.object(state,"drop_to_state_owner") as drop,patch.object(bridge,"mutate_action") as mutate:
                with patch.object(sys,"argv",["action","--action","signin_no","--task-id",task["id"],"--note","b"*64]):
                    with self.assertRaisesRegex(ValueError,"signin_event_not_in_current_view"):bridge.main()
                drop.assert_not_called();mutate.assert_not_called()
                task["obligation_suppressed"]="quote_only_no_verified_policy"
                path.write_text(json.dumps({**payload(task),"tasks":[],"informational":[task]}))
                with patch.object(sys,"argv",["action","--action","close","--task-id",task["id"]]):
                    with self.assertRaisesRegex(ValueError,"informational_action_not_allowed"):bridge.main()
                drop.assert_not_called();mutate.assert_not_called()

    def test_sensor_projects_information_and_questions_without_body(self):
        sensor_path=ROOT/"homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py"
        with patch.dict(sys.modules,{"lifeos_pa_user_state":state}):
            spec=importlib.util.spec_from_file_location("overview_sensor",sensor_path);sensor=importlib.util.module_from_spec(spec);spec.loader.exec_module(sensor)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"view.json"
            data=payload(row([source()]))
            data["informational"]=[{"id":"quote","title":"Quote", "status":"OPEN","obligation_suppressed":"quote_only_no_verified_policy"}]
            path.write_text(json.dumps(data))
            out=io.StringIO()
            with patch.object(sensor,"TASKS",path),patch.object(sensor,"read_user_state",return_value={"obligations":{}}),contextlib.redirect_stdout(out):sensor.main()
            view=json.loads(out.getvalue())
            self.assertEqual(view["questions"],1);self.assertEqual(view["information"],1)
            self.assertEqual(len(view["items"]),1)
            self.assertEqual(len(view["reference_items"]),1)
            self.assertFalse(any(item.get("obligation_suppressed") for item in view["items"]))
            # The old card sees only items and chooses OPEN/WAITING rows. A
            # retained quote must stay out even before the JS module refreshes.
            self.assertNotIn("quote",[item["id"] for item in view["items"] if item.get("status") in {"OPEN","WAITING"}])
            self.assertNotIn("body",json.dumps(view))

if __name__=="__main__": unittest.main()
