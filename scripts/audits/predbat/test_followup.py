import contextlib,io,json,pathlib,tarfile,tempfile,unittest
import followup as f
from unittest.mock import patch
from types import SimpleNamespace

ID='0123456789ab'+'0'*52
ROW={'short_id':ID[:12],'id':'sha256:'+ID,'version':'v1.2.3','tags':[],'registry_digests':[]}
class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(f.os.environ,{'PREDBAT_STORAGE_ROOT':'/synthetic/storage','PREDBAT_TRANSACTION_ROOT':'/synthetic/transactions'},clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        f.TRANSACTION_ROOT='/synthetic/transactions'
    def matches(self,text): return f.candidate_matches(text,[ROW])
    def test_full_id(self): self.assertEqual(self.matches('sha256:'+ID)[0]['kinds'],['config_id'])
    def test_short_id(self): self.assertEqual(self.matches(ID[:12])[0]['short_id'],ID[:12])
    def test_case(self): self.assertTrue(self.matches(ID.upper()))
    def test_version_without_v(self): self.assertTrue(self.matches('image=1.2.3'))
    def test_version_with_v(self): self.assertTrue(self.matches('v1.2.3'))
    def test_version_collision(self): self.assertEqual(self.matches('v1.2.30'),[])
    def test_embedded_version(self): self.assertEqual(self.matches('releaseX1.2.3'),[])
    def test_shorter_hex(self): self.assertEqual(self.matches(ID[:11]),[])
    def test_other_id(self): self.assertEqual(self.matches('a'*64),[])
    def test_dotenv_relevant(self): self.assertEqual(f.priority('/synthetic/stacks/predbat/.env'),'configuration_or_recovery_record')
    def test_extensionless_rollback(self): self.assertEqual(f.priority('/usr/local/sbin/lifeos-rollback'),'configuration_or_recovery_record')
    def test_font_irrelevant(self): self.assertEqual(f.priority('/synthetic/stacks/ui/fonts/a.woff2'),'irrelevant_binary')
    def test_archive_priority(self): self.assertEqual(f.priority('/backup/configuration.tar'),'configuration_archive')
    def test_transaction_priority(self): self.assertEqual(f.priority('/synthetic/transactions/a/backups/target'),'transaction_record')
    def test_generic_not_dependency(self): self.assertEqual(f.category('/docs/README.md','Predbat is mentioned',[]),'generic_predbat_mention')
    def test_ambiguous_version(self): self.assertEqual(f.category('/config.json','version 1.2.3',self.matches('1.2.3')),'ambiguous_version_only_reference')
    def test_history_not_live(self): self.assertEqual(f.category('/repo/retired/compose.yml','predbat image '+ID,self.matches(ID)),'historical_reference')
    def test_archive_read_no_extract(self):
        with tempfile.TemporaryDirectory() as root:
            p=pathlib.Path(root)/'configuration.tar'
            with tarfile.open(p,'w') as t:
                raw=('image: predbat:'+ID).encode(); m=tarfile.TarInfo('predbat/docker-compose.yml');m.size=len(raw);t.addfile(m,io.BytesIO(raw))
                raw=b'private document';m=tarfile.TarInfo('media/original.pdf');m.size=len(raw);t.addfile(m,io.BytesIO(raw))
            out=io.StringIO()
            with contextlib.redirect_stdout(out): f.archive_child(str(p))
            packet=json.loads(out.getvalue());self.assertEqual(len(packet['members']),1)
            self.assertEqual(list(pathlib.Path(root).iterdir()),[p])
    def test_symlink_not_read(self):
        with tempfile.TemporaryDirectory() as root:
            p=pathlib.Path(root);(p/'target').write_text('x');(p/'link').symlink_to(p/'target')
            with self.assertRaises(ValueError): f.read_small(p/'link')
    def test_schema_rejects_missing_inventory(self):
        with self.assertRaises(ValueError): f.check_schema({})
    def test_schema_rejects_incomplete_set(self):
        d={k:[] for k in ('inventory','reference_hits','coverage_gaps','reference_roots','errors','growth')}
        d['inventory']=[ROW]
        with self.assertRaises(ValueError): f.check_schema(d)
    def test_synthetic_hit_reconciliation_end_to_end(self):
        # Entirely synthetic; never read target runtime, Docker or real documents.
        with tempfile.TemporaryDirectory() as root:
            p=pathlib.Path(root); rows=[]
            for i in range(24):
                short=f'{i+1:012x}'
                rows.append({'short_id':short,'id':'sha256:'+short+'0'*52,'version':None,'tags':[],'registry_digests':[],'disposition':'KEEP' if i<4 else 'HOLD'})
            hits=[]
            for i in range(11):
                q=p/f'reference{i}.md'; q.write_text('Predbat guidance' if i<7 else 'unrelated text')
                hits.append({'path':str(q),'matched_tokens':[],'generic_predbat_reference':i<7})
            d={'inventory':rows,'reference_hits':hits,'coverage_gaps':[],'reference_roots':[str(p)],
               'errors':[{'error':'log_stat_inaccessible'}]*3,'growth':[],'containers':[]}
            input=p/'input.json';input.write_text(json.dumps(d));out=io.StringIO()
            def fake(args,timeout=15):
                if args[:3]==['docker','ps','-aq']: return {'ok':True,'stdout':'','error':None}
                if args[:3]==['docker','image','inspect']:
                    return {'ok':True,'stdout':json.dumps({'id':args[-1],'tags':[],'registry_digests':[],'total_size_bytes':1}),'error':None}
                return {'ok':False,'stdout':'','error':'synthetic_no_access'}
            fs=SimpleNamespace(f_bavail=100,f_frsize=4096,f_blocks=1000)
            with patch.object(f,'command',side_effect=fake),patch.object(f.os,'statvfs',return_value=fs),patch.object(f.os,'scandir',side_effect=PermissionError),contextlib.redirect_stdout(out):
                f.main(str(input),root)
            s=json.loads((p/'summary.json').read_text())
            self.assertEqual(s['original_hit_count'],11)
            self.assertEqual(s['original_candidate_token_hit_count'],0)
            self.assertEqual(s['original_hit_class_counts']['generic_predbat_mention'],7)
            self.assertEqual(s['original_hit_class_counts']['unrelated_reference'],4)
            self.assertEqual(s['approved_deletion_allowlist'],[])
            self.assertEqual(s['collector_error_counts']['log_stat_inaccessible'],3)

if __name__=='__main__':unittest.main()
