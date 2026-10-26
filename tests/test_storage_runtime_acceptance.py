import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from governor import storage_runtime_acceptance as audit
class DisposableWriteProbe(unittest.TestCase):
    def test_roundtrip_and_cleanup_through_container_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            row={"Mounts":[{"Destination":tmp,"Source":tmp,"RW":True,"Type":"bind"}]}
            def local_exec(args,timeout=15):
                assert args[:3]==["docker","exec","fixture"]
                return subprocess.run(args[3:],capture_output=True,text=True,timeout=timeout,check=True)
            with patch.object(audit,"device",return_value="SSD"),patch.object(audit,"command",side_effect=local_exec):
                self.assertTrue(audit.write_probe("fixture",tmp,row))
            self.assertEqual(list(target.iterdir()),[])
    def test_wrong_device_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            row={"Mounts":[{"Destination":"/config","Source":tmp,"RW":True,"Type":"bind"}]}
            with patch.object(audit,"device",return_value="SD_ROOT"),patch.object(audit,"command") as execute:
                with self.assertRaises(RuntimeError): audit.write_probe("fixture","/config",row)
                execute.assert_not_called()
