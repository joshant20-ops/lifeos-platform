"""Invented legacy-source replay and receipt/grouping contracts; no private mail."""
import copy
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'homelab/live/home/joshan/automation'))
import lifeos_task_reconciler as reconciler
from governor import pa_source_disposition as policy
from tests.test_pa_projects import sensor


def mail(mid='receipt', **kw):
    return {'message_id':f'<{mid}@example.test>','from':'Example Motors <orders@motors.example.test>',
            'subject':'Thank You for Your Order', 'body':'Thank you for your order. Your order number is TEST2042.',
            'date':'Fri, 25 Sep 2026 14:29:34 +0000', **kw}


def row(mid='receipt', **kw):
    return {'id':mid,'status':'OPEN','title':'Example Motors order','topic':'Order Confirmation','counterparty':'Example Motors',
            'source_message_ids':[f'<{mid}@example.test>'],'email_message_id':f'<{mid}@example.test>',**kw}


class LegacyEvidenceTests(unittest.TestCase):
    def test_acknowledgement_is_information_but_requests_win(self):
        self.assertEqual(policy.non_obligation_kind(mail()),'order_acknowledgement')
        for request in ['Please upload your identity document.', 'Complete your delivery details.', 'Your payment is due.', 'You must sign the agreement.', 'Collect your package by Friday.']:
            self.assertIsNone(policy.non_obligation_kind(mail(body=mail()['body']+' '+request)))
        self.assertIsNone(policy.non_obligation_kind(mail(body='See the account page.')))
        self.assertIsNone(policy.non_obligation_kind(mail(subject='Your order requires attention',body='Please verify your address.')))

    def test_legacy_history_rebuilds_from_exact_source_without_changing_task_state(self):
        item=row(due_date='2020-01-01',severity='high')
        original=copy.deepcopy(item)
        tasks={'receipt':item};sources={mail()['message_id']:mail()}
        self.assertEqual(reconciler.backfill_verified_source_history(tasks,sources),1)
        self.assertEqual(reconciler.backfill_verified_source_history(tasks,sources),0)
        self.assertEqual(item['status'],original['status']);self.assertEqual(item['due_date'],original['due_date'])
        self.assertEqual(item['severity'],original['severity']);self.assertEqual(len(item['timeline_events']),1)
        event=item['timeline_events'][0]
        self.assertTrue(event['evidence_only']);self.assertEqual(event['event_kind'],'information')
        self.assertEqual(event['time_source'],'email_date');self.assertNotIn('body',event)
        self.assertEqual(item['verified_order_refs'],['TEST2042'])

    def test_identity_mismatch_and_missing_dates_never_fabricate_history(self):
        item=row();sources={mail()['message_id']:mail('other')}
        self.assertEqual(reconciler.backfill_verified_source_history({'receipt':item},sources),0)
        self.assertNotIn('timeline_events',item)
        sources={mail()['message_id']:mail(date='invalid')}
        reconciler.backfill_verified_source_history({'receipt':item},sources)
        self.assertEqual(item['timeline_events'][0]['observed_at'],0)
        self.assertEqual(item['timeline_events'][0]['time_source'],'unknown')

    def test_hold_requires_all_sources_and_preserves_user_overrides(self):
        item=row();sources={mail()['message_id']:mail()}
        self.assertTrue(reconciler.hold_source_non_obligation(item,sources,{'obligations':{}}))
        self.assertEqual(item['obligation_suppressed'],'order_acknowledgement')
        self.assertFalse(reconciler.hold_source_non_obligation(item,sources,{'obligations':{'receipt':{'status_override':'OPEN'}}}))
        self.assertNotIn('obligation_suppressed',item)
        item['source_message_ids'].append('<missing@example.test>')
        self.assertFalse(reconciler.hold_source_non_obligation(item,sources,{'obligations':{}}))
        self.assertNotIn('obligation_suppressed',item)

    def test_same_supplier_different_senders_share_exact_order_not_generic_topic(self):
        a,b=row('receipt'),row('assignment',status='WAITING',reason='Await vehicle assignment')
        a.update(case_reference_ids=['BILLING-OTHER'])
        b.update(case_reference_ids=['DELIVERY-OTHER'],topic='Vehicle assignment')
        messages=[mail(),mail('assignment',**{'from':'Delivery team <delivery@motors.example.test>','subject':'Assignment update','body':'We will email when allocation is ready. Reference TEST2042.'})]
        for task,source in zip([a,b],messages):
            task['source_context']={'message_id':source['message_id'],'sender':source['from']}
        sources={source['message_id']:source for source in messages};tasks={a['id']:a,b['id']:b}
        reconciler.backfill_verified_source_history(tasks,sources)
        reconciler.backfill_shared_order_references(tasks,sources)
        reconciler.hold_source_non_obligation(a,sources,{'obligations':{}})
        projects=sensor.derive_projects([a,b])['projects']
        self.assertEqual(len(projects),1);self.assertEqual(projects[0]['attention'],'WAITING')
        self.assertEqual(projects[0]['next_action'],[]);self.assertEqual(len(projects[0]['timeline']),2)
        self.assertEqual(projects[0]['name'],'Example Motors order')
        b['verified_order_refs']=['DIFFERENT2043']
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)

    def test_existing_lifecycle_event_is_not_replaced_by_metadata_backfill(self):
        item=row(timeline_events=[{'message_id':mail()['message_id'],'title':'Submit identity details','status':'OPEN','event_kind':'obligation','observed_at':100}])
        before=copy.deepcopy(item['timeline_events'])
        reconciler.backfill_verified_source_history({'receipt':item},{mail()['message_id']:mail()})
        self.assertEqual(item['timeline_events'],before)

if __name__=='__main__':unittest.main()
