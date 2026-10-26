import importlib.util
from pathlib import Path
import unittest
p=Path(__file__).resolve().parents[1]/"scripts/lifeos-restic-restore-rehearsal.py"
spec=importlib.util.spec_from_file_location("restore_capacity",p)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class RestoreCapacity(unittest.TestCase):
    def test_blocks_unknown_and_oversized_restore(self):
        for stats in [{},{"total_size":True},{"total_size":-1},{"total_size":10*1024**3}]:
            with self.assertRaises(RuntimeError): mod.require_capacity(stats,6*1024**3)
    def test_reserves_headroom(self):
        mod.require_capacity({"total_size":1024},6*1024**3)
