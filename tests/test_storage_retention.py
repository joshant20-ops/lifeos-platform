import contextlib
import copy
import datetime as dt
import importlib.util
import json
import os
import pathlib
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('retention',ROOT/'governor/storage_retention.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
NOW=dt.datetime(2030,6,1,tzinfo=dt.timezone.utc)
POLICY=json.loads((ROOT/'governor/storage-retention-policy.json').read_text())
def generation(**updates):
    g={'service':'synthetic-service','generation_id':'generation-a','category':'automation_backup','root_id':'backup-root',
       'created_at':(NOW-dt.timedelta(days=41)).isoformat(),'completed_at':(NOW-dt.timedelta(days=40)).isoformat(),
       'timestamp_verified':True,'producer_evidence_id':'synthetic-completion-record','state':'completed','active':False,
       'references_verified':True,'dependencies':[],'open_references':0,'holds':[],'verification':'passed',
       'live_data':False,'database_volume':False,'offhost_required':False,'logical_bytes':4,'allocated_bytes':4096,
       'relative_path':'generation-a','record_class':'ordinary_payload',
       'files':[{'relative_path':'generation-a/data','allocated_bytes':4096,'identity':{'st_dev':1,'st_ino':2,'st_size':4,'st_mtime_ns':3,'st_ctime_ns':4}}]}
    g.update(updates);return g
def inventory(g=None):
    return {'schema_version':1,'complete':True,'observed_at':NOW.isoformat(),'generations':[g or generation()],
            'recovery_points':[{'service':'synthetic-service','generation_id':'retained-point','protected':True,'verified':True,
                                'available':True,'offhost':True,'independent_failure_domain':True},
                               {'service':'synthetic-service','generation_id':'retained-point-2','protected':True,'verified':True,
                                'available':True,'offhost':False,'independent_failure_domain':False}]}
class PolicyTests(unittest.TestCase):
    def test_individually_cleared_generation_not_blocked_by_other_unknown(self):
        good=generation()
        unknown=generation(generation_id='unknown',timestamp_verified=False,references_verified=False)
        inv=inventory(good);inv.update(complete=False,generations=[good,unknown])
        manifest,summary=r.assess(inv,POLICY,NOW)
        self.assertEqual(summary['eligible_generations'],1)
        self.assertEqual(len(manifest['entries']),1)
    def test_automation_keeps_two_distinct_recovery_generations(self):
        inv=inventory();inv['recovery_points']=inv['recovery_points'][:1]
        self.assertIn('no_retained_verified_recovery',self.why(inv=inv))

    def why(self,g=None,inv=None,p=None):return r.reasons(g or generation(),inv or inventory(g),p or POLICY,NOW)
    def test_default_expired_generation(self):self.assertEqual(self.why(),[])
    def test_missing_metadata(self):
        g=generation();del g['producer_evidence_id'];self.assertIn('missing_or_invalid_metadata',self.why(g))
    def test_mtime_is_not_creation(self):self.assertIn('unverified_timestamp',self.why(generation(timestamp_verified=False)))
    def test_active_job(self):self.assertIn('active_or_nonterminal',self.why(generation(active=True)))
    def test_open_log(self):self.assertIn('reference_or_hold',self.why(generation(category='cron_log',open_references=1)))
    def test_unknown_references(self):self.assertIn('reference_or_hold',self.why(generation(references_verified=False)))
    def test_dependency(self):self.assertIn('reference_or_hold',self.why(generation(dependencies=['open-incident'])))
    def test_sole_recovery(self):
        inv=inventory();inv['recovery_points'][0]['generation_id']='generation-a'
        self.assertIn('protected_recovery_point',self.why(inv=inv));self.assertIn('no_retained_verified_recovery',self.why(inv=inv))
    def test_missing_recovery(self):
        inv=inventory();inv['recovery_points']=[];self.assertIn('no_retained_verified_recovery',self.why(inv=inv))
    def test_same_failure_domain_not_offsite(self):
        inv=inventory();inv['recovery_points'][0]['independent_failure_domain']=False
        p=copy.deepcopy(POLICY);p['categories']['automation_backup']['offhost_required']=True
        self.assertIn('offhost_coverage_unproven',self.why(inv=inv,p=p))
    def test_live_database_volume(self):self.assertIn('protected_live_data',self.why(generation(database_volume=True)))
    def test_incomplete_inventory(self):
        inv=inventory();inv['complete']=False;self.assertNotIn('inventory_incomplete',self.why(inv=inv))
    def test_stale_inventory(self):
        inv=inventory();inv['observed_at']=(NOW-dt.timedelta(minutes=6)).isoformat();self.assertIn('stale_inventory',self.why(inv=inv))
    def test_future_completion(self):self.assertIn('unverified_timestamp',self.why(generation(completed_at=(NOW+dt.timedelta(days=1)).isoformat())))
    def test_naive_timestamp(self):self.assertIn('missing_or_invalid_metadata',self.why(generation(completed_at='2030-01-01')))
    def test_repair_uses_closure(self):
        g=generation(category='repair_snapshot',closed_at=(NOW-dt.timedelta(days=5)).isoformat())
        self.assertIn('within_retention',self.why(g))
    def test_repair_requires_closure_proof(self):
        g=generation(category='repair_snapshot',closed_at=(NOW-dt.timedelta(days=20)).isoformat())
        self.assertIn('unverified_closure',self.why(g));g.update(closure_verified=True,closure_evidence_id='synthetic-closure');self.assertEqual(self.why(g),[])
    def test_success_payload_seven_days(self):self.assertEqual(self.why(generation(category='successful_job',completed_at=(NOW-dt.timedelta(days=8)).isoformat())),[])
    def test_failed_payload_thirty_days(self):self.assertEqual(self.why(generation(category='failed_job',state='failed')),[])
    def test_control_record_floor(self):self.assertIn('within_retention',self.why(generation(category='successful_job',record_class='control_record')))
    def test_service_override(self):
        p=copy.deepcopy(POLICY);p['services']={'synthetic-service':{'automation_backup':{'days':90}}}
        self.assertIn('within_retention',self.why(p=p))
    def test_reserve_cannot_be_lowered(self):
        p=copy.deepcopy(POLICY);p['minimum_free_percent']=5
        self.assertIn('missing_or_invalid_metadata',self.why(p=p))
    def test_paperless_requires_native_adapter(self):self.assertIn('existing_rehearsal_adapter_required',self.why(generation(category='paperless_rehearsal',temporary=True,restore_verification_passed=True)))
    def test_file_escape(self):self.assertIn('missing_or_invalid_metadata',self.why(generation(relative_path='../escape')))
    def test_missing_file_manifest(self):
        g=generation();del g['files'];self.assertIn('missing_or_invalid_metadata',self.why(g))
    def test_duplicate_inventory(self):
        inv=inventory();inv['generations']*=2
        with self.assertRaises(ValueError):r.assess(inv,POLICY,NOW)
    def test_dry_run_estimate_not_recovery(self):
        m,s=r.assess(inventory(),POLICY,NOW);self.assertEqual(s['potential_allocated_bytes'],4096);self.assertEqual(s['guaranteed_recovered_bytes'],0)
        self.assertEqual(m['policy_sha256'],r.digest(POLICY))
    def test_policy_executor_disabled(self):self.assertFalse(POLICY['executor_enabled'])
    def test_image_roles_and_references(self):
        g=generation(category='predbat_image',image_id='sha256:'+'5'*64,image_references_verified=True,tags=[],registry_digests=[])
        inv=inventory(g);inv['protected_images']={'synthetic-service':dict(zip(['production','rollback','approved_history_1','approved_history_2'],['sha256:'+str(i)*64 for i in range(1,5)]))};inv['container_image_ids']=[g['image_id']]
        self.assertIn('protected_image',self.why(g,inv));inv['container_image_ids']=[];self.assertEqual(self.why(g,inv),[])
    def test_logrotate_does_not_expire_behind_manifest(self):
        text=r.logrotate_entry('/synthetic/cron.log',True)
        self.assertIn('rotate -1',text);self.assertIn('nocopytruncate',text);self.assertNotIn('maxage',text)
    def test_logrotate_rejects_unverified_writer(self):
        with self.assertRaises(ValueError):r.logrotate_entry('/synthetic/cron.log')
    def test_logrotate_rejects_injection(self):
        with self.assertRaises(ValueError):r.logrotate_entry('/synthetic/log\npostrotate bad',True)
    def test_weekly_summary(self):
        h=[{'observed_at':(NOW-dt.timedelta(days=7)).isoformat(),'available_bytes':100,'eligible_generations':1,'potential_allocated_bytes':4},
           {'observed_at':NOW.isoformat(),'available_bytes':80,'eligible_generations':2,'potential_allocated_bytes':8}]
        self.assertEqual(r.weekly(h)['net_storage_growth_bytes'],20)
    def test_private_approval_permissions(self):self.assertFalse(r.private_info(SimpleNamespace(st_uid=0,st_mode=0o644)))
    def test_native_docker_rejects_arbitrary_commands(self):
        for args in [['system','prune'],['image','rm','--force','sha256:'+'1'*64],['container','exec','x','sh']]:
            with patch.object(r.subprocess,'run') as run,self.assertRaises(ValueError):r.NativeDocker().run(args)
            run.assert_not_called()
    def test_native_docker_is_pinned_to_local_socket(self):
        cp=SimpleNamespace(returncode=0,stdout='')
        with patch.object(r.subprocess,'run',return_value=cp) as run:r.NativeDocker().run(['image','ls','--all','--quiet','--no-trunc'])
        self.assertEqual(run.call_args.args[0][:3],['/usr/bin/docker','--host','unix:///run/docker.sock'])
        self.assertNotIn('shell',run.call_args.kwargs)
    def test_inventory_schema(self):
        schema=json.loads((ROOT/'governor/contracts/storage-retention-inventory.schema.json').read_text())
        self.assertIn('completed_at',schema['properties']['generations']['items']['required'])
        self.assertIn('recovery_points',schema['required'])
    def test_metrics_have_real_assessment_timestamp(self):
        _,s=r.assess(inventory(),POLICY,NOW)
        text=r.metrics(s,{'available_bytes':1000,'reserve_bytes':100})
        self.assertIn('lifeos_retention_assessment_timestamp_seconds '+str(int(NOW.timestamp())),text)
        self.assertIn('lifeos_retention_guaranteed_recovered_bytes 0',text)
    def test_metrics_reject_text_injection(self):
        _,s=r.assess(inventory(),POLICY,NOW)
        with self.assertRaises(ValueError):r.metrics(s,{'available_bytes':'private\ntext','reserve_bytes':100})
    def test_daily_not_configured(self):
        with patch.dict(os.environ,{},clear=True):self.assertEqual(r.daily()['status'],'NOT_CONFIGURED')
    def test_daily_permission_error_is_sanitised(self):
        with patch.dict(os.environ,{'LIFEOS_RETENTION_CONFIG':'/synthetic/config'},clear=True),patch.object(r,'bounded_json',side_effect=PermissionError('private-path')):
            d=r.daily();self.assertEqual(d['status'],'UNVERIFIED');self.assertNotIn('private-path',json.dumps(d))
    def test_optional_daily_hook_never_breaks_existing_publisher(self):
        with patch.dict(os.environ,{'LIFEOS_RETENTION_CONFIG':'/synthetic/config'},clear=True),patch.object(r,'bounded_json',return_value=[]):
            self.assertEqual(r.daily()['status'],'UNVERIFIED')
    def test_empty_incomplete_inventory_is_not_all_clear(self):
        inv=inventory();inv.update(complete=False,generations=[])
        _,summary=r.assess(inv,POLICY,NOW);self.assertEqual(summary['status'],'INCOMPLETE');self.assertEqual(summary['unverified_generations'],1)
    def test_admission_prevents_backup_loop(self):
        p=copy.deepcopy(POLICY);p['producer_limits']['max_daily_generations']=1
        existing=[generation(created_at=NOW.isoformat())]
        c={'available_bytes':1000,'reserve_bytes':100,'capacity_bytes':1000}
        self.assertEqual(r.producer_admission('synthetic-service','job','a'*64,10,existing,c,p,NOW),'BLOCK_DAILY_GENERATION_LIMIT')
    def test_admission_preserves_reserve(self):
        c={'available_bytes':110,'reserve_bytes':100,'capacity_bytes':1000}
        self.assertEqual(r.producer_admission('synthetic-service','job','a'*64,20,[],c,POLICY,NOW),'BLOCK_PROTECTED_RESERVE')
    def test_admission_reuses_only_same_source_epoch(self):
        g=generation(job_id='job',source_epoch_sha256='a'*64)
        c={'available_bytes':1000,'reserve_bytes':100,'capacity_bytes':1000}
        self.assertEqual(r.producer_admission('synthetic-service','job','a'*64,10,[g],c,POLICY,NOW),'REUSE_VERIFIED_GENERATION')
        self.assertEqual(r.producer_admission('synthetic-service','job','b'*64,10,[g],c,POLICY,NOW),'ALLOW_REGISTERED_PRODUCER')
    def test_admission_unknown_size_is_blocked(self):
        self.assertEqual(r.producer_admission('synthetic-service','job','a'*64,None,[],{},POLICY,NOW),'BLOCK_SIZE_ESTIMATE_REQUIRED')
    def test_attention_identity_is_stable(self):
        _,s=r.assess(inventory(),POLICY,NOW);c={'available_bytes':1,'reserve_bytes':2}
        self.assertEqual(r.attention(s,c),r.attention(s,c));self.assertEqual(r.attention(s,c)['attention_id'],'storage-retention:capacity')

class Guards:
    def __init__(self,inv):self.inv=inv;self.busy=False;self.fail=False;self.capacity_calls=0
    @contextlib.contextmanager
    def exclusive(self):yield
    def health(self):
        if self.fail:raise ValueError('protected_health_failed')
    def inventory(self):return self.inv
    def file_idle(self,*args):
        if self.busy:raise ValueError('open_file')
    def revalidate(self):pass
    def approved_roots(self):return self.roots
    def capacity(self):self.capacity_calls+=1;return 1000+self.capacity_calls*100

class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);p=pathlib.Path(self.temp.name)
        self.root=p/'managed';self.root.mkdir();(self.root/'generation-a').mkdir();self.file=self.root/'generation-a/data';self.file.write_bytes(b'data')
        self.state=p/'state';self.state.mkdir(mode=0o700)
        g=generation();info=self.file.stat();g['files'][0]['identity']=r.file_identity(info);g['files'][0]['allocated_bytes']=info.st_blocks*512;g['allocated_bytes']=info.st_blocks*512
        self.inv=inventory(g);self.policy=copy.deepcopy(POLICY);self.policy['executor_enabled']=True
        self.manifest,_=r.assess(self.inv,self.policy,NOW);self.guards=Guards(self.inv)
        self.guards.roots={'backup-root':str(self.root)}
        self.approval={'manifest_sha256':r.digest(self.manifest),'approved':True,'expires_at':(NOW+dt.timedelta(minutes=4)).isoformat()}
    def apply(self):
        load=lambda path:self.approval if str(path)=='unused' else r.bounded_json(path)
        with patch.object(r.os,'geteuid',return_value=0),patch.object(r,'private_info',return_value=True),patch.object(r,'trusted_json',side_effect=load),patch.object(r,'STATE_ROOT',self.state):
            return r.execute(self.manifest,self.policy,{'backup-root':str(self.root)},self.state,'unused',self.guards,NOW)
    def test_delete_exact_synthetic_file_and_measure(self):
        result=self.apply();self.assertFalse(self.file.exists());self.assertEqual(result['net_available_delta_bytes'],100)
        saved=self.state/(r.digest(self.manifest)+'.manifest.json')
        self.assertEqual(r.digest(json.loads(saved.read_text())),r.digest(self.manifest))
    def test_duplicate_execution_no_second_delete(self):
        self.apply();self.assertEqual(self.apply()['status'],'ALREADY_COMPLETE')
    def test_interrupted_cleanup_requires_reconciliation(self):
        with patch.object(r.os,'unlink',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.apply()
        with self.assertRaisesRegex(ValueError,'interrupted'):self.apply()
        self.assertTrue(self.file.exists())
    def test_interrupt_after_unlink_never_replays(self):
        original=os.unlink
        def interrupted(*args,**kwargs):
            original(*args,**kwargs);raise RuntimeError('synthetic_interrupt')
        with patch.object(r.os,'unlink',side_effect=interrupted),self.assertRaises(RuntimeError):self.apply()
        self.assertFalse(self.file.exists())
        with self.assertRaisesRegex(ValueError,'interrupted'):self.apply()
    def test_policy_disabled(self):
        self.policy['executor_enabled']=False
        with self.assertRaisesRegex(ValueError,'disabled'):self.apply()
    def test_wrong_manifest_approval(self):
        self.approval['manifest_sha256']='0'*64
        with self.assertRaises(ValueError):self.apply()
        self.assertTrue(self.file.exists())
    def test_expired_approval(self):
        self.approval['expires_at']=NOW.isoformat()
        with self.assertRaises(ValueError):self.apply()
    def test_approval_expiry_rechecked_before_atomic_operation(self):
        with patch.object(r.time,'monotonic',side_effect=[0,0,1000]),self.assertRaisesRegex(ValueError,'approval_expired'):self.apply()
        self.assertTrue(self.file.exists())
    def test_generation_changed(self):
        self.file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'file_changed'):self.apply()
    def test_symlink_never_followed(self):
        self.file.unlink();self.file.symlink_to('/synthetic/outside')
        with self.assertRaises(OSError):self.apply()
    def test_hardlink_held(self):
        os.link(self.file,self.root/'another-link')
        with self.assertRaisesRegex(ValueError,'unsafe_file'):self.apply()
    def test_open_file_guard(self):
        self.guards.busy=True
        with self.assertRaisesRegex(ValueError,'open_file'):self.apply()
        self.assertTrue(self.file.exists())
    def test_protected_health_guard(self):
        self.guards.fail=True
        with self.assertRaisesRegex(ValueError,'health'):self.apply()
    def test_unknown_root(self):
        self.manifest['entries'][0]['root_id']='unregistered';self.inv['generations'][0]['root_id']='unregistered'
        self.manifest['root_id']='unregistered'
        self.manifest['inventory_sha256']=r.digest(self.inv);self.approval['manifest_sha256']=r.digest(self.manifest)
        with self.assertRaisesRegex(ValueError,'unregistered_root'):self.apply()
    def test_sibling_file_not_deleted(self):
        sibling=self.root/'generation-other';sibling.mkdir();(sibling/'data').write_bytes(b'protected')
        self.apply();self.assertTrue((sibling/'data').exists())
    def test_lock_symlink_refused(self):
        (self.state/'retention.lock').symlink_to(self.file)
        with self.assertRaises(OSError):self.apply()
        self.assertTrue(self.file.exists())
    def test_image_manifest_uses_only_native_exact_id_adapter(self):
        g=self.inv['generations'][0];g.update(category='predbat_image',image_id='sha256:'+'9'*64,image_references_verified=True,tags=[],registry_digests=[])
        self.inv['protected_images']={'synthetic-service':dict(zip(['production','rollback','approved_history_1','approved_history_2'],['sha256:'+str(i)*64 for i in range(1,5)]))}
        self.inv['container_image_ids']=[]
        self.manifest,_=r.assess(self.inv,self.policy,NOW);self.approval['manifest_sha256']=r.digest(self.manifest)
        native=SimpleNamespace(preflight=lambda *args:None,remove=lambda identity:self.assertEqual(identity,g['image_id']))
        with patch.object(r,'NativeDocker',return_value=native):self.assertEqual(self.apply()['status'],'COMPLETE')
        self.assertTrue(self.file.exists())
    def test_native_rotation_requires_closed_registered_logs(self):
        self.policy['rotation_enabled']=True
        self.guards.log_metadata=lambda path:{'registered':True,'open_references':1,'writer_reopen_verified':True,'compression_input_bytes':0,'reserve_bytes':0}
        with patch.object(r.os,'geteuid',return_value=0),self.assertRaisesRegex(ValueError,'not_idle'):r.rotate_log('/synthetic/cron.log',self.policy,self.guards)
    def test_native_rotation_defers_when_compression_could_breach_reserve(self):
        self.policy['rotation_enabled']=True
        self.guards.log_metadata=lambda path:{'registered':True,'open_references':0,'writer_reopen_verified':True,'compression_input_bytes':1000,'reserve_bytes':0}
        with patch.object(r.os,'geteuid',return_value=0),self.assertRaisesRegex(ValueError,'reserve'):r.rotate_log('/synthetic/cron.log',self.policy,self.guards)
    def test_native_rotation_does_not_force_or_delete_archives(self):
        self.policy['rotation_enabled']=True
        self.guards.log_metadata=lambda path:{'registered':True,'open_references':0,'writer_reopen_verified':True,'compression_input_bytes':0,'reserve_bytes':0}
        with patch.object(r.os,'geteuid',return_value=0),patch.object(r,'STATE_ROOT',self.state),patch.object(r,'private_info',return_value=True),patch.object(r.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            d=r.rotate_log('/synthetic/cron.log',self.policy,self.guards)
        self.assertFalse(d['archive_deletion_authorised']);self.assertNotIn('--force',run.call_args.args[0])

if __name__=='__main__':unittest.main()
