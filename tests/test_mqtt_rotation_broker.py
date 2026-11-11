"""Disposable pinned ARM64 broker acceptance; never connects to a live broker."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from governor import mqtt_live_rotation

IMAGE = 'eclipse-mosquitto@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797'


@unittest.skipUnless(shutil.which('docker'), 'requires disposable Docker runtime')
class BrokerRotationTests(unittest.TestCase):
    def command(self, *args):
        return subprocess.check_output(args, timeout=20, text=True).strip()

    def test_retained_rotation_preserves_connected_subscriber(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Synthetic nonsecret fixture shared with an isolated container UID.
            root.chmod(0o755)
            logs = root / 'log'
            logs.mkdir(mode=0o777)
            logs.chmod(0o777)
            journal = root / 'journal'
            journal.mkdir(mode=0o700)
            (root / 'broker.conf').write_text(
                'listener 1883\nallow_anonymous true\nlog_type all\n'
                'log_dest file /proof/log/active.log\n')
            name = 'lifeos-synthetic-rotation-' + uuid.uuid4().hex
            self.command('docker', 'run', '-d', '--name', name, '--network', 'none',
                         '--memory', '128m', '--cpus', '0.5',
                         '-v', str(root) + ':/proof', IMAGE,
                         'mosquitto', '-c', '/proof/broker.conf')
            try:
                deadline = time.monotonic() + 10
                while not (logs / 'active.log').exists():
                    if time.monotonic() >= deadline:
                        self.fail('disposable broker failed to open log')
                    time.sleep(0.1)
                before = json.loads(self.command('docker', 'inspect', name))[0]['State']
                def actual_identity():
                    broker = json.loads(self.command('docker', 'inspect', name))[0]
                    state = broker['State']
                    self.assertTrue(state['Running'])
                    return (broker['Id'], broker['Image'], state['Pid'],
                            state['StartedAt'], broker['RestartCount'])

                with patch.multiple(
                    mqtt_live_rotation,
                    LOG=logs / 'active.log', JOURNAL=journal, RETAINED='retained.log',
                    preflight=lambda: ({'synthetic_fixture': True}, None, 'confirmed'),
                    broker_identity=actual_identity,
                    connection_inputs=lambda: ('synthetic', 'synthetic'),
                    health_checks=lambda *_: {'synthetic_fixture': True},
                ):
                    report = mqtt_live_rotation.run_rotation()
                self.assertEqual(report['reclaimed_bytes'], 0)
                self.assertTrue((logs / 'retained.log').exists())
                self.assertTrue((journal / 'verified.json').exists())
                after = json.loads(self.command('docker', 'inspect', name))[0]['State']
                self.assertEqual(before['Pid'], after['Pid'])
                self.assertEqual(before['StartedAt'], after['StartedAt'])
            finally:
                # The exact random fixture container, no prune or shared service.
                self.command('docker', 'rm', '-f', name)
