import unittest
from unittest.mock import patch
from governor import storage_recovery_audit as audit
class StorageRecoveryAudit(unittest.TestCase):
    def test_nas_and_root_are_not_mistaken_for_ssd(self):
        for raw, expected in [(audit.SSD+" ext4","SSD"),(audit.SD+" ext4","SD_ROOT"),("nfs4","NAS"),("","UNKNOWN")]:
            with patch.object(audit,"run",return_value=raw):
                self.assertEqual(audit.device("/ignored"),expected)
    def test_untrusted_name_not_published(self):
        self.assertEqual(audit.safe_name("/homeassistant"),"homeassistant")
        self.assertEqual(audit.safe_name("private\ncontent"),"UNRECOGNIZED")
