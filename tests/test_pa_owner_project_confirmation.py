"""Owner-linked Projects stay derived and only override reviewed source versions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from governor import pa_user_state as state
from tests.test_pa_projects import sensor

REF='owner-fixture-0123456789'


def source_row(key, *, information=False):
    mid=f'<{key}@example.test>'
    return {'id':key,'title':key,'topic':key,'counterparty':'Example Motors','status':'OPEN',
            'email_message_id':mid,'source_message_ids':[mid],
            'source_context':{'message_id':mid,'sender':'Example Motors <orders@motors.example.test>','subject':'Synthetic source'},
            'timeline_events':[{'message_id':mid,'title':f'Source {key}','event_kind':'information','status':'NONE','evidence_only':True,'observed_at':500}],
            'source_disposition_checks':{'missing':0},
            **({'obligation_suppressed':'order_acknowledgement'} if information else {})}


def fixture():
    return {'schema':'lifeos_tasks_v3','generated_time':1000,'tasks':[source_row('b'),source_row('c')],
            'resolved':[],'informational':[source_row('a',information=True)]}


def confirm(payload,path,**kw):
    return state.confirm_reviewed_project(payload,provider='motors.example.test',expected_count=3,
                                         expected_active=2,reviewed_before=1010,confirmation_ref=REF,path=path,now=1020,**kw)


def rows(payload):
    return payload['tasks']+payload['resolved']+payload.get('informational',[])


class OwnerProjectTests(unittest.TestCase):
    def test_one_owner_project_waiting_information_provenance_and_rebuild(self):
        original=fixture();before=copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json'
            state._write_atomic(state._default(),path)
            self.assertEqual(confirm(original,path)['result'],'APPLIED')
            overlay=state.read_user_state(path)
            view=state.apply_user_state(original,overlay)
            projects=sensor.derive_projects(rows(view))['projects']
            self.assertEqual(len(projects),1)
            p=projects[0]
            self.assertEqual(p['attention'],'WAITING');self.assertEqual(p['lifecycle'],'active')
            self.assertEqual(p['anchor_matter_id'],'a')
            self.assertEqual(p['buckets']['WAITING'],['b','c']);self.assertEqual(p['buckets']['INFORMATION'],['a'])
            self.assertEqual(p['buckets']['ACTION'],[])
            self.assertEqual(p['waiting_on'],['Vehicle and collection assignment'])
            self.assertEqual({v['confirmation_ref'] for v in p['provenance']},{REF})
            replay=state.apply_user_state(view,overlay)
            self.assertEqual(sensor.derive_projects(rows(replay))['projects'],projects)
            self.assertEqual(state.read_user_state(path),overlay)
            self.assertEqual(confirm({**original,'generated_time':5000},path)['result'],'ALREADY_APPLIED')
            self.assertEqual(original,before)

    def test_later_information_preserves_waiting_but_request_and_unknown_unblock(self):
        original=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json';state._write_atomic(state._default(),path);confirm(original,path)
            overlay=state.read_user_state(path)
            for kind,metadata,expected in [('information',False,'WAITING'),('obligation',False,'OPEN'),('information',True,'OPEN')]:
                fresh=copy.deepcopy(original);item=fresh['tasks'][0]
                item['source_message_ids'].append('<new@example.test>')
                item['timeline_events'].append({'message_id':'<new@example.test>','title':'New accepted update','event_kind':kind,
                                                'status':'NONE' if kind=='information' else 'OPEN','evidence_only':metadata,'observed_at':1100})
                view=state.apply_user_state(fresh,overlay)
                found=next(r for r in rows(view) if r['id']=='b')
                self.assertEqual(found['status'],expected)
                self.assertEqual(sensor.derive_projects(rows(view))['projects'][0]['attention'],'WAITING' if expected=='WAITING' else 'ACTION')
            fresh=copy.deepcopy(original);fresh['tasks'][0]['source_message_ids'].append('<unknown@example.test>')
            self.assertEqual(state.apply_user_state(fresh,overlay)['tasks'][0]['status'],'OPEN')

    def test_new_completion_and_newer_owner_decision_are_not_hidden(self):
        original=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json';state._write_atomic(state._default(),path);confirm(original,path)
            fresh=copy.deepcopy(original);fresh['tasks'][0]['status']='DONE'
            self.assertEqual(state.apply_user_state(fresh,state.read_user_state(path))['resolved'][0]['status'],'DONE')
            state.mutate_action('b','reopen',path=path,now=1020) # same second, later revision
            found=next(r for r in rows(state.apply_user_state(original,state.read_user_state(path))) if r['id']=='b')
            self.assertEqual(found['status'],'OPEN');self.assertEqual(found['status_source'],'user')

    def test_annotations_and_backup_preserve_unrelated_and_backing_values(self):
        original=fixture()
        initial={'schema':state.SCHEMA,'revision':4,'obligations':{
            'b':{'comments':[{'id':'note','text':'Synthetic note','source':'user_comment','created_at':10}],
                 'due_date_override':'2027-01-01','severity_override':'high'},'unrelated':{'status_override':'DONE'}}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json';state._write_atomic(initial,path);confirm(original,path)
            saved=state.read_user_state(path)
            self.assertEqual(saved['obligations']['unrelated'],initial['obligations']['unrelated'])
            for key,value in initial['obligations']['b'].items():self.assertEqual(saved['obligations']['b'][key],value)
            self.assertEqual(json.loads((Path(folder)/('user-state-before-'+REF+'.json')).read_text()),initial)
            view=state.apply_user_state(original,saved)
            removed=state.apply_user_state(view,state._default())
            restored=next(r for r in rows(removed) if r['id']=='b')
            self.assertEqual(restored['status'],'OPEN');self.assertIsNone(restored.get('user_waiting_for'))
            self.assertIsNone(restored.get('due_date'));self.assertNotEqual(restored.get('severity'),'high')
            self.assertEqual(len(sensor.derive_projects(rows(removed))['projects']),3)

    def test_changed_membership_or_newer_snapshot_fail_without_writing(self):
        for mode in ('count','snapshot','source','decision'):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'user.json';initial=state._default()
                if mode=='decision':initial['obligations']['b']={'status_set_at':1011,'status_override':'OPEN'}
                state._write_atomic(initial,path);data=fixture()
                if mode=='count':data['tasks'].append(source_row('other'))
                if mode=='snapshot':data['generated_time']=1011
                if mode=='source':data['tasks'][0]['source_disposition_checks']['missing']=1
                with self.assertRaises(ValueError):confirm(data,path)
                self.assertEqual(state.read_user_state(path),initial)
                self.assertFalse(list(Path(folder).glob('user-state-before-*')))

    def test_unrelated_later_same_supplier_does_not_inherit_membership(self):
        original=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json';state._write_atomic(state._default(),path);confirm(original,path)
            original['tasks'].append(source_row('unrelated'))
            projects=sensor.derive_projects(rows(state.apply_user_state(original,state.read_user_state(path))))['projects']
            self.assertEqual(len(projects),2)
            independent=next(p for p in projects if 'unrelated' in p['matter_ids'])
            self.assertEqual(independent['attention'],'ACTION');self.assertEqual(independent['matter_ids'],['unrelated'])

if __name__=='__main__':unittest.main()
