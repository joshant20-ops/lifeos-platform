import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cleanup", HERE / "cleanup.py")
cleanup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = cleanup
SPEC.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def test_all_explicit_protections_are_protected(self):
        for path in cleanup.PROTECTED:
            self.assertTrue(cleanup.protected(path))
            self.assertTrue(cleanup.protected(path / "nested"))

    def test_parent_of_protected_path_is_also_refused(self):
        self.assertTrue(cleanup.protected(Path("/home/joshan")))

    def test_safe_category_cannot_target_protected_path(self):
        plan = {"entries": [{"path": "/home/joshan/.ssh", "category": "SAFE_TO_REMOVE"}]}
        self.assertTrue(cleanup.validate(plan))

    def test_review_plan_is_valid_and_non_removable(self):
        plan = {"entries": [{"path": "/tmp/example", "category": "REVIEW"}]}
        self.assertEqual(cleanup.validate(plan), [])


if __name__ == "__main__":
    unittest.main()
