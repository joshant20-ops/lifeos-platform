import unittest
from governor import smart_native_repair as repair

class SmartRepairSafety(unittest.TestCase):
    def test_refuses_unknown_drive_before_configuration(self):
        for protocol, model, capacity in [("NVMe",repair.MODEL,160_000_000_000),
                                           ("ATA","OTHER",160_000_000_000),
                                           ("ATA",repair.MODEL,1_000_000_000)]:
            with self.assertRaises(RuntimeError):
                repair.validate_identity({"model_name":model,"device":{"protocol":protocol},
                                          "user_capacity":{"bytes":capacity}})

    def test_preserves_comments_and_standby_policy(self):
        source = "# retain operator comments\n" + repair.DEFAULT + "\n"
        value = repair.replacement(source,"/dev/disk/by-id/usb-fixture")
        self.assertTrue(value.startswith("# retain operator comments\n"))
        self.assertIn(" -d sat -a -n standby ",value)
        self.assertNotIn("DEVICESCAN",value)
        self.assertEqual(repair.replacement(value,"/dev/disk/by-id/usb-fixture"),value)

    def test_refuses_to_replace_custom_rules_or_injected_identity(self):
        for source, target in [(repair.DEFAULT+"\n/dev/other -a", "/dev/disk/by-id/usb-fixture"),
                               (repair.DEFAULT, "/dev/disk/by-id/usb-fixture -d sntjmicron")]:
            with self.assertRaises(RuntimeError): repair.replacement(source,target)

    def test_exports_health_without_device_identifiers(self):
        result = repair.health_summary({"serial_number":"PRIVATE", "smart_status":{"passed":False},
                    "ata_smart_attributes":{"table":[{"id":197,"raw":{"value":3}}]}})
        self.assertFalse(result["overall_passed"])
        self.assertEqual(result["pending_sectors"],3)
        self.assertNotIn("PRIVATE",str(result))
