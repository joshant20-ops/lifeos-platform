import unittest
from governor.matter_storage_recovery import original_container
class OriginalMatterIdentity(unittest.TestCase):
    def test_only_recorded_original_full_identity(self):
        cid="a"*64
        self.assertTrue(original_container({"Id":cid},cid[:12]+"\n"))
        self.assertFalse(original_container({"Id":"b"*64},cid[:12]))
        self.assertFalse(original_container({"Id":cid},""))
        self.assertFalse(original_container({"Id":cid},"a;untrusted"))
