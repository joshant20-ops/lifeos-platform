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

    def test_real_ha_sensor_allows_all_overview_attributes(self):
        package=(ROOT/"homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml").read_text()
        attributes=package.split("      json_attributes:",1)[1]
        for key in ("items","reference_items","questions","information","total_matters"):
            self.assertIn("        - "+key+"\n",attributes)

    def test_waiting_context_is_bounded_and_only_projected_for_waiting_items(self):
        sensor_path=ROOT/"homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py"
        spec=importlib.util.spec_from_file_location("pa_attention_sensor_waiting_test",sensor_path)
        sensor=importlib.util.module_from_spec(spec);spec.loader.exec_module(sensor)
        source={"status":"WAITING","counterparty":" Tesla  Motors ","topic":" Vehicle order ","reason":" Await the identity-check email after assignment. "}
        self.assertEqual(sensor.project_waiting_context(source),{
            "counterparty":"Tesla Motors","topic":"Vehicle order","reason":"Await the identity-check email after assignment."
        })
        self.assertIsNone(sensor.project_waiting_context({**source,"status":"OPEN"}))
        self.assertLessEqual(len(sensor.project_waiting_context({**source,"reason":"r"*500})["reason"]),240)

    def test_source_context_backfills_verified_email_without_changing_obligation(self):
        msg=source('order',**{'from':'=?UTF-8?Q?Device_Shop?= <orders@example.test>','subject':'Order TEST1042 confirmed','body':'Order TEST1042 contains two smart relays.'})
        task={'id':'synthetic-order','status':'WAITING','due_date':None,'email_message_id':msg['message_id'],'source_message_ids':[msg['message_id']]}
        answer={'summary':'Two smart relays ordered.','waiting_for':'Collection-ready email','next_step':''}
        with patch.object(reconciler.ai_broker,'_ollama',return_value=json.dumps(answer)) as model:
            reconciler.refresh_source_context(task,{msg['message_id']:msg},[1])
            self.assertEqual(task['source_context']['sender'],'Device Shop <orders@example.test>')
            self.assertEqual(task['source_context']['summary'],answer['summary'])
            self.assertEqual(task['status'],'WAITING')
            self.assertIsNone(task['due_date'])
            self.assertEqual(task['verified_order_refs'],['TEST1042'])
            reconciler.refresh_source_context(task,{msg['message_id']:msg},[1])
            self.assertEqual(model.call_count,1)

    def test_source_context_identity_budget_and_failure_boundaries(self):
        msg=source('order',subject='Order TEST1042 confirmed')
        task={'id':'synthetic-order','status':'WAITING','email_message_id':msg['message_id'],'source_message_ids':[msg['message_id']]}
        with patch.object(reconciler.ai_broker,'_ollama',side_effect=RuntimeError('private model content')) as model:
            reconciler.refresh_source_context(task,{msg['message_id']:{**msg,'message_id':'<other@example.test>'}},[1])
            self.assertNotIn('source_context',task)
            reconciler.refresh_source_context(task,{msg['message_id']:msg},[0])
            model.assert_not_called()
            reconciler.refresh_source_context(task,{msg['message_id']:msg},[1])
            self.assertEqual(task['source_context']['subject'],msg['subject'])
            self.assertIsNone(task['source_context']['briefing_version'])
        self.assertNotEqual(reconciler.order_reference_ids(msg),reconciler.order_reference_ids(source(subject='Order TEST2042 confirmed')))

    def test_source_context_sensor_requires_provenance_and_bounds_fields(self):
        spec=importlib.util.spec_from_file_location('pa_context_sensor',ROOT/'homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py')
        sensor=importlib.util.module_from_spec(spec);spec.loader.exec_module(sensor)
        task={'source_message_ids':['<a@example.test>'],'source_context':{'message_id':'<b@example.test>','sender':'x'*500}}
        self.assertIsNone(sensor.project_source_context(task))
        task['source_context']['message_id']='<a@example.test>'
        self.assertEqual(len(sensor.project_source_context(task)['sender']),200)
        self.assertNotIn('message_id',sensor.project_source_context(task))

    def test_html_template_cannot_truncate_the_actual_order_contents(self):
        markup='<html><head><style>'+('x'*14000)+'</style></head><body><p>Order number is: # TEST1042</p><table><tr><td>Two smart relays</td></tr></table><script>ignore_me()</script></body></html>'
        msg=reconciler.email.message_from_string('Content-Type: text/html; charset=utf-8\n\n'+markup)
        text=reconciler.text_of(msg)
        self.assertIn('Two smart relays',text)
        self.assertNotIn('ignore_me',text)
        self.assertLess(len(text),200)
        self.assertEqual(reconciler.order_reference_ids({'body':text}),{'TEST1042'})

    def test_html_order_metadata_and_plain_text_remain_readable(self):
        for label in ('Order: # TEST1042','Order No.: TEST1042','Order number is TEST1042','Order #TEST1042'):
            self.assertEqual(reconciler.order_reference_ids({'subject':label}),{'TEST1042'})
        msg=reconciler.email.message_from_string('Content-Type: text/plain; charset=utf-8\n\nOrder TEST2042 contains one relay.')
        self.assertIn('one relay',reconciler.text_of(msg))
        msg=reconciler.email.message_from_string('Content-Type: text/html; charset=utf-8\n\n<p>Ready</p><img alt><img alt="Smart relay">')
        self.assertIn('Smart relay',reconciler.text_of(msg))

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

    def test_sensor_exposes_unconfirmed_date_as_context_not_legacy_deadline(self):
        sensor_path=ROOT/"homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py"
        with patch.dict(sys.modules,{"lifeos_pa_user_state":state}):
            spec=importlib.util.spec_from_file_location("commitment_sensor",sensor_path);sensor=importlib.util.module_from_spec(spec);spec.loader.exec_module(sensor)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"view.json";task={"id":"role","title":"Apply for a role","status":"OPEN","confirmation_required":"optional_commitment","due_date":"2026-07-20"}
            path.write_text(json.dumps(payload(task)));out=io.StringIO()
            with patch.object(sensor,"TASKS",path),patch.object(sensor,"read_user_state",return_value={"obligations":{}}),contextlib.redirect_stdout(out):sensor.main()
            view=json.loads(out.getvalue());item=view["items"][0]
            self.assertEqual(view["questions"],1);self.assertEqual(item["due_date"],None)
            self.assertEqual(item["extracted_date"],"2026-07-20")
            self.assertEqual(item["original_title"],"Apply for a role")
            self.assertTrue(item["title"].startswith("Confirm whether to track:"))
            self.assertEqual(view["overdue"],0)

    def test_sensor_keeps_verified_deadline_when_email_requires_review(self):
        sensor_path=ROOT/"homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py"
        with patch.dict(sys.modules,{"lifeos_pa_user_state":state}):
            spec=importlib.util.spec_from_file_location("verified_date_sensor",sensor_path);sensor=importlib.util.module_from_spec(spec);spec.loader.exec_module(sensor)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"view.json";task={"id":"policy","title":"Check policy","status":"OPEN","confirmation_required":"source_unavailable","due_date":"2026-07-20","due_date_source":"paperless_policy"}
            path.write_text(json.dumps(payload(task)));out=io.StringIO()
            with patch.object(sensor,"TASKS",path),patch.object(sensor,"read_user_state",return_value={"obligations":{}}),contextlib.redirect_stdout(out):sensor.main()
            item=json.loads(out.getvalue())["items"][0]
            self.assertTrue(item["date_verified"])
            self.assertEqual(item["due_date"],"2026-07-20")

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

