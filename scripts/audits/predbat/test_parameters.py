import ast,os,pathlib,re,unittest
from unittest.mock import patch
import followup as f

ROOT=pathlib.Path(__file__).parent
class ParameterTests(unittest.TestCase):
    def test_required_path_missing(self):
        with self.assertRaises(ValueError): f.required_path(None,'storage')
    def test_required_path_relative(self):
        with self.assertRaises(ValueError): f.required_path('relative','storage')
    def test_parameter_is_data_not_shell(self):
        value='/synthetic/$(not-a-command);literal'
        self.assertEqual(f.required_path(value,'storage'),value)
    def test_focus_rejects_shell_fragments(self):
        with patch.dict(os.environ,{'PREDBAT_FOCUS_IMAGE_ID':'x; command'},clear=True),self.assertRaises(ValueError):
            f.settings({'inventory':[]})
    def test_roles_from_private_evidence(self):
        with patch.dict(os.environ,{},clear=True):
            f.settings({'inventory':[{'short_id':'000000000001','disposition':'KEEP'},{'short_id':'000000000002','disposition':'HOLD'}]})
            self.assertEqual(f.PINS,{'000000000001'});self.assertEqual(f.EXPECTED,{'000000000002'})
    def test_growth_baseline_from_input(self):
        d={'growth':[{'path':'/synthetic/logs','allocated_bytes_by_child':'1234\t/synthetic/logs\n'}]}
        self.assertEqual(f.growth_targets(d),[('/synthetic/logs',1234)])
    def test_missing_growth_baseline_unknown(self):
        self.assertEqual(f.growth_targets({'growth':[{'path':'/synthetic/logs'}]}),[('/synthetic/logs',None)])
    def test_growth_limit_preserved(self):
        self.assertEqual(len(f.growth_targets({'growth':[{'path':f'/synthetic/{i}'} for i in range(9)]})),3)
    def test_embedded_python_matches_tested_module(self):
        shell=(ROOT/'Predbat_Followup_ReadOnly_2026-11-23.sh').read_text()
        body=shell.split("cat <<'PY_PAYLOAD'\n",1)[1].split('\nPY_PAYLOAD\n',1)[0]
        self.assertEqual(body,(ROOT/'followup.py').read_text().rstrip());ast.parse(body)
    def test_no_shell_execution_in_python(self):
        tree=ast.parse((ROOT/'followup.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                self.assertFalse(isinstance(node.func,ast.Name) and node.func.id in {'eval','exec'})
                self.assertFalse(any(k.arg=='shell' and not(isinstance(k.value,ast.Constant) and k.value.value is False) for k in node.keywords))
    def test_wrapper_no_remote_interpolation_or_eval(self):
        s=(ROOT/'Predbat_Followup_ReadOnly_2026-11-23.sh').read_text()
        self.assertNotIn('eval ',s);self.assertNotIn('scp ',s);self.assertNotIn('ssh ',s)
        for expected in ('timeout 180s','ulimit -v 393216','nice -n 19','umask 077'):
            self.assertIn(expected,s)
    def test_published_sources_have_no_private_addresses_or_accounts(self):
        for p in ROOT.iterdir():
            if not p.is_file():continue
            s=p.read_text()
            self.assertIsNone(re.search(r'\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)\b',s),p.name)
            self.assertIsNone(re.search(r'/home/[A-Za-z][A-Za-z0-9_-]*/',s),p.name)
            self.assertNotIn('PRIVATE '+'KEY-----',s)

if __name__=='__main__': unittest.main()
