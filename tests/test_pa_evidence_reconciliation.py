"""General reconciliation fixtures, invented source identities only."""
import copy
import unittest
from governor import pa_evidence_reconciliation as engine
from tests.test_pa_legacy_project_evidence import reconciler


def matter(mid, action='Repair boiler', issuer='Example Maintenance', state='OPEN', day=20, refs=None):
    return {'id':mid, 'title':action, 'topic':action, 'counterparty':issuer, 'status':state,
            'source':'gmail', 'case_reference_ids':['DEMO42'] if refs is None else refs,
            'source_message_ids':[f'<{mid}@example.test>'], 'email_message_id':f'<{mid}@example.test>',
            'updated_from_email':f'{day} Oct 2026 12:00:00 +0000', 'reason':'Synthetic accepted state'}


def observation(mid, action, state, issuer='Example Maintenance', day=21, refs=None, **kw):
    return {'message_id':f'<{mid}@example.test>', 'title':'Synthetic source update', 'status':state,
            'event_kind':'obligation', 'date':f'{day} Oct 2026 12:00:00 +0000',
            'obligation_scope':engine.scope(issuer, action, ['DEMO42'] if refs is None else refs), **kw}


class GeneralEvidenceTests(unittest.TestCase):
    def decision(self, rows, mid='request', **kw):
        return next(d for d in engine.reconcile(rows, **kw)['decisions'] if d['matter_id']==mid)

    def test_one_policy_resolves_arbitrary_categories_without_topic_rules(self):
        for action in ('Receive bookshelf', 'Repair boiler', 'Confirm wedding booking', 'Renew insurance policy',
                       'Submit tenancy documents', 'Approve finance', 'Register training course'):
            a=matter('request',action=action)
            b=matter('resolved',action=action,state='DONE',day=21)
            for row in (a,b):row['obligation_key']='accepted-logical-obligation'
            decision=self.decision([a,b])
            self.assertEqual(decision['proposed_state'],'DONE',action)
            self.assertEqual(decision['support'][0]['relationship'],'accepted_obligation_identity')
            self.assertEqual(decision['support'][0]['source_id'],'<resolved@example.test>')

    def test_approval_never_closes_identity_or_signing_in_same_outcome(self):
        rows=[matter('approval','Approve finance',state='DONE',day=21),
              matter('identity','Verify identity'),matter('signing','Sign agreement')]
        for row in rows:row['user_project']={'anchor_id':'purchase'}
        for mid in ('identity','signing'):
            self.assertIsNone(self.decision(rows,mid)['proposed_state'])

    def test_newer_waiting_then_action_use_identical_policy(self):
        a=matter('request')
        b=matter('update',state='WAITING',day=21)
        for row in (a,b):row['obligation_key']='accepted-logical-obligation'
        self.assertEqual(self.decision([a,b])['proposed_state'],'WAITING')
        a.update(status='WAITING',updated_from_email=b['updated_from_email'])
        b.update(status='OPEN',updated_from_email='22 Oct 2026 12:00:00 +0000')
        self.assertEqual(self.decision([a,b])['proposed_state'],'OPEN')

    def test_information_and_evidence_backfill_create_no_action_or_completion(self):
        a=matter('request',state='WAITING')
        a['source_message_ids'].append('<info@example.test>')
        for update in (observation('info',a['topic'],'NONE'), observation('info',a['topic'],'DONE',evidence_only=True),
                       observation('info',a['topic'],'OPEN',event_kind='information')):
            a['timeline_events']=[update]
            self.assertIsNone(self.decision([a])['proposed_state'])

    def test_explicit_scoped_resolution_can_be_in_an_informational_message(self):
        a=matter('request');a['source_message_ids'].append('<resolved@example.test>')
        a['timeline_events']=[observation('resolved',a['topic'],'DONE',event_kind='information')]
        self.assertEqual(self.decision([a])['proposed_state'],'DONE')

    def test_same_company_or_owner_project_without_resource_identity_does_not_join(self):
        a=matter('request',refs=[]);b=matter('other',state='DONE',day=21,refs=[])
        for row in (a,b):row['user_project']={'anchor_id':'same-outcome'}
        self.assertIsNone(self.decision([a,b])['proposed_state'])
        a['case_reference_ids']=['DEMO42'];b['case_reference_ids']=['OTHER43']
        self.assertIsNone(self.decision([a,b])['proposed_state'])

    def test_provider_specific_checks_are_not_interchangeable(self):
        a=matter('request','Verify identity',issuer='Retailer')
        b=matter('other','Verify identity',issuer='Lender',state='DONE',day=21)
        self.assertIsNone(self.decision([a,b])['proposed_state'])

    def test_equal_time_disagreement_is_uncertainty_not_arbitrary_tiebreak(self):
        rows=[matter('request'),matter('a',state='WAITING',day=21),matter('b',state='DONE',day=21)]
        decision=self.decision(rows)
        self.assertIsNone(decision['proposed_state'])
        self.assertIn('conflicting_observations',decision['uncertainties'])
        self.assertEqual(engine.reconcile(rows),engine.reconcile(list(reversed(rows))))

    def test_dates_age_and_missing_source_never_establish_completion(self):
        a=matter('request');a['due_date']='2020-01-01'
        self.assertIsNone(self.decision([a])['proposed_state'])
        b=matter('later',state='DONE',day=21)
        for row in (a,b):row['obligation_key']='accepted-logical-obligation'
        for value in ('', 'invalid', '21 Oct 2026 12:00:00'):
            b['updated_from_email']=value
            self.assertIsNone(self.decision([a,b])['proposed_state'])
        b['updated_from_email']='21 Oct 2026 12:00:00 +0000'
        decision=self.decision([a,b],available_sources={'<request@example.test>'})
        self.assertIsNone(decision['proposed_state']);self.assertIn('source_unavailable',decision['uncertainties'])

    def test_overrides_remain_authoritative_and_user_done_is_not_a_source_claim(self):
        a=matter('request');b=matter('later',state='DONE',day=21)
        for row in (a,b):row['obligation_key']='accepted-logical-obligation'
        state={'obligations':{'request':{'status_override':'WAITING'}}}
        self.assertEqual(self.decision([a,b],user_state=state)['reason'],'user_override')
        b['status_source']='user'
        self.assertIsNone(self.decision([a,b])['proposed_state'])
        b['machine_status']='OPEN'
        a['status']='WAITING'
        self.assertEqual(self.decision([a,b])['proposed_state'],'OPEN')

    def test_unscoped_history_and_unknown_shadow_results_never_become_facts(self):
        a=matter('request');a['source_message_ids'].append('<legacy@example.test>')
        update=observation('legacy',a['topic'],'DONE');update.pop('obligation_scope')
        a['timeline_events']=[update]
        a['emailops_shadow']={'lifecycle':'DONE','promotion_ready':False}
        result=engine.reconcile([a])
        self.assertEqual(result['counts']['unscoped_events'],1)
        self.assertIsNone(result['decisions'][0]['proposed_state'])

    def test_requotes_deduplicate_and_rebuild_cannot_mutate_tasks(self):
        a=matter('request');a['source_message_ids'].append('<later@example.test>')
        update=observation('later',a['topic'],'WAITING')
        a['timeline_events']=[update,copy.deepcopy(update)]
        before=copy.deepcopy(a)
        result=engine.reconcile([a])
        self.assertEqual(a,before);self.assertEqual(result,engine.reconcile([a]))
        self.assertEqual(len([f for f in result['observations'] if f['source_id']=='<later@example.test>']),1)

    def test_publisher_applies_proven_state_and_preserves_backing_and_provenance(self):
        a=matter('request');b=matter('later',state='DONE',day=21)
        for row in (a,b):row['obligation_key']='accepted-logical-obligation'
        tasks={r['id']:r for r in (a,b)}
        sources={r['email_message_id']:{'message_id':r['email_message_id'],'date':r['updated_from_email'],
                   'from':'Example Maintenance <updates@example.test>','subject':'Synthetic accepted update','body':'Synthetic body'} for r in (a,b)}
        result=reconciler.reconcile_accepted_observations(tasks,sources,{'obligations':{}})
        self.assertEqual(result['counts']['applied_changes'],1)
        self.assertEqual(a['status'],'DONE');self.assertEqual(a['machine_status'],'DONE')
        self.assertEqual(a['completion_previous_status'],'OPEN')
        self.assertEqual(a['completion_evidence'][0]['method'],'accepted_observation')
        self.assertEqual(a['email_message_id'],'<later@example.test>')
        self.assertEqual(a['state_reconciliation_backing']['email_message_id'],'<request@example.test>')
        self.assertEqual(reconciler.reconcile_accepted_observations(tasks,sources,{})['counts']['applied_changes'],0)

    def test_repeated_occurrences_do_not_close_or_reopen_from_policy_reference_alone(self):
        a=matter('request','Renew insurance policy',day=20)
        b=matter('next-year','Renew insurance policy',state='DONE',day=21)
        decision=self.decision([a,b])
        self.assertIsNone(decision['proposed_state'])
        self.assertIn('obligation_identity_ambiguous',decision['uncertainties'])

    def test_scope_validation_does_not_create_a_partial_identity(self):
        self.assertIsNone(engine.scope('', 'Repair boiler'))
        self.assertIsNone(engine.scope('Example', 'Repair boiler', 'not-a-reference-list'))
        self.assertIsNone(engine.scope('Example', 'x'*401))


if __name__=='__main__':unittest.main()
