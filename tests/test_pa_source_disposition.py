"""Synthetic source disposition and durable legacy correction contracts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'homelab/live/home/joshan/automation')]
from governor.pa_source_disposition import non_obligation_kind
from governor import pa_user_state as user_state
import lifeos_task_reconciler as reconciler


def message(body,subject='Synthetic update',**kw):
    return {'message_id':'<source@example.test>','subject':subject,'body':body,**kw}


def task():
    return {'id':'synthetic-task','title':'Synthetic task','status':'OPEN','source_message_ids':['<source@example.test>']}


class SourceDispositionTests(unittest.TestCase):
    def test_offer_expiry_is_not_personal_deadline(self):
        source=message('Claim 25% off with promo code. Offer ends tomorrow. Unsubscribe.')
        self.assertEqual(non_obligation_kind(source),'marketing_offer')
        with patch.object(reconciler.ai_broker,'_ollama',side_effect=AssertionError('no inference needed')):
            decision=reconciler.classify(source)
        self.assertFalse(decision['actionable']);self.assertIsNone(decision['due_date'])

    def test_html_campaign_wording_is_normalised(self):
        self.assertEqual(non_obligation_kind(message('<p>Claim <b>25% off</b></p><p>Unsubscribe</p>')),'marketing_offer')

    def test_routine_tracking_is_information_not_completion(self):
        for text in ['Your parcel is out for delivery. Track your parcel.','Your order has been delivered.','Your package has shipped.','Delivery status update.']:
            with self.subTest(text=text):self.assertEqual(non_obligation_kind(message(text)),'routine_delivery')
        decision=reconciler.classify(message('Your order has been delivered.'))
        self.assertFalse(decision['actionable']);self.assertEqual(decision['status'],'NONE')

    def test_delivery_exceptions_and_required_actions_are_preserved(self):
        for text in ['Delivery update. Please pay the customs fee.','Track your parcel. Delivery failed. Reschedule.','Your parcel is out for delivery. Signature required.','Delivery update. Your delivery is delayed.']:
            with self.subTest(text=text):self.assertIsNone(non_obligation_kind(message(text)))

    def test_optional_invitation_requires_positive_source_evidence(self):
        source=message('Applications are now open. Apply to become a trustee. Unsubscribe.')
        self.assertEqual(non_obligation_kind(source),'optional_opportunity')
        self.assertIsNone(non_obligation_kind(message('Please review the attached board papers.')))
        self.assertIsNone(non_obligation_kind(message('Apply to become a trustee.'))) # no bulk/optional evidence

    def test_accepted_application_and_mandatory_requests_are_preserved(self):
        for text in ['Applications are open. Your application has been received. Unsubscribe.','Vacancy update. Application reference ABC. Please upload proof.','Special offer: please confirm your appointment.','Your claim requires your response. Claim your discount.']:
            with self.subTest(text=text):self.assertIsNone(non_obligation_kind(message(text)))

    def test_campaign_footers_cannot_hide_real_commitments_in_same_source(self):
        sources=[
            message('Your invoice is due tomorrow. Save 25% off your next order. Unsubscribe.'),
            message('Your current policy renews next week. Special offer: save 25% off. Unsubscribe.'),
            message('Your appointment is tomorrow. Track your parcel. Unsubscribe.'),
            message('You must apply by Friday to keep your entitlement. Applications are open. Unsubscribe.'),
            message('Please track your parcel and investigate the problem.'),
            message('Use promo code to accept the offer.',subject='Settlement offer for your complaint'),
            message('Thank you for applying. Explore more job opportunities. Unsubscribe.'),
            message('Your order has shipped. Return your old device by Friday.'),
            message('Please settle your invoice by Friday. Special offer: 25% off your next order. Unsubscribe.',subject='Payment reminder'),
            message('Please renew your policy by Friday. Special offer: 25% off travel cover. Unsubscribe.',subject='Renew your policy'),
            message('Please respond by Friday with identification. Apply now to more job opportunities. Unsubscribe.',subject='Proof requested for your application'),
        ]
        for source in sources:
            with self.subTest(subject=source['subject'],body=source['body']):self.assertIsNone(non_obligation_kind(source))

    def test_mixed_or_missing_sources_never_create_a_hold(self):
        row=task();row['source_message_ids'].append('<required@example.test>')
        sources={'<source@example.test>':message('Claim 25% off. Unsubscribe.')}
        self.assertFalse(reconciler.hold_source_non_obligation(row,sources,{}))
        sources['<required@example.test>']=message('Please provide identification.')
        self.assertFalse(reconciler.hold_source_non_obligation(row,sources,{}))
        self.assertNotIn('obligation_suppressed',row)

    def test_replay_lookup_miss_retains_hold_but_real_new_action_releases_it(self):
        row=task();sources={'<source@example.test>':message('Claim 25% off. Unsubscribe.')}
        self.assertTrue(reconciler.hold_source_non_obligation(row,sources,{}))
        self.assertFalse(reconciler.hold_source_non_obligation(row,{},{}))
        self.assertEqual(row['obligation_suppressed'],'marketing_offer')
        self.assertFalse(reconciler.hold_source_non_obligation(row,{'<source@example.test>':message('Please provide identification.')},{}))
        self.assertNotIn('obligation_suppressed',row)

    def test_manual_tracking_and_existing_user_decisions_survive(self):
        row=task();source={'<source@example.test>':message('Claim 25% off. Unsubscribe.')}
        for entry in [{'status_override':'OPEN'},{'due_date_override':'2026-11-01'},{'severity_override':'high'}]:
            self.assertFalse(reconciler.hold_source_non_obligation(row,source,{'obligations':{row['id']:entry}}))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            row['obligation_suppressed']='marketing_offer'
            payload={'schema':'lifeos_tasks_v3','generated_time':1793180000,'tasks':[],'resolved':[],'informational':[row]}
            user_state.mutate_action(row['id'],'comment',note='Keep this context',path=path)
            view=user_state.apply_user_state(payload,user_state.read_user_state(path))
            self.assertEqual(view['attention']['counts']['needs_me'],0)
            user_state.mutate_action(row['id'],'reopen',path=path)
            view=user_state.apply_user_state(payload,user_state.read_user_state(path))
            self.assertEqual(view['attention']['counts']['needs_me'],1)
            self.assertEqual(view['informational'],[])
            self.assertEqual(view['tasks'][0]['user_comments'][0]['text'],'Keep this context')
            self.assertEqual(user_state.apply_user_state(view,user_state.read_user_state(path))['tasks'],view['tasks'])

    def test_user_closed_sources_stay_in_closed_view_after_machine_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path=Path(directory)/'state.json';task_path=Path(directory)/'tasks.json'
            for action in ('close','dismiss'):
                row={**task(),'status':'DONE' if action=='close' else 'DISMISSED','machine_status':'OPEN','status_source':'user'}
                user_state.mutate_action(row['id'],action,path=state_path)
                task_path.write_text(json.dumps({'tasks':[],'resolved':[row],'informational':[]}))
                with patch.object(reconciler,'STATE',task_path):loaded=reconciler.load_previous()[row['id']]
                overlay=user_state.read_user_state(state_path)
                self.assertFalse(reconciler.hold_source_non_obligation(loaded,{'<source@example.test>':message('Claim 25% off. Unsubscribe.')},overlay))
                view=user_state.apply_user_state({'schema':'lifeos_tasks_v3','tasks':[loaded],'resolved':[]},overlay)
                self.assertEqual(view['tasks'],[]);self.assertEqual(view['informational'],[])
                self.assertEqual(view['resolved'][0]['status'],row['status'])
                self.assertEqual(user_state.read_user_state(state_path),overlay)

    def test_old_deadline_does_not_close_a_genuine_obligation(self):
        row={**task(),'due_date':'2026-07-20'}
        self.assertFalse(reconciler.hold_source_non_obligation(row,{'<source@example.test>':message('Please submit the evidence we requested.')},{}))
        self.assertEqual(row['status'],'OPEN')

if __name__=='__main__':unittest.main()
