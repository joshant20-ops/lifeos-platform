import unittest

from governor.backup_duplicate_audit import compare, select_sample


class DuplicateAuditTests(unittest.TestCase):
    def test_requires_identical_whole_group_and_preserves_newer_comparator(self):
        entry = {"archive_path": "group-1/config", "mode": 0o600,
                 "bytes": 10, "sha256": "synthetic-a", "allocated_bytes": 4096}
        other = {**entry, "sha256": "synthetic-b"}
        results = compare([(0, "20260501", "earlier", [entry]),
                           (0, "20260502", "newer", [entry]),
                           (1, "20260503", "different_family", [entry]),
                           (0, "20260504", "different_bytes", [other])])
        candidates, allocated, repeated = results
        self.assertEqual((allocated, repeated), (4096, 1))
        self.assertEqual(candidates[0]["original_group"], "earlier")
        self.assertEqual(candidates[0]["identical_group"], "newer")
        self.assertEqual(candidates[0]["dependency_and_hold_status"], "unverified")

    def test_equal_sizes_are_candidate_selection_only(self):
        records = {f"a-2026050{i}-120000": {"bytes": 10, "files": 1} for i in (1, 2, 3)}
        result = select_sample(records, ["a", "b"])
        self.assertEqual([item[1] for item in result], ["20260501120000", "20260503120000"])
