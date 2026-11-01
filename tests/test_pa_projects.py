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
        row=matter(intended_outcome='Collect the synthetic vehicle')
        self.assertEqual(self.project([row])['lifecycle'],'active')
        row['status']='DONE'
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

    def test_ha_attribute_and_runtime_acceptance_include_projection(self):
        self.assertIn('        - projects_view\n',(ROOT/'homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml').read_text())
        self.assertIn('PA_PROJECTS_ACTUAL_HA_ENTITY=PASS',(ROOT/'scripts/accept-pa-governed-actions.py').read_text())

if __name__=='__main__':unittest.main()
