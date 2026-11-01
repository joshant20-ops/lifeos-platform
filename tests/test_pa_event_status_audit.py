"""Synthetic contracts for read-only event evidence; no real source data."""
import importlib.util
from datetime import date
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('event_audit',Path(__file__).resolve().parents[1]/'scripts/audit-pa-event-status.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class EventAuditTests(unittest.TestCase):
    def test_outcome_audit_counts_shapes_without_exposing_or_mutating_sources(self):
        import copy
        a={'id':'a','title':'Check Synthetic identity','status':'OPEN','topic':'Identity', 'source_message_ids':['<a@example.test>'],'verified_order_refs':['DEMO42'], 'updated_from_email':'Wed, 28 Oct 2026 12:00:00 +0000'}
        b={'id':'b','title':'Synthetic finance','status':'DONE','source_message_ids':['<b@example.test>'],'verified_order_refs':['DEMO42'],'timeline_events':[{'message_id':'<b@example.test>','title':'Identity verification completed','date':'Thu, 29 Oct 2026 12:00:00 +0000'}]}
        payload={'tasks':[a], 'resolved':[b]}; before=copy.deepcopy(payload)
        counts=audit.outcome_counts(payload,'Synthetic')
        self.assertEqual(counts['SAME_ORDER_PAIRS'],1)
        self.assertEqual(counts['IDENTITY_LATER_CANDIDATES'],1)
        self.assertEqual(payload,before)
        self.assertTrue(all(isinstance(k,str) and type(v) is int for k,v in counts.items()))
        self.assertNotIn('DEMO42',str(counts));self.assertNotIn('example.test',str(counts))
    def test_invalid_stale_or_wrong_schema_cannot_look_like_zero_candidates(self):
        valid={'schema':'lifeos_tasks_v3','generated_time':100000,'tasks':[],'resolved':[],'informational':[]}
        self.assertIs(audit.validate_payload(valid,100001),valid)
        for payload in [{},[],{**valid,'schema':'other'},{**valid,'generated_time':1},{**valid,'generated_time':100002},{**valid,'tasks':{}},{**valid,'informational':None}]:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):audit.validate_payload(payload,100001)

    def test_review_flags_and_unverified_actions_are_counted_separately(self):
        base={'id':'synthetic','title':'Directions hearing','status':'OPEN','due_date':'2026-09-23'}
        for update,key in [({},'UNVERIFIED_PAST_ACTIONS'),({'confirmation_required':'source_unavailable'},'SOURCE_REVIEW_QUESTIONS'),({'confirmation_required':'past_event_status'},'PAST_EVENT_QUESTIONS')]:
            counts=audit.event_counts({'tasks':[{**base,**update}]},date(2026,10,28))
            if key:self.assertEqual(counts[key],1)

    def test_owner_and_verified_dates_are_not_reported_as_unknown_actions(self):
        base={'id':'synthetic','title':'Directions hearing','status':'OPEN','due_date':'2026-09-23'}
        for update in [{'due_date_source':'user'},{'due_date_source':'paperless_policy'},{'user_tracking':True},{'status_source':'user'}]:
            self.assertEqual(audit.event_counts({'tasks':[{**base,**update}]},date(2026,10,28))['UNVERIFIED_PAST_ACTIONS'],0)

    def test_required_source_action_is_a_warning_inside_the_past_event_question(self):
        row={'id':'synthetic','title':'Directions hearing','status':'OPEN','due_date':'2026-09-23','confirmation_required':'past_event_status','source_response_required':True}
        counts=audit.event_counts({'tasks':[row]},date(2026,10,28))
        self.assertEqual(counts['PAST_EVENT_QUESTIONS'],1)
        self.assertEqual(counts['PAST_EVENT_RESPONSE_WARNINGS'],1)
        self.assertEqual(counts['UNVERIFIED_PAST_ACTIONS'],0)

    def test_invoice_or_separate_deadline_stays_an_action_candidate(self):
        base={'id':'synthetic','title':'Directions hearing','status':'OPEN','due_date':'2026-09-23'}
        for checks,key in [
            ({'sources':1,'event_schedules':0,'event_date_matches':0},None),
            ({'sources':1,'event_schedules':1,'event_date_matches':0,'event_action_deadlines':1},'SCHEDULED_SOURCE_DATE_MISMATCH_ACTIONS'),
        ]:
            counts=audit.event_counts({'tasks':[{**base,'source_disposition_checks':checks}]},date(2026,10,28))
            self.assertEqual(counts['UNVERIFIED_PAST_ACTIONS'],1)
            if key:self.assertEqual(counts[key],1)
