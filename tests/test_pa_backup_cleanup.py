import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pa_cleanup', ROOT/'scripts/lifeos_pa_backup_cleanup.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.root=self.base/'automation'/'backups';self.root.mkdir(parents=True)
        self.name='pa_escalation_v1_20200101_000000'
        self.make(self.name)
        self.fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        self.addCleanup(os.close,self.fd)

    def make(self,name):
        p=self.root/name;p.mkdir()
        payloads=({'lovelace.dashboard_homelab':'{}','lifeos_pa_lifecycle.yaml':'command_line: []','pa_escalations.json':'[]'}
                  if name.startswith('pa_escalation') else
                  {'synthetic__open_loops.json':'[]','synthetic__pa_latest_summary.json':'{}',
                   'synthetic__lifeos_pa_lifecycle.yaml':'command_line: []',
                   'synthetic__lifeos_pa_lifecycle_export.py':'pass\n'})
        for leaf,data in payloads.items():(p/leaf).write_text(data)
        return p

    def test_unknown_family_rejected(self):
        self.assertIsNone(m.family('../live-data'))
        with self.assertRaises(ValueError):m.inspect(self.fd,'unknown')

    def test_unknown_member_holds_generation(self):
        (self.root/self.name/'PROTECTED').write_text('hold')
        with self.assertRaises(ValueError):m.inspect(self.fd,self.name)

    def test_symlink_member_rejected(self):
        f=self.root/self.name/'pa_escalations.json';f.unlink();f.symlink_to(self.base/'missing')
        with self.assertRaises(ValueError):m.inspect(self.fd,self.name)

    def test_hardlink_member_rejected(self):
        os.link(self.root/self.name/'pa_escalations.json',self.base/'alias')
        with self.assertRaises(ValueError):m.inspect(self.fd,self.name)

    def test_generation_symlink_rejected(self):
        link='pa_escalation_v1_20200102_000000';(self.root/link).symlink_to(self.root/self.name)
        with self.assertRaises(OSError):m.inspect(self.fd,link)

    def test_birth_time_and_all_ctimes_required(self):
        record=m.inspect(self.fd,self.name)
        with patch.object(m,'CUTOFF',int(time.time())+10):
            self.assertTrue(m.old(record,1));self.assertFalse(m.old(record,0))
            changed=copy.deepcopy(record);next(iter(changed['files'].values()))['st_ctime_ns']=(m.CUTOFF+1)*10**9
            self.assertFalse(m.old(changed,1))

    def test_isolated_file_restore_and_hash_verification(self):
        record=m.inspect(self.fd,self.name)
        seen=[]
        hashes=m.restore_check(self.root,record,self.base/'restored',lambda data:seen.append(data))
        self.assertEqual(len(hashes),3);self.assertEqual(len(seen),1)
        self.assertEqual((self.base/'restored'/'pa_escalations.json').read_bytes(),b'[]')

    def test_bad_json_restore_rejected(self):
        (self.root/self.name/'pa_escalations.json').write_text('broken')
        record=m.inspect(self.fd,self.name)
        with self.assertRaises(ValueError):m.restore_check(self.root,record,self.base/'restored',lambda data:None)

    def test_exact_generation_deletion_and_journal(self):
        record=m.inspect(self.fd,self.name)
        with open(self.base/'journal','w+') as log:
            m.remove_generation(self.fd,record,log);log.seek(0)
            rows=[json.loads(line) for line in log]
        self.assertFalse((self.root/self.name).exists())
        self.assertEqual(rows[0]['event'],'intent')
        self.assertEqual(sum(r['event']=='unlinked' for r in rows),3)
        self.assertEqual(rows[-1]['event'],'generation_removed')

    def test_changed_file_never_unlinked(self):
        record=m.inspect(self.fd,self.name)
        (self.root/self.name/'pa_escalations.json').write_text('[1]')
        with open(self.base/'journal','w') as log:
            with self.assertRaises(ValueError):m.remove_generation(self.fd,record,log)
        self.assertEqual(len(list((self.root/self.name).iterdir())),3)

    def test_reference_access_error_not_silently_ignored(self):
        with patch.object(m.os,'walk',side_effect=PermissionError('synthetic')):
            with self.assertRaises(PermissionError):m.references([self.base])

    def test_reference_match_preserved(self):
        r=self.base/'records';r.mkdir()
        (r/'transaction.json').write_text(json.dumps({'backup':self.name}))
        self.assertIn(self.name,m.references([r]))

    def test_operational_dry_run_and_execution(self):
        for k in ('pa_escalation_v1','pa_ha_dashboard'):
            for i in range(1,5):
                name=f'{k}_2020010{i}_010101'
                self.make(name)
        # Existing initial generation is oldest; explicitly protect it.
        audit=self.base/'audit'
        argv=['cleanup','--root',str(self.root),'--audit-dir',str(audit),'--execute','--protect',self.name]
        health=([{'Id':'synthetic','Name':'/homeassistant','State':{'Running':True},'Config':{},'Mounts':[]}],{'synthetic':('image','start')})
        def birth(root,names):return {name:i+1 for i,name in enumerate(sorted(names))}
        with patch.object(m.os,'geteuid',return_value=0),patch.object(m,'health',return_value=health),\
             patch.object(m,'references',return_value=set()),patch.object(m,'active_generations',return_value=set()),\
             patch.object(m,'births',side_effect=birth),patch.object(m,'call',return_value=b''),\
             patch.object(m,'CUTOFF',int(time.time())+100),patch.object(m,'volume',return_value={'capacity_bytes':10**15,'available_bytes':10**12,'available_inodes':10**6}),\
             patch.object(m,'cleanup_lock',return_value=open(self.base/'lock','a')),patch.object(m.sys,'argv',argv),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(),0)
        summary=json.loads((audit/'summary.json').read_text())
        self.assertEqual(summary['deletions_executed'],4)
        self.assertEqual(summary['preserved_recovery_generations'],4)
        self.assertTrue((self.root/self.name).is_dir())
        self.assertEqual(summary['protected_service_health'],'PASS')

if __name__=='__main__':unittest.main()
