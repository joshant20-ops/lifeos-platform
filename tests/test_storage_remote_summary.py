import ast
import datetime
import importlib.util
import importlib.machinery
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/audits/storage/worker.py'
spec = importlib.util.spec_from_file_location('storage_summary', SOURCE)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def config(root='/synthetic'):
    return {'storage_root': root, 'automation_root': root + '/automation',
            'inventory_tsv': root + '/inventory.tsv', 'predbat_report': root + '/report.json',
            'protected_container_names': ['dns', 'automation', 'broker'], 'max_cache_age_seconds': 3600}


def report():
    rows = [{'id': 'sha256:' + f'{i:064x}', 'disposition': 'KEEP' if i < 5 else 'HOLD'} for i in range(1, 25)]
    return {'inventory': rows, 'docker_df_image_rows': []}


class FakeDocker:
    def __init__(self, data, referenced=None, tagged=None, changed=False):
        self.data, self.referenced, self.tagged = data, referenced, tagged
        self.changed, self.calls, self.list_count = changed, [], 0

    def get(self, endpoint):
        self.calls.append(endpoint)
        if endpoint == '/containers/json?all=1':
            self.list_count += 1
            rows = [{'Id': f'{i:064x}', 'ImageID': 'sha256:' + f'{i:064x}', 'Names': [name], 'State': 'running'}
                    for i, name in enumerate(['/dns', '/automation', '/broker'], 1)]
            if self.referenced:
                rows.append({'Id': 'f' * 64, 'ImageID': self.referenced, 'Names': ['/stopped'], 'State': 'exited'})
            if self.changed and self.list_count > 1: rows[0]['State'] = 'exited'
            return rows
        if endpoint.startswith('/containers/'):
            identity=endpoint[len('/containers/'):-len('/json')]
            return {'Id':identity,'Image':'sha256:'+identity,'State':{'Running':True,'StartedAt':'synthetic'},'RestartCount':0}
        identity = endpoint[len('/images/'):-len('/json')]
        return {'Id': identity, 'RepoTags': ['hold'] if identity == self.tagged else [], 'RepoDigests': []}


