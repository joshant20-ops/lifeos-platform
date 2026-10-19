#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
import urllib.error
from email.message import Message
from unittest import mock

ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
builder=load('house_status_builder',ROOT/'homeassistant/build-house-status-release.py')
gate=load('house_status_gate',ROOT/'homeassistant/verify-house-status-live-release.py')
energy_scope=load('house_status_energy_scope',ROOT/'scripts/lifeos-house-status-energy-scope.py')

class ReleaseGovernance(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((ROOT/'homeassistant/releases/house-status/live/approved-release.json').read_text())

    def test_approved_pointer_is_explicit_and_v29_is_inert(self):
        approved=gate.verify_manifest(self.manifest)
        self.assertRegex(approved['release'],r'^v(?:[3-9][0-9]|[1-9][0-9]{2,})$')
        cfg=(ROOT/'homelab/live/opt/stacks/homeassistant/config/configuration.yaml').read_text()
        allowed_config_releases=(approved['release'],self.manifest['previous_production_release'])
        self.assertTrue(any(f'name: lifeos-house-status-{release}' in cfg for release in allowed_config_releases))
        self.assertTrue(any(f'lifeos-house-status-{release}.js' in cfg for release in allowed_config_releases))
        self.assertNotIn('lifeos-house-status-v29',cfg)
        live_workflow=(ROOT/'.github/workflows/house-status-live-deploy.yml').read_text()
        self.assertIn('workflow_dispatch:',live_workflow)
        self.assertNotIn('    push:',live_workflow)
        self.assertIn('artifact_sha256:',live_workflow)
        self.assertIn('required: true',live_workflow)
        self.assertNotIn('v29',live_workflow)
        v29=ROOT/'homeassistant/releases/house-status/live/lifeos-house-status-v29.js'
        self.assertTrue(v29.exists())
        self.assertNotEqual(hashlib.sha256(v29.read_bytes()).hexdigest(),approved['artifact_sha256'])
        previous=self.manifest['previous_production_release']
        if previous=='v28':
            self.assertEqual(self.manifest['previous_production_artifact_sha256'],gate.sha(gate.V28))
        else:
            self.assertEqual(len(self.manifest['previous_production_artifact_sha256']),64)
        previous=self.manifest['previous_production_release']
        self.assertLess(int(previous[1:]),int(approved['release'][1:]))
        if previous=='v28':
            self.assertEqual(self.manifest['previous_production_artifact_sha256'],gate.sha(gate.V28))
        else:
            self.assertEqual(len(self.manifest['previous_production_artifact_sha256']),64)
        candidate=self.manifest.get('promotion_candidate')
        if approved['release']=='v28':
            self.assertIsNone(candidate)
            self.assertEqual(approved['artifact_sha256'],gate.sha(gate.V28))
        else:
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate['release'],approved['release'])
            self.assertEqual(candidate['artifact_sha256'],approved['artifact_sha256'])
            self.assertEqual(len(candidate['source_commit']),40)
            self.assertEqual(len(candidate['packager_commit']),40)
            run_id=candidate.get('dev_acceptance_run_id')
            run_number=candidate.get('dev_acceptance_run_number')
            self.assertNotEqual(run_id is not None,run_number is not None)
            self.assertGreater(run_id if run_id is not None else run_number,0)
            self.assertGreater(candidate['dev_acceptance_run_attempt'],0)
            for field in ('dev_app_sha256','dev_doorbell_sha256','doorbell_sha256'):
                self.assertEqual(len(candidate[field]),64)
        self.assertGreater(int(self.manifest['next_candidate_release'][1:]),int(approved['release'][1:]))

    def test_manual_selection_fails_closed(self):
        approved=self.manifest['approved_production']
        release=approved['release']; digest=approved['artifact_sha256']
        self.assertEqual(gate.select_release(self.manifest,release,digest)['release'],release)
        rejected=[('',digest),(release,''),('v29',digest),(release,'0'*64)]
        if release!='v28': rejected.append(('v28',digest))
        for requested,digest_value in rejected:
            with self.assertRaises(gate.GateError): gate.select_release(self.manifest,requested,digest_value)

    def test_actual_github_jobs_response_uses_job_id_logs_endpoint(self):
        # Shape returned by GET /actions/runs/{run_id}/attempts/{attempt}/jobs.
        # The jobs endpoint has no logs_url; the logs API uses job id.
        payload={
            'total_count':1,
            'jobs':[{
                'id':115829743019,
                'run_id':38557356149,
                'workflow_name':'House Status Development Deploy',
                'head_branch':'main',
                'run_url':'https://api.github.com/repos/joshant20-ops/lifeos-platform/actions/runs/38557356149',
                'run_attempt':1,
                'node_id':'CR_kwDOexample',
                'head_sha':'5864f37169f4e42e41f2257f677ffdaa58cd85f9',
                'url':'https://api.github.com/repos/joshant20-ops/lifeos-platform/actions/jobs/115829743019',
                'html_url':'https://github.com/joshant20-ops/lifeos-platform/actions/runs/38557356149/job/115829743019',
                'status':'completed',
                'conclusion':'success',
                'created_at':'2026-10-14T00:00:00Z',
                'started_at':'2026-10-14T00:00:01Z',
                'completed_at':'2026-10-14T00:01:00Z',
                'name':'deploy',
                'steps':[],
                'check_run_url':'https://api.github.com/repos/joshant20-ops/lifeos-platform/check-runs/115829743019',
                'labels':[],
                'runner_id':1,
                'runner_name':'github-hosted',
                'runner_group_id':1,
                'runner_group_name':'GitHub Actions',
            }],
        }
        candidate={'dev_acceptance_run_id':38557356149,'dev_acceptance_run_attempt':1,'source_commit':'5864f37169f4e42e41f2257f677ffdaa58cd85f9'}
        job=gate.successful_dev_deploy_job(payload,candidate)
        self.assertNotIn('logs_url',job)
        self.assertEqual(job['id'],115829743019)
        self.assertEqual(gate.github_job_logs_api_url('joshant20-ops/lifeos-platform',job),'https://api.github.com/repos/joshant20-ops/lifeos-platform/actions/jobs/115829743019/logs')
        for field,value in [('run_id',1),('run_attempt',2),('head_sha','f'*40),('conclusion','failure')]:
            changed=json.loads(json.dumps(payload))
            changed['jobs'][0][field]=value
            with self.assertRaises(gate.GateError):
                gate.successful_dev_deploy_job(changed,candidate)

    def test_dev_run_number_resolves_only_exact_successful_main_push(self):
        sha='eb2044e62ae7c4b7d4d49350df297971a1094060'
        candidate={'dev_acceptance_run_number':141,'dev_acceptance_run_attempt':1,'source_commit':sha}
        run={
            'id':39165812345,
            'run_number':141,
            'name':'House Status Development Deploy',
            'path':'.github/workflows/house-status-dev-deploy.yml',
            'event':'push',
            'head_branch':'main',
            'head_sha':sha,
            'run_attempt':1,
            'status':'completed',
            'conclusion':'success',
        }
        self.assertEqual(gate.successful_dev_run_by_number({'workflow_runs':[run]},candidate),run)
        with self.assertRaises(gate.GateError):
            gate.successful_dev_run_by_number({'workflow_runs':[run,dict(run)]},candidate)
        for field,value in [('head_sha','f'*40),('event','pull_request'),('conclusion','failure'),('run_attempt',2)]:
            changed=dict(run)
            changed[field]=value
            with self.assertRaises(gate.GateError):
                gate.successful_dev_run_by_number({'workflow_runs':[changed]},candidate)

    def test_github_job_logs_redirect_does_not_forward_authorization(self):
        api_url='https://api.github.com/repos/example/lifeos/actions/jobs/123/logs'
        signed_url='https://signed-blob.example/logs.zip?sig=secret'
        headers=Message(); headers['Location']=signed_url
        redirect=urllib.error.HTTPError(api_url,302,'Found',headers,None)
        class FakeOpener:
            def __init__(self): self.request=None
            def open(self,request,timeout):
                self.request=request
                raise redirect
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): return None
            def read(self): return b'zip-log-bytes'
        opener=FakeOpener()
        with mock.patch.object(gate.urllib.request,'build_opener',return_value=opener):
            with mock.patch.object(gate.urllib.request,'urlopen',return_value=FakeResponse()) as signed_fetch:
                result=gate.fetch_github_job_logs('github-secret',api_url)
        self.assertEqual(result,b'zip-log-bytes')
        self.assertEqual(opener.request.get_header('Authorization'),'Bearer github-secret')
        redirected_request=signed_fetch.call_args.args[0]
        self.assertEqual(redirected_request.full_url,signed_url)
        self.assertIsNone(redirected_request.get_header('Authorization'))

    def test_candidate_identity_requires_accepted_dev_run(self):
        candidate={
          'release':'v30','artifact_sha256':'a'*64,'packager_version':builder.PACKAGER_VERSION,
          'source_commit':'b'*40,'packager_commit':'b'*40,'dev_acceptance_run_id':106,'dev_acceptance_run_attempt':1,
          'dev_app_sha256':'c'*64,'dev_doorbell_sha256':'d'*64,'doorbell_sha256':'e'*64,
        }
        proposed={'schema_version':1,'approved_production':{'release':'v30','artifact_sha256':'a'*64},'promotion_candidate':candidate,'previous_production_release':'v28','previous_production_artifact_sha256':self.manifest['approved_production']['artifact_sha256'],'next_candidate_release':'v31'}
        self.assertEqual(gate.select_release(proposed,'v30','a'*64)['release'],'v30')
        import json as _json
        att={'packager_version':1,'release':'v30','source_commit':'b'*40,'packager_commit':'b'*40,'dev_app_sha256':'c'*64,'dev_doorbell_sha256':'d'*64,'live_app_sha256':'a'*64,'live_doorbell_sha256':'e'*64}
        logs=('HOUSE_STATUS_DEV_SERVED_ASSET=PASS\nHOUSE_STATUS_DEV_SERVED_SHA256='+'c'*64+'\nHOUSE_STATUS_DEV_LIVE_ACCEPTANCE=PASS\nHOUSE_STATUS_DEV_ROLLING_WEEK_MONTH_YEAR=PASS\nYEAR_POWER_DOWN_RENDERING=HIDDEN\nHOUSE_STATUS_RELEASE_ATTESTATION='+_json.dumps(att))
        run={'name':'House Status Development Deploy','path':'.github/workflows/house-status-dev-deploy.yml','event':'push','head_branch':'main','head_sha':'b'*40,'status':'completed','conclusion':'success','run_attempt':1}
        gate.validate_dev_evidence(candidate,run,logs)
        with self.assertRaises(gate.GateError): gate.validate_dev_evidence(candidate,{**run,'head_sha':'f'*40},logs)
        with self.assertRaises(gate.GateError): gate.validate_dev_evidence(candidate,run,logs.replace('YEAR_POWER_DOWN_RENDERING=HIDDEN','YEAR_POWER_DOWN_RENDERING=VISIBLE'))
        invalid=json.loads(json.dumps(proposed)); invalid['promotion_candidate']['dev_acceptance_run_id']=None
        with self.assertRaises(gate.GateError): gate.verify_manifest(invalid)
        invalid=json.loads(json.dumps(proposed)); invalid['approved_production']['artifact_sha256']='f'*64
        with self.assertRaises(gate.GateError): gate.select_release(invalid,'v30','f'*64)

    def test_dev_to_live_packaging_is_deterministic_and_reversible(self):
        manifest_before=(ROOT/'homeassistant/releases/house-status/live/approved-release.json').read_bytes()
        src=ROOT/'homeassistant/www/house-status-dev'
        app=(src/'lifeos-house-status-dev.js').read_text()
        bell=(src/'lifeos-house-status-doorbell.js').read_text()
        release='v31'
        live_bell=builder.normalize_doorbell(bell,release)
        bell_hash=builder.sha256(live_bell.encode())
        live_app=builder.normalize_app(app,release,bell_hash)
        self.assertEqual(builder.denormalize_app(live_app,release,bell_hash),app)
        self.assertEqual(builder.denormalize_doorbell(live_bell,release),bell)
        self.assertIn('LifeOSHouseStatusModules?.doorbellV31',live_app,'packaged app must look up its release-specific Doorbell module')
        self.assertIn('window.LifeOSHouseStatusModules.doorbellV31=',live_bell,'imported Doorbell module must register under the app lookup key')
        self.assertIn("await import('/local/house-status/lifeos-house-status-doorbell-v31.js?v=",live_app)
        self.assertIn("catch(error) { console.warn('House Status Doorbell module load failed',error); }",live_app)
        self.assertIn("this.period()==='year'?'':powerdownWindows.map",live_app)
        self.assertIn('periodWindow(){return [this.periodStart(),this.periodEnd()];}',live_app)
        self.assertNotIn('/local/house-status-dev/',live_app)
        with tempfile.TemporaryDirectory() as t:
            a=pathlib.Path(t)/'a'; b=pathlib.Path(t)/'b'
            cmd=['python3',str(ROOT/'homeassistant/build-house-status-release.py'),'--release',release,'--source-commit','b'*40,'--out-dir']
            first=subprocess.run(cmd+[str(a)],capture_output=True,text=True,check=True)
            second=subprocess.run(cmd+[str(b)],capture_output=True,text=True,check=True)
            self.assertEqual((a/'lifeos-house-status-v31.js').read_bytes(),(b/'lifeos-house-status-v31.js').read_bytes())
            self.assertEqual((a/'lifeos-house-status-doorbell-v31.js').read_bytes(),(b/'lifeos-house-status-doorbell-v31.js').read_bytes())
            self.assertIn('HOUSE_STATUS_RELEASE_CANDIDATE=v31:',first.stdout)
            self.assertEqual(first.stdout,second.stdout)
            self.assertEqual((ROOT/'homeassistant/releases/house-status/live/approved-release.json').read_bytes(),manifest_before,'candidate creation cannot change the approved Live pointer')
            subprocess.run(['node','--check',str(a/'lifeos-house-status-v31.js')],check=True)
            subprocess.run(['node','--check',str(a/'lifeos-house-status-doorbell-v31.js')],check=True)

    def test_energy_preflight_scope_keeps_doorbell_only_packaging_separate(self):
        builder_source=(ROOT/'homeassistant/build-house-status-release.py').read_text()
        paths={energy_scope.BUILDER,energy_scope.GOVERNANCE_TEST}
        self.assertFalse(energy_scope.energy_acceptance_required(paths,builder_source,builder_source),
                         'Doorbell-only package changes with an explicit regression do not require the unrelated long Energy endpoint')
        self.assertTrue(energy_scope.energy_acceptance_required({energy_scope.BUILDER},builder_source,builder_source),
                        'a packager change without paired governance coverage fails closed')
        changed_app=builder_source.replace('def normalize_app(','def normalize_app_changed(',1)
        self.assertNotEqual(changed_app,builder_source)
        self.assertTrue(energy_scope.energy_acceptance_required(paths,builder_source,changed_app),
                        'changes outside the Doorbell-only normalizers retain the full Energy preflight')
        shell_test=energy_scope.DOORBELL_SHELL_TEST
        changed_paths=paths|{energy_scope.APP_INPUT,shell_test}
        old_setter=energy_scope.BASE_DOORBELL_SETTER
        new_setter=energy_scope.NEW_DOORBELL_SETTER
        old_app=old_setter+"\n    const moduleOwner=LifeOSEnergyModule.owns(mode)?'energy':LifeOSHouseModule.owns(mode)?'house':LifeOSDoorbellModule.owns(mode)?'doorbell':'energy';\n    this.dataset.module=moduleOwner;\n    const stamp=o=>new Date(o.valid_from||0).getTime();"
        new_app=(new_setter+"\n    if(mode==='doorbell'){\n      this.dataset.module='doorbell';\n      const doorbell=window.LifeOSHouseStatusDevModules?.doorbell;\n      let body='';\n      try{if(doorbell?.render)body=doorbell.render(this._hass);}catch(error){console.warn(error);}\n      this._doorbellHost=this.querySelector('[data-doorbell-card]');\n      if(this._doorbellHost){\n        try{Promise.resolve(doorbell?.mount?.(this._doorbellHost,this._hass)).catch(error=>console.warn(error));}catch(error){console.warn(error);}\n      }\n      return;\n    }\n    const moduleOwner=LifeOSEnergyModule.owns(mode)?'energy':LifeOSHouseModule.owns(mode)?'house':'energy';\n    this.dataset.module=moduleOwner;\n    const stamp=o=>new Date(o.valid_from||0).getTime();")
        self.assertFalse(energy_scope.energy_acceptance_required(
            changed_paths,builder_source,builder_source,old_app,new_app),
            'a tested Doorbell-shell-only app change bypasses the unrelated long Energy endpoint')
        energy_changed=new_app.replace("const stamp=o=>","const stamp=o=>/* Energy logic changed */",1)
        self.assertTrue(energy_scope.energy_acceptance_required(
            changed_paths,builder_source,builder_source,old_app,energy_changed),
            'any change outside the Doorbell shell retains full Energy acceptance')
        self.assertTrue(energy_scope.energy_acceptance_required(
            paths|{energy_scope.APP_INPUT},builder_source,builder_source,old_app,new_app),
            'a Doorbell shell change without its regression test fails closed')
        legacy_old=old_app+"\n    this._doorbellHost=null; if(mode==='doorbell'){const host=this.querySelector('[data-doorbell-card]');}\n"
        legacy_new=legacy_old.replace("querySelector('[data-doorbell-card]')","querySelector('[data-lifeos-doorbell-camera]')",1)
        self.assertFalse(energy_scope.energy_acceptance_required(
            changed_paths,builder_source,builder_source,legacy_old,legacy_new),
            'the legacy post-render selector change is isolated from Energy after the active Doorbell early return')
        self.assertFalse(energy_scope.energy_acceptance_required({'README.md'},builder_source,builder_source))

    def test_dev_deployer_cannot_write_live_targets_and_rollback_is_pinned(self):
        deploy=(ROOT/'scripts/lifeos-deploy-house-status-dev-dashboard.sh').read_text()
        self.assertIn('HOUSE_STATUS_DEV_LIVE_ISOLATION=PASS',deploy)
        self.assertIn('PRODUCTION_AFTER',deploy)
        self.assertLess(int(self.manifest['previous_production_release'][1:]),int(self.manifest['approved_production']['release'][1:]))
        if self.manifest['previous_production_release']=='v28':
            self.assertEqual(self.manifest['previous_production_artifact_sha256'],gate.sha(gate.V28))
        else:
            self.assertEqual(len(self.manifest['previous_production_artifact_sha256']),64)
        rollback=(ROOT/'scripts/lifeos-promote-house-status-approved-release.sh').read_text()
        self.assertIn('HOUSE_STATUS_LIVE_ROLLBACK=COMPLETE',rollback)
        self.assertIn('lifeos-house-status-$RELEASE.js',rollback)
        self.assertTrue(gate.V28.exists())
        approved=self.manifest['approved_production']
        approved_path=gate.MANIFEST.parent / ('lifeos-house-status-'+approved['release']+'.js')
        if approved_path.exists():
            self.assertEqual(gate.sha(approved_path),approved['artifact_sha256'])
        else:
            self.assertEqual(approved['artifact_sha256'],self.manifest['promotion_candidate']['artifact_sha256'])

if __name__=='__main__': unittest.main(verbosity=2)
