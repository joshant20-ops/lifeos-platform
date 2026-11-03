"""Cloud-safe project contracts: invented sources only, no runtime data."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py'
spec = importlib.util.spec_from_file_location('projects_sensor', PATH)
sensor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sensor)


def matter(name='order', status='WAITING', **kw):
    return dict(id=name, title='Collect synthetic vehicle', topic='Vehicle purchase',
                counterparty='Synthetic Motors', status=status,
                case_reference_ids=['CASE-DEMO-42'], source_message_ids=['<'+name+'@example.test>'], **kw)


def event(mid, title='Vehicle allocation pending', status='WAITING', kind='obligation', observed=100):
    return dict(message_id='<'+mid+'@example.test>', title=title, status=status,
                event_kind=kind, observed_at=observed, date='Wed, 28 Oct 2026 12:00:00 +0000')


class ProjectsTests(unittest.TestCase):
    def shipping(self, mid, party, tracking='DEMO1234567890', order=None):
        row = matter(mid, timeline_events=[{**event(mid, 'Parcel update', 'NONE', 'information'),
                                          'correlation_refs': {'tracking': [tracking]}}])
        row.update(counterparty=party, topic='Delivery ' + mid, case_reference_ids=[],
                   verified_order_refs=[order] if order else [])
        return row

    def test_reply_ancestry_groups_different_actions_and_companies(self):
        a = matter('booking', timeline_events=[event('booking')])
        b = matter('payment', timeline_events=[event('payment')])
        a.update(case_reference_ids=[], counterparty='Example Venue', topic='Reserve room',
                 thread_root_id='<booking@example.test>')
        b.update(case_reference_ids=[], counterparty='Example Agent', topic='Pay deposit',
                 thread_root_id='<booking@example.test>')
        original = copy.deepcopy([a, b])
        result = sensor.derive_projects([a, b])
        self.assertEqual(len(result['projects']), 1)
        project = result['projects'][0]
        self.assertEqual(project['provenance'][0]['rule'], 'accepted_conversation_outcome')
        self.assertEqual(project['provenance'][1]['conversation_evidence'][0]['root_source_message_id'], '<booking@example.test>')
        self.assertEqual(sensor.derive_projects([b, a]), result)
        self.assertEqual([a, b], original)

    def test_reply_ancestry_requires_retained_root_and_respects_owner(self):
        a, b = matter('a'), matter('b')
        for row in (a, b):
            row.update(case_reference_ids=[], topic=row['id'], thread_root_id='<gone@example.test>')
        self.assertEqual(len(sensor.derive_projects([a, b])['projects']), 2)
        for row in (a, b): row['thread_root_id'] = '<a@example.test>'
        a['user_project'] = {'anchor_id': 'a', 'source': 'user', 'outcome': 'Finish booking'}
        self.assertEqual(len(sensor.derive_projects([a, b])['projects']), 2)

    def test_reply_chain_conflicting_jobs_vetoes_transitive_component(self):
        rows = [self.shipping('shop1', 'Shop', order='ORDER42'),
                self.shipping('agent', 'Agent'), self.shipping('shop2', 'Shop', order='ORDER43')]
        for row in rows: row['thread_root_id'] = '<shop1@example.test>'
        self.assertEqual(len(sensor.derive_projects(rows)['projects']), 3)
        a, b = matter('a'), matter('b')
        a['case_reference_ids'], b['case_reference_ids'] = ['CASE42'], ['CASE43']
        for row in (a, b): row['thread_root_id'] = '<a@example.test>'
        result = sensor.derive_projects([a, b])['projects']
        self.assertEqual(len(result), 2)
        self.assertTrue(all('Ambiguous correlation evidence; kept separate' in p['uncertainties'] for p in result))

    def test_split_parcels_join_one_order_but_cannot_bridge_two_orders(self):
        a = self.shipping('shop', 'Shop', order='ORDER42')
        a['timeline_events'][0]['correlation_refs']['tracking'].append('SECOND1234567890')
        b = self.shipping('parcel1', 'Carrier')
        c = self.shipping('parcel2', 'Carrier', tracking='SECOND1234567890')
        rows = [a, b, c]
        self.assertEqual(len(sensor.derive_projects(rows)['projects']), 1)
        other = self.shipping('other', 'Shop', tracking='SECOND1234567890', order='ORDER43')
        self.assertEqual(len(sensor.derive_projects(rows + [other])['projects']), 4)

    def test_same_subject_or_source_alone_does_not_invent_a_job(self):
        a, b = matter('a'), matter('b')
        a.update(case_reference_ids=[], topic='Repair oven')
        b.update(case_reference_ids=[], topic='Renew insurance', source_message_ids=a['source_message_ids'])
        self.assertEqual(len(sensor.derive_projects([a, b])['projects']), 2)

    def test_retailer_carrier_outcome_crosses_company_boundary(self):
        retailer = self.shipping('dispatch', 'Example Shop', order='DEMOORDER42')
        carrier = self.shipping('carrier', 'Example Courier')
        original = copy.deepcopy([retailer, carrier])
        p = self.project([retailer, carrier])
        self.assertEqual(len(sensor.derive_projects([retailer, carrier])['projects']), 1)
        self.assertEqual(p['provenance'][0]['rule'], 'verified_cross_company_tracking')
        self.assertEqual(len(p['timeline']), 1)
        self.assertEqual(len(p['timeline'][0]['source_message_ids']), 2)
        self.assertEqual(sensor.derive_projects([carrier, retailer]), sensor.derive_projects([retailer, carrier]))
        self.assertEqual([retailer, carrier], original)

    def test_tracking_collision_and_ambiguous_bridge_stay_separate(self):
        a = self.shipping('a', 'Shop', order='ORDER42')
        b = self.shipping('b', 'Shop', order='ORDER43')
        carrier = self.shipping('carrier', 'Courier')
        projects = sensor.derive_projects([a, b, carrier])['projects']
        self.assertEqual(len(projects), 3)
        self.assertTrue(all('Ambiguous correlation evidence; kept separate' in p['uncertainties'] for p in projects))
        carrier['timeline_events'][0]['correlation_refs']['tracking'].append('OTHER1234567890')
        self.assertEqual(len(sensor.derive_projects([a, carrier])['projects']), 2)

    def test_unverified_tracking_and_pinned_owner_membership_do_not_expand(self):
        a, b = self.shipping('a', 'Shop'), self.shipping('b', 'Courier')
        b['timeline_events'][0]['message_id'] = '<missing@example.test>'
        self.assertEqual(len(sensor.derive_projects([a, b])['projects']), 2)
        b['timeline_events'][0]['message_id'] = b['source_message_ids'][0]
        a['user_project'] = {'anchor_id': 'a', 'source': 'user', 'outcome': 'Receive example purchase'}
        self.assertEqual(len(sensor.derive_projects([a, b])['projects']), 2)

    def test_verified_single_source_starts_timeline_without_invented_lifecycle(self):
        row = matter(source_context={'message_id': '<order@example.test>', 'subject': 'Example receipt',
                                     'sent_at': 'Wed, 28 Oct 2026 12:00:00 +0000'})
        original = copy.deepcopy(row)
        p = self.project([row])
        self.assertTrue(p['timeline'][0]['evidence_only'])
        self.assertEqual(p['timeline'][0]['time_source'], 'email_date')
        self.assertEqual(p['attention'], 'WAITING')
        self.assertEqual(row, original)
        row['source_context']['sent_at'] = 'unknown'
        self.assertEqual(self.project([row])['timeline'][0]['observed_at'], 0)

    def test_shared_source_retains_every_matter_relationship(self):
        a, b = matter('a'), matter('b')
        b['source_message_ids'] = a['source_message_ids']
        a['timeline_events'] = [event('a')]
        b['timeline_events'] = [event('a')]
        self.assertEqual(self.project([a, b])['timeline'][0]['matter_ids'], ['a', 'b'])
        a['timeline_events'] = []
        a['source_context'] = {'message_id': '<a@example.test>', 'subject': 'Metadata fallback'}
        b['timeline_events'] = [event('a', 'Identity check requested', 'OPEN')]
        timeline = self.project([a, b])['timeline']
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]['title'], 'Identity check requested')
        self.assertFalse(timeline[0]['evidence_only'])
        self.assertEqual(timeline[0]['matter_ids'], ['a', 'b'])

    def project(self, rows):
        return sensor.derive_projects(rows)['projects'][0]

    def test_multithread_sources_one_project_consolidated_timeline(self):
        a = matter('first', timeline_events=[event('first')])
        b = matter('second', timeline_events=[event('second')])
        p = self.project([a,b])
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),1)
        self.assertEqual(p['matter_ids'],['first','second'])
        self.assertEqual(len(p['timeline']),1)
        self.assertEqual(len(p['timeline'][0]['source_message_ids']),2)
        self.assertEqual(len(p['provenance']),2)

    def test_information_does_not_unblock_waiting(self):
        row = matter(reason='Waiting for manufacturer to assign a vehicle',
                     timeline_events=[event('order', 'Delivery estimate updated', 'NONE', 'information')])
        p = self.project([row])
        self.assertEqual(p['attention'],'WAITING')
        self.assertEqual(p['next_action'],[])
        self.assertIn('assign a vehicle',p['waiting_on'][0])
        self.assertEqual(p['timeline'][0]['event_kind'],'information')

    def test_later_accepted_source_unblocks_action(self):
        row = matter(status='OPEN', reason='Complete identity check',
                     timeline_events=[event('order','Identity check requested','OPEN')])
        p = self.project([row])
        self.assertEqual(p['attention'],'ACTION')
        self.assertEqual(p['next_action'],['Complete identity check'])

    def test_same_company_different_matter_and_conflicting_refs_do_not_merge(self):
        a,b = matter('purchase'),matter('service')
        b['topic']='Service booking';b['case_reference_ids']=['CASE-OTHER-43']
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)
        b['topic']=a['topic']
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)
        a['case_reference_ids']=[]
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)
        b['case_reference_ids']=[]
        b['topic']='Service booking'
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)

    def test_duplicate_events_and_requotes_do_not_duplicate_updates(self):
        row = matter(timeline_events=[event('order'),event('order')])
        self.assertEqual(len(self.project([row])['timeline']),1)

    def test_effective_override_preserved_and_rebuild_is_read_only(self):
        row=matter(status='DONE', status_source='user', due_date='2025-01-01', user_comments=[{'text':'Synthetic note'}])
        original=copy.deepcopy(row)
        first=sensor.derive_projects([row]);second=sensor.derive_projects([row])
        self.assertEqual(first,second);self.assertEqual(row,original)
        self.assertEqual(first['projects'][0]['attention'],'COMPLETE')
        self.assertEqual(first['projects'][0]['completed_count'],1)

    def test_past_date_is_not_completion_and_dismissal_is_not_success(self):
        row=matter(due_date='2020-01-01')
        self.assertEqual(self.project([row])['attention'],'WAITING')
        row['status']='DISMISSED'
        self.assertEqual(self.project([row])['completed_count'],0)

    def test_missing_evidence_explicit_unknown_and_no_fabricated_timeline(self):
        row=matter();row['source_message_ids']=[]
        row['timeline_events']=[event('unknown')]
        p=self.project([row])
        self.assertIn('Source evidence missing',p['uncertainties'])
        self.assertIsNone(p['intended_outcome']);self.assertEqual(p['lifecycle'],'candidate')
        self.assertEqual(p['timeline'],[])

    def test_exact_topic_only_and_stable_rebuild_identity(self):
        a,b=matter('a'),matter('b')
        a['case_reference_ids']=[];b['case_reference_ids']=[]
        self.assertEqual(self.project([a])['id'],self.project([b,a])['id'])
        b['topic']='Vehicle insurance'
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)

    def test_attention_has_provenance_links_for_every_bucket(self):
        rows=[matter(str(i),status) for i,status in enumerate(['OPEN','WAITING','DONE','NONE','UNKNOWN'])]
        view=sensor.derive_projects(rows)
        for kind in ('ACTION','WAITING','WATCH','INFORMATION','COMPLETE'):
            self.assertEqual(len(view['attention'][kind]),1)
            self.assertEqual(view['attention'][kind][0]['project_id'],view['projects'][0]['id'])

    def test_outcome_completion_requires_accepted_done_state(self):
        row=matter(user_project={'outcome':'Collect the synthetic vehicle','state':'active','source':'user'})
        self.assertEqual(self.project([row])['lifecycle'],'active')
        row['status']='DONE'
        self.assertEqual(self.project([row])['lifecycle'],'active')
        row['user_project']['state']='complete'
        self.assertEqual(self.project([row])['lifecycle'],'complete')

    def test_order_reference_is_supplier_scoped_and_ambiguous_sets_do_not_bridge(self):
        a,b=matter('a'),matter('b')
        for row in (a,b):
            row['case_reference_ids']=[];row['verified_order_refs']=['ORDER42']
        b['counterparty']='Unrelated supplier'
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)
        b['counterparty']=a['counterparty'];b['verified_order_refs'].append('ORDER43')
        self.assertEqual(len(sensor.derive_projects([a,b])['projects']),2)

    def test_unverified_context_and_malformed_event_do_not_invent_facts(self):
        row=matter(reason='Await source review', source_context={'message_id':'<wrong@example.test>', 'waiting_for':'Fabricated assignment'})
        row['timeline_events']=[{**event('order'), 'observed_at':'bad'}]
        p=self.project([row])
        self.assertEqual(p['waiting_on'],['Await source review'])
        self.assertEqual(p['timeline'],[])

    def test_duplicate_channel_rows_and_confirmation_question(self):
        row=matter(confirmation_required='source_unavailable')
        p=self.project([row,row])
        self.assertEqual(p['attention'],'ACTION')
        self.assertEqual(p['open_count'],1)

    def test_tesla_synthetic_multimessage_lifecycle_uses_accepted_state(self):
        # Invented Tesla case, distinct threads already accepted by the PA.
        row=matter('tesla-demo')
        row.update(counterparty='Tesla', topic='Buy and collect a Tesla Model 3',
                   case_reference_ids=['DEMO-TESLA-42'],
                   source_message_ids=['<order@example.test>','<update@example.test>','<identity@example.test>'],
                   timeline_events=[event('order'),event('update','Order estimate updated','NONE','information',200)])
        self.assertEqual(self.project([row])['attention'],'WAITING')
        self.assertEqual(len(self.project([row])['timeline']),2)
        row['timeline_events'].append(event('identity','Complete identity check','OPEN','obligation',300))
        row['status']='OPEN';row['reason']='Complete identity check'
        projected=self.project([row])
        self.assertEqual(projected['attention'],'ACTION')
        self.assertEqual(projected['latest_update']['title'],'Complete identity check')
        row['timeline_events'].append(event('identity','Requoted identity check','OPEN','obligation',400))
        self.assertEqual(len(self.project([row])['timeline']),3)

    def test_existing_user_overlay_owns_outcome_without_task_mutation(self):
        import sys, tempfile
        sys.path.insert(0,str(ROOT))
        from governor import pa_user_state as state
        row=matter();original=copy.deepcopy(row)
        payload={'schema':'lifeos_tasks_v3','generated_time':1000,'tasks':[row],'resolved':[]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            state.mutate_action(row['id'],'project_outcome',note='Collect the synthetic vehicle',path=path,now=1000)
            overlay=state.read_user_state(path)
            effective=state.apply_user_state(payload,overlay)
            projected=self.project(effective['tasks'])
            self.assertEqual(projected['lifecycle'],'active')
            stable_id=projected['id']
            effective['tasks'][0]['case_reference_ids']=['NEW-ACCEPTED-REF']
            self.assertEqual(self.project(effective['tasks'])['id'],stable_id)
            state.mutate_action(row['id'],'project_complete',path=path,now=1001)
            complete=state.apply_user_state(payload,state.read_user_state(path))
            self.assertEqual(complete['tasks'][0]['status'],'WAITING')
            self.assertEqual(self.project(complete['tasks'])['lifecycle'],'complete')
            self.assertIn('Outcome marked complete but obligations remain open',self.project(complete['tasks'])['uncertainties'])
            cleared=state.apply_user_state(complete,{'obligations':{}})
            self.assertEqual(self.project(cleared['tasks'])['lifecycle'],'candidate')
            state.mutate_action(row['id'],'project_reopen',path=path,now=1002)
            self.assertEqual(state.read_user_state(path)['obligations'][row['id']]['project']['state'],'active')
        self.assertEqual(row,original)

    def test_ha_attribute_and_runtime_acceptance_include_projection(self):
        self.assertIn('        - projects_view\n',(ROOT/'homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml').read_text())
        self.assertIn('PA_PROJECTS_ACTUAL_HA_ENTITY=PASS',(ROOT/'scripts/accept-pa-governed-actions.py').read_text())

if __name__=='__main__':unittest.main()