class StorageSummaryTests(unittest.TestCase):
    def test_public_default(self): self.assertEqual(w.public(w.empty())['eligible_for_deletion_bytes'], 0)
    def test_public_rejects_private_key(self):
        d=w.empty(); d['private_path']='secret'
        with self.assertRaises(ValueError): w.public(d)
    def test_public_rejects_free_text(self):
        d=w.empty(); d['status']='private detail'
        with self.assertRaises(ValueError): w.public(d)
    def test_public_rejects_deletion(self):
        d=w.empty(); d['eligible_for_deletion_bytes']=1
        with self.assertRaises(ValueError): w.public(d)
    def test_public_rejects_bool_number(self):
        d=w.empty(); d['backup_groups']=True
        with self.assertRaises(ValueError): w.public(d)
    def test_public_negative_headroom(self):
        d=w.empty(); d['headroom_bytes']=-1024
        self.assertEqual(w.public(d)['headroom_bytes'], -1024)
    def test_public_rejects_overflow(self):
        d=w.empty(); d['backup_groups']=2**61
        with self.assertRaises(ValueError): w.public(d)
    def test_missing_config_field(self):
        c=config(); del c['storage_root']
        with patch.object(w,'read_json',return_value=(c,None)), self.assertRaises(ValueError): w.configuration()
    def test_reject_relative_config_path(self):
        c=config(); c['inventory_tsv']='relative'
        with patch.object(w,'read_json',return_value=(c,None)), self.assertRaises(ValueError): w.configuration()
    def test_valid_config(self):
        c=config()
        with patch.object(w,'read_json',return_value=(c,None)): self.assertEqual(w.configuration(),c)
    def test_reject_command_in_container_name(self):
        c=config(); c['protected_container_names'][0]='x;cmd'
        with patch.object(w,'read_json',return_value=(c,None)), self.assertRaises(ValueError): w.configuration()
    def test_reject_unbounded_cache_age(self):
        c=config(); c['max_cache_age_seconds']=10**9
        with patch.object(w,'read_json',return_value=(c,None)), self.assertRaises(ValueError): w.configuration()
    def test_docker_mutation_endpoint_rejected(self):
        for endpoint in ['/containers/create','/system/prune','/images/create','/containers/a/start']:
            with self.assertRaises(ValueError): w.DockerReadOnly().get(endpoint)
    def test_all_container_states_counted(self):
        r=report(); candidate=r['inventory'][-1]['id']; docker=FakeDocker(r,referenced=candidate); d=w.empty()
        with patch.object(w,'read_json',return_value=(r,None)), patch.object(w,'age',return_value=0): w.predbat(config(),d,docker)
        self.assertEqual(d['predbat_unreferenced_untagged'],19)
        self.assertEqual(d['eligible_for_deletion_bytes'],0)
    def test_tag_is_hold(self):
        r=report(); docker=FakeDocker(r,tagged=r['inventory'][-1]['id']); d=w.empty()
        with patch.object(w,'read_json',return_value=(r,None)), patch.object(w,'age',return_value=0): w.predbat(config(),d,docker)
        self.assertEqual(d['predbat_unreferenced_untagged'],19)
    def test_container_change_reported(self):
        r=report(); d=w.empty()
        with patch.object(w,'read_json',return_value=(r,None)), patch.object(w,'age',return_value=0): w.predbat(config(),d,FakeDocker(r,changed=True))
        self.assertFalse(d['containers_unchanged']); self.assertEqual(d['predbat_status'],'INVALID')
    def test_protected_restart_reported(self):
        r=report(); d=w.empty(); docker=FakeDocker(r); original=docker.get
        def changed(endpoint):
            data=original(endpoint)
            if endpoint.startswith('/containers/') and endpoint != '/containers/json?all=1' and docker.list_count>1:
                data['RestartCount']=1
            return data
        docker.get=changed
        with patch.object(w,'read_json',return_value=(r,None)),patch.object(w,'age',return_value=0): w.predbat(config(),d,docker)
        self.assertFalse(d['containers_unchanged'])
    def test_stale_unique_not_published(self):
        r=report(); d=w.empty()
        with patch.object(w,'read_json',return_value=(r,None)), patch.object(w,'age',return_value=8000): w.predbat(config(),d,FakeDocker(r))
        self.assertEqual(d['predbat_status'],'STALE'); self.assertEqual(d['predbat_cached_unique_bytes'],-1)
    def test_image_identity_mismatch_fails(self):
        r=report(); docker=FakeDocker(r); original=docker.get
        docker.get=lambda endpoint: original(endpoint) if endpoint.startswith('/containers') else {'Id':'wrong'}
        with patch.object(w,'read_json',return_value=(r,None)),patch.object(w,'age',return_value=0),self.assertRaises(ValueError): w.predbat(config(),w.empty(),docker)
    def test_unique_requires_every_candidate(self):
        self.assertEqual(w.unique_estimate({'docker_df_image_rows':[]},['a'*12]),-1)
    def test_unique_is_estimate_only(self):
        line='<none> <none> aaaaaaaaaaaa today 8MB 3MB 5MB 0'
        self.assertEqual(w.unique_estimate({'docker_df_image_rows':[line]},['a'*12]),5000000)
    def test_profile_reuses_existing_parsers(self):
        with tempfile.TemporaryDirectory() as root:
            p=pathlib.Path(root); c=config(root); inv=p/'inventory.tsv'
            today=datetime.date.today().isoformat()
            inv.write_text(f'100\t{today}\t{root}/automation/backups/group/file.yaml\n200\t{today}\t{root}/automation/repair_lifecycle/snapshots/file.json\n')
            d=w.empty()
            with patch.object(w,'LIB',ROOT): w.inventories(c,d)
            self.assertEqual((d['backup_groups'],d['backup_logical_bytes'],d['snapshot_logical_bytes']),(1,100,200))
            self.assertEqual(d['eligible_for_deletion_bytes'],0)
    def test_resource_deferral_does_not_read_sources(self):
        fs=SimpleNamespace(f_bavail=90,f_frsize=4096,f_blocks=100,f_favail=50)
        with patch.object(w.os,'statvfs',return_value=fs),patch.object(w,'resource_safe',return_value=False),patch.object(w,'inventories') as inv,patch.object(w,'predbat') as pred:
            d=w.collect(config()); inv.assert_not_called(); pred.assert_not_called()
        self.assertEqual(d['status'],'DEFERRED')
    def test_below_reserve_skips_large_parser(self):
        fs=SimpleNamespace(f_bavail=1,f_frsize=4096,f_blocks=100,f_favail=50)
        with patch.object(w.os,'statvfs',return_value=fs),patch.object(w,'resource_safe',return_value=True),patch.object(w,'inventories') as inv,patch.object(w,'predbat'):
            d=w.collect(config()); inv.assert_not_called()
        self.assertLess(d['headroom_bytes'],0)
    def test_no_shell_subprocess(self):
        for node in ast.walk(ast.parse(SOURCE.read_text())):
            if isinstance(node,ast.Call):
                self.assertFalse(any(k.arg=='shell' for k in node.keywords))
    def test_unit_is_readonly_and_bounded(self):
        s=(ROOT/'scripts/audits/storage/lifeos-storage-audit.service').read_text()
        for value in ['ProtectSystem=strict','PrivateNetwork=yes','CPUQuota=20%','MemoryMax=384M','TimeoutStartSec=110','RestrictAddressFamilies=AF_UNIX']:
            self.assertIn(value,s)
        self.assertNotIn('[Install]',s)
    def test_workflow_no_checkout_or_installer(self):
        s=(ROOT/'.github/workflows/storage-readonly-summary.yml').read_text()
        s=s.split('  audit:',1)[1]
        for value in ['actions/checkout','install.sh','git fetch','workflow_call','inputs.','docker ']: self.assertNotIn(value,s)
        self.assertIn('STORAGE_READONLY_AUDIT_ENABLED',s)
        self.assertIn('lifeos-pi5-control',s)
    def test_installer_does_not_activate_or_grant_sudo(self):
        s=(ROOT/'scripts/audits/storage/install.sh').read_text()
        for value in ['systemctl start','systemctl restart','systemctl enable','NOPASSWD','docker pull']: self.assertNotIn(value,s)
        self.assertIn('RUNNER_HAS_UNRESTRICTED_DOCKER_ACCESS',s)
    def test_comment_trigger_is_exact_owner_scoped_existing_issue(self):
        s=(ROOT/'.github/workflows/storage-readonly-summary.yml').read_text().split('  audit:',1)[1]
        for value in ["github.event.issue.number == 2072", "!github.event.issue.pull_request", "github.event.comment.body == '/storage-audit-summary'", 'github.actor == github.repository_owner', 'github.triggering_actor == github.repository_owner', "github.ref == 'refs/heads/main'", 'github.run_attempt == 1']:
            self.assertIn(value,s)
    def test_gateway_fixed_branch_skips_repository_execution(self):
        p=ROOT/'homelab/live/usr/local/sbin/lifeos-deploy-gateway'
        source=p.read_text(); tree=ast.parse(source)
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        self.assertIn("operation == 'storage-audit-summary'",ast.unparse(main))
        self.assertLess(source.index("if operation == 'storage-audit-summary':"),source.index('    head = preflight()'))
        self.assertIn("'-I', '-B', str(installed), '--request'",source)
    def test_gateway_arguments_rejected(self):
        loader=importlib.machinery.SourceFileLoader('storage_gateway',str(ROOT/'homelab/live/usr/local/sbin/lifeos-deploy-gateway'))
        spec=importlib.util.spec_from_loader('storage_gateway',loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
        self.assertEqual(m.parse_request(['storage-audit-summary']),('storage-audit-summary',[]))
        for argv in [['storage-audit-summary','/arbitrary'],['storage-audit-summary','; command']]:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error: m.parse_request(argv)
            self.assertEqual(error.exception.code,64)
    def test_request_requires_root_boundary(self):
        with patch.object(w.os,'geteuid',return_value=1001),patch.object(w.subprocess,'run') as run,self.assertRaises(ValueError): w.request()
        run.assert_not_called()
    def test_fresh_cache_does_not_start_service(self):
        with patch.object(w.os,'geteuid',return_value=0),patch.object(w,'age',return_value=10),patch.object(w,'read_json',return_value=(w.empty(),None)),patch.object(w.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()): w.request()
        run.assert_not_called()
    def test_symlink_report_refused(self):
        with tempfile.TemporaryDirectory() as root:
            p=pathlib.Path(root);(p/'source').write_text('{}');(p/'link').symlink_to(p/'source')
            with self.assertRaises(OSError): w.read_json(p/'link')


if __name__=='__main__': unittest.main()
