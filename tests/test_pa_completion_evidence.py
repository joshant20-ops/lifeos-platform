"""Synthetic step completion contracts; no private source corpus."""
import copy
import unittest
from tests.test_pa_legacy_project_evidence import reconciler
from governor.pa_user_state import apply_user_state
from tests.test_pa_projects import sensor


def source(mid, body, day=28, subject='Synthetic update'):
    return {'message_id': '<' + mid + '@example.test>', 'from':'Example <updates@example.test>',
            'subject':subject, 'body':body, 'date':f'{day} Oct 2026 12:00:00 +0000'}


def row(mid, title, day=28, **kw):
    return {'id':mid, 'title':title, 'topic':title, 'counterparty':'Example', 'status':'OPEN',
            'source_message_ids':['<' + mid + '@example.test>'], 'email_message_id':'<' + mid + '@example.test>',
            'updated_from_email':f'{day} Oct 2026 12:00:00 +0000', **kw}


class CompletionEvidenceTests(unittest.TestCase):
    def test_private_recovery_copy_is_immutable_and_does_not_replace_projection(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tasks.json'
            raw=json.dumps({'schema':'lifeos_tasks_v3','tasks':[{'title':'Synthetic request'}]}).encode()
            path.write_bytes(raw)
            reconciler.preserve_completion_backup(path);reconciler.preserve_completion_backup(path)
            backups=list(Path(folder).glob('*.pre-completion-*'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),raw)
            self.assertEqual(backups[0].stat().st_mode & 0o777,0o600)
            self.assertEqual(path.read_bytes(),raw)
            backups[0].write_text('{}')
            with self.assertRaises(ValueError):reconciler.preserve_completion_backup(path)
    def test_partner_order_links_preserve_auxiliary_refs_without_company_only_merge(self):
        a, b = row('shop','Retailer order'), row('partner','Delivery update')
        a.update(counterparty='Example Motors', verified_order_refs=['DEMO123'])
        b.update(counterparty='Partner', verified_order_refs=['DEMO123','PARTNER42'])
        shop=source('shop','Your order DEMO123 is confirmed.')
        shop['from']='Example Motors <orders@motors.example.test>'
        partner=source('partner','Your Example Motors order DEMO123 is in transit.')
        partner['from']='Partner <updates@partner.example.test>'
        for task, mail in ((a,shop),(b,partner)):
            task['source_context']={'message_id':mail['message_id'],'sender':mail['from']}
        tasks={'shop':a,'partner':b};sources={s['message_id']:s for s in (shop,partner)}
        self.assertEqual(len(sensor.derive_projects(list(tasks.values()))['projects']),2)
        reconciler.correlate_named_supplier_orders(tasks,sources)
        projects=sensor.derive_projects(list(tasks.values()))['projects']
        self.assertEqual(len(projects),1)
        self.assertEqual(b['verified_order_refs'],['DEMO123','PARTNER42'])
        self.assertEqual(b['status'],'OPEN')
        self.assertEqual(next(p for p in projects[0]['provenance'] if p['matter_id']=='partner')['verified_order_links'][0]['source_message_id'],'<partner@example.test>')
        self.assertEqual(sensor.derive_projects([b,a]),sensor.derive_projects([a,b]))
        partner['body']='An update from Example Motors, no order reference.'
        reconciler.correlate_named_supplier_orders(tasks,sources)
        self.assertNotIn('verified_order_links',b)
        self.assertEqual(len(sensor.derive_projects(list(tasks.values()))['projects']),2)

    def test_partner_multiorder_and_quoted_mentions_stay_unresolved(self):
        for body in ('Example Motors order DEMO123 and order OTHER42.', '> Example Motors order DEMO123'):
            a,b=row('a','Order'),row('b','Order')
            a['verified_order_refs']=['DEMO123'];b['verified_order_refs']=['DEMO123','OTHER42']
            mails=[source('a','Your order DEMO123'),source('b',body)]
            mails[0]['from']='Example Motors <orders@motors.example.test>'
            mails[1]['from']='Partner <updates@partner.example.test>'
            reconciler.correlate_named_supplier_orders({'a':a,'b':b},{m['message_id']:m for m in mails})
            self.assertNotIn('verified_order_links',b)

    def scenario(self, title='Complete finance approval', body='Your finance application DEMO123 approved.', request='Please complete your finance approval.'):
        a, b = row('request', title), row('proof', 'Source update', 29, obligation_suppressed='information')
        tasks = {a['id']:a, b['id']:b}
        sources = {m['message_id']:m for m in [source('request',request),source('proof',body,29)]}
        state = {'obligations':{mid:{'project':{'anchor_id':'request'}} for mid in tasks}}
        return tasks, sources, state

    def test_later_approval_completes_approval_with_exact_provenance_and_replay(self):
        tasks, sources, state = self.scenario()
        counts = reconciler.reconcile_completion_evidence(tasks, sources, state)
        self.assertEqual(counts['completed'],1)
        task=tasks['request'];self.assertEqual(task['status'],'DONE')
        self.assertEqual(task['machine_status'],'DONE')
        self.assertEqual(task['completion_previous_status'],'OPEN')
        self.assertEqual(task['completion_evidence'][0]['source_message_id'],'<proof@example.test>')
        self.assertEqual(task['completion_evidence'][0]['relationship'],'owner_confirmed_membership')
        self.assertIn('<proof@example.test>',task['source_message_ids'])
        before=copy.deepcopy(tasks)
        self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)
        self.assertEqual(tasks,before)

    def test_approval_never_completes_identity_signing_or_combined_steps(self):
        for title in ('Complete identity check','Sign finance agreement','Complete identity check and sign finance agreement'):
            tasks,sources,state=self.scenario(title=title)
            self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)
            self.assertEqual(tasks['request']['status'],'OPEN')
        tasks,sources,state=self.scenario(title='Complete identity check',request='Complete identity verification.',body='Your identity verification is complete.')
        sources['<proof@example.test>']['from']='Different provider <verify@other.example.test>'
        self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)

    def test_combined_steps_need_all_explicit_confirmations(self):
        tasks,sources,state=self.scenario(title='Complete identity check and sign finance agreement', body='Your identity verification is complete. Your finance agreement has been signed.', request='Please complete your identity check and sign your finance agreement.')
        self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],1)
        self.assertEqual({p['step'] for p in tasks['request']['completion_evidence']},{'identity','signing'})

    def test_original_source_additional_requests_block_coarse_title_closure(self):
        tasks,sources,state=self.scenario(request='Finance approval: please complete your identity check and sign your finance agreement.')
        self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)

    def test_same_company_without_relationship_is_insufficient(self):
        tasks,sources,_=self.scenario()
        self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,{'obligations':{}})['completed'],0)
        for task in tasks.values():task['verified_order_refs']=['DEMO123']
        self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,{'obligations':{}})['completed'],1)

    def test_older_equal_missing_and_timezone_less_dates_do_not_complete(self):
        for date in ('27 Oct 2026 12:00:00 +0000','28 Oct 2026 12:00:00 +0000','29 Oct 2026 12:00:00','invalid',''):
            tasks,sources,state=self.scenario();sources['<proof@example.test>']['date']=date
            self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)

    def test_future_negative_conditional_and_quoted_text_are_not_completion(self):
        for text in ('Your finance application is not approved.','Once your finance application is approved, sign in.',
                     'Is your finance application approved?', 'Ensure your finance application is approved.',
                     'Your finance application will be approved.','Please check if your finance application is approved.',
                     '> Your finance application DEMO123 approved.',
                     'New message\nOn Wednesday someone wrote:\nYour finance application DEMO123 approved.'):
            tasks,sources,state=self.scenario(body=text)
            self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)
        tasks,sources,state=self.scenario(body='> Old quoted text')
        sources['<proof@example.test>']['subject']='Fwd: Your finance application DEMO123 approved'
        self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)

    def test_user_override_missing_source_and_wrong_source_identity_are_preserved(self):
        for mode in ('override','missing','wrong'):
            tasks,sources,state=self.scenario();before=copy.deepcopy(tasks)
            if mode=='override':state['obligations']['request']['status_override']='WAITING'
            if mode=='missing':sources.pop('<request@example.test>')
            if mode=='wrong':sources['<proof@example.test>']['message_id']='<other@example.test>'
            self.assertEqual(reconciler.reconcile_completion_evidence(tasks,sources,state)['completed'],0)
            self.assertEqual(tasks,before)

    def test_source_completion_wins_scoped_waiting_without_erasing_owner_notes(self):
        tasks,sources,state=self.scenario()
        state['obligations']['request'].update(waiting_confirmation={'source_ids':['<request@example.test>'],'confirmed_at':100,'confirmed_revision':1},comments=[{'text':'Synthetic note','created_at':100}])
        reconciler.reconcile_completion_evidence(tasks,sources,state)
        payload={'schema':'lifeos_tasks_v3','tasks':list(tasks.values()),'resolved':[]}
        effective=apply_user_state(payload,state)
        task=next(t for t in effective['resolved'] if t['id']=='request')
        self.assertEqual(task['status'],'DONE');self.assertEqual(task['machine_status'],'DONE')
        self.assertEqual(state['obligations']['request']['comments'][0]['text'],'Synthetic note')


if __name__=='__main__':unittest.main()
