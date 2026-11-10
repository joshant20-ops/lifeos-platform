"""Disposable pinned ARM64 broker acceptance; never connects to a live broker."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

from governor.mqtt_retained_rotation import rotate

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
            subscriber = None
            try:
                def execute(*args):
                    return self.command('docker', 'exec', name, *args)
                deadline = time.monotonic() + 10
                while not (logs / 'active.log').exists():
                    if time.monotonic() >= deadline:
                        self.fail('disposable broker failed to open log')
                    time.sleep(0.1)
                before = json.loads(self.command('docker', 'inspect', name))[0]['State']
                subscriber = subprocess.Popen(
                    ['docker', 'exec', name, 'mosquitto_sub', '-h', '127.0.0.1',
                     '-t', 'lifeos/synthetic/rotation', '-C', '2', '-W', '15'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                # Prove subscriber registration before publishing; no production data.
                deadline = time.monotonic() + 5
                while 'lifeos/synthetic/rotation' not in (logs / 'active.log').read_text():
                    if time.monotonic() >= deadline:
                        self.fail('subscriber registration timed out')
                    time.sleep(0.1)
                execute('mosquitto_pub', '-h', '127.0.0.1', '-t',
                        'lifeos/synthetic/rotation', '-m', 'before')
                self.assertTrue(select.select([subscriber.stdout], [], [], 5)[0])
                self.assertEqual(subscriber.stdout.readline().strip(), 'before')
                def writer(info):
                    # Root inside disposable container only; inspect descriptors,
                    # not log contents. PID 1 is the fixed image broker process.
                    descriptors = execute('sh', '-c',
                        'for f in /proc/1/fd/*; do stat -Lc "%d:%i" "$f" 2>/dev/null || :; done')
                    return f'{info.st_dev}:{info.st_ino}' in descriptors.splitlines()
                def reopen():
                    execute('mosquitto_signal', '-p', '1', 'log-rotate')
                def verify(old, new):
                    self.assertFalse(writer(old))
                    self.assertTrue(writer(new))
                    retained_size = (logs / 'retained.log').stat().st_size
                    execute('mosquitto_pub', '-h', '127.0.0.1', '-t',
                            'lifeos/synthetic/rotation', '-m', 'after')
                    self.assertTrue(select.select([subscriber.stdout], [], [], 5)[0])
                    self.assertEqual(subscriber.stdout.readline().strip(), 'after')
                    self.assertEqual(subscriber.wait(timeout=5), 0)
                    self.assertEqual((logs / 'retained.log').stat().st_size, retained_size)
                    after = json.loads(self.command('docker', 'inspect', name))[0]['State']
                    self.assertEqual(before['Pid'], after['Pid'])
                    self.assertEqual(before['StartedAt'], after['StartedAt'])
                    self.assertTrue(after['Running'])
                report = rotate(logs, 'active.log', 'retained.log', journal,
                                lambda: None, writer, reopen, verify)
                self.assertEqual(report['reclaimed_bytes'], 0)
            finally:
                if subscriber is not None and subscriber.poll() is None:
                    subscriber.terminate()
                    subscriber.communicate(timeout=5)
                # The exact random fixture container, no prune or shared service.
                self.command('docker', 'rm', '-f', name)
