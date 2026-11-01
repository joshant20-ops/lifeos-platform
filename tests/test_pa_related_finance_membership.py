"""Owner relationship confirmation cannot silently change a finance obligation."""
import copy
from pathlib import Path
import tempfile
import unittest
from governor import pa_user_state as state
from tests.test_pa_owner_project_confirmation import fixture, confirm, rows, REF, source_row
from tests.test_pa_projects import sensor

LINK='owner-finance-fixture-012345'


def finance(key='finance', **kw):
    return {**source_row(key),'title':'Example Vehicle PCP finance approval','topic':'Car finance approval',
            'counterparty':'Example Lender', **kw}


def link(payload,path):
    return state.link_reviewed_project_members(payload,parent_ref=REF,confirmation_ref=LINK,
          vehicle_name='Example Vehicle',lender_name='Example Lender',reviewed_before=1030,path=path,now=1040)


class RelatedFinanceTests(unittest.TestCase):
    def test_lender_and_vehicle_finance_labels_but_not_unrelated_products(self):
        for item in [finance(),finance(title='Complete Example Lender identity check',topic='Identity verification'),
                     finance(title='Example Lender PCP agreement',topic='PCP')]:
            self.assertTrue(state.related_vehicle_finance(item,vehicle_name='Example Vehicle',lender_name='Example Lender'))
        for title in ['Example Lender personal loan identity check','Example Lender credit card statement',
                      'Example Lender mortgage payment','Unrelated recruitment account setup','Example Lender insurance quote']:
            item=finance(title=title,topic='',counterparty='')
            self.assertFalse(state.related_vehicle_finance(item,vehicle_name='Example Vehicle',lender_name='Example Lender'))

    def test_additive_membership_preserves_status_scope_notes_and_source_uncertainty(self):
        payload=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json';state._write_atomic(state._default(),path);confirm(payload,path)
            new=finance(confirmation_required='source_unavailable')
            payload['tasks'].append(new)
            existing=state.read_user_state(path)
            existing['obligations']['finance']={'comments':[{'id':'note','source':'user_comment','text':'Synthetic owner note','created_at':100}]}
            state._write_atomic(existing,path)
            original=copy.deepcopy(payload)
            self.assertEqual(link(payload,path)['members'],1)
            after=state.read_user_state(path)
            for key,value in existing['obligations']['finance'].items():self.assertEqual(after['obligations']['finance'][key],value)
            self.assertNotIn('waiting_confirmation',after['obligations']['finance'])
            view=state.apply_user_state(payload,after)
            projects=sensor.derive_projects(rows(view))['projects']
            self.assertEqual(len(projects),1)
            self.assertEqual(set(projects[0]['matter_ids']),{'a','b','c','finance'})
            self.assertEqual(projects[0]['buckets']['WAITING'],['b','c'])
            self.assertEqual(projects[0]['buckets']['ACTION'],['finance'])
            self.assertIn('Review a recorded item',projects[0]['next_action'][0])
            item=next(r for r in rows(view) if r['id']=='finance')
            self.assertEqual(item['confirmation_required'],'source_unavailable')
            self.assertEqual(item['status'],'OPEN')
            self.assertEqual(payload,original)
            self.assertEqual(link({**payload,'generated_time':9999},path)['result'],'ALREADY_APPLIED')
            payload['tasks'].append(source_row('unrelated'))
            self.assertEqual(len(sensor.derive_projects(rows(state.apply_user_state(payload,after)))['projects']),2)

    def test_existing_date_priority_status_overrides_remain_effectively_identical(self):
        payload=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json';state._write_atomic(state._default(),path);confirm(payload,path)
            payload['tasks'].append(finance())
            existing=state.read_user_state(path)
            existing['obligations']['finance']={'severity_override':'high','due_date_override':'2027-02-01','status_override':'WAITING','status_set_at':1000}
            state._write_atomic(existing,path)
            before=next(r for r in rows(state.apply_user_state(payload,existing)) if r['id']=='finance')
            link(payload,path)
            after=next(r for r in rows(state.apply_user_state(payload,state.read_user_state(path))) if r['id']=='finance')
            for key in ('status','due_date','severity','due_date_source','severity_source','status_source'):
                self.assertEqual(after[key],before[key])

    def test_completed_finance_stays_completed_and_no_waiting_is_added(self):
        payload=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json';state._write_atomic(state._default(),path);confirm(payload,path)
            payload['resolved'].append(finance(status='DONE'))
            link(payload,path)
            view=state.apply_user_state(payload,state.read_user_state(path))
            self.assertEqual(next(r for r in rows(view) if r['id']=='finance')['status'],'DONE')
            self.assertEqual(sensor.derive_projects(rows(view))['projects'][0]['buckets']['COMPLETE'],['finance'])

    def test_no_matching_members_or_changed_snapshot_fails_without_state_write(self):
        for mode in ('missing','changed'):
            payload=fixture()
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'user.json';state._write_atomic(state._default(),path);confirm(payload,path)
                before=state.read_user_state(path)
                if mode=='changed':payload['tasks'].append(finance());payload['generated_time']=1031
                with self.assertRaises(ValueError):link(payload,path)
                self.assertEqual(state.read_user_state(path),before)
                self.assertFalse((Path(folder)/('user-state-before-'+LINK+'.json')).exists())

if __name__=='__main__':unittest.main()
