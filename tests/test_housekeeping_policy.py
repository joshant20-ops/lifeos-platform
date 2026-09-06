import pathlib
import unittest

WORKFLOW = pathlib.Path('.github/workflows/lifeos-housekeeping.yml')
TEXT = WORKFLOW.read_text()


def executable_lines():
    """Return shell-like lines while ignoring comments and human-readable echo text."""
    lines = []
    for raw in TEXT.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith(('echo ', "echo '", 'echo "')):
            continue
        lines.append(line)
    return lines


class HousekeepingPolicyTests(unittest.TestCase):
    def test_uses_existing_ots_git_maintenance(self):
        self.assertIn('git -C "$repo" worktree prune --expire now --verbose', TEXT)
        self.assertIn('git -C "$repo" gc --auto', TEXT)
        self.assertIn('runs-on: [self-hosted, linux, ARM64, lifeos-pi5]', TEXT)
        self.assertIn('ssh -o BatchMode=yes -o ConnectTimeout=8 Engineer', TEXT)

    def test_forbids_broad_or_destructive_repository_cleanup(self):
        commands = '\n'.join(executable_lines())
        forbidden = (
            'git clean',
            'reset --hard',
            'rm -rf "$repo"',
            'find /tmp ',
            'sudo ',
        )
        for token in forbidden:
            self.assertNotIn(token, commands)

    def test_only_exact_known_pi_temp_files_are_targets(self):
        expected = (
            '/tmp/lifeos-ai-tags.json',
            '/tmp/lifeos-ai-model',
            '/tmp/lifeos-ai-request.json',
            '/tmp/lifeos-ai-response.json',
            '/tmp/lifeos-ai-ps.json',
        )
        for path in expected:
            self.assertIn(path, TEXT)
        self.assertNotIn('/tmp/lifeos-*', TEXT)

    def test_engineer_cleanup_is_bounded_to_known_smoke_residue(self):
        self.assertIn('$HOME/.local/share/lifeos-agent/smoke', TEXT)
        self.assertIn('$HOME/.local/share/lifeos-agent/codex-smoke.out', TEXT)
        self.assertIn('ACTIVE_WORKTREE_PRESERVED', TEXT)
        self.assertIn('UNSAFE_SYMLINK_PRESERVED', TEXT)
        self.assertIn('OTHER_OWNER_PRESERVED', TEXT)

    def test_unknown_repository_dirt_fails_closed(self):
        self.assertIn('PI_REPOSITORY_CLEAN=FAIL', TEXT)
        self.assertIn('ENGINEER_REPOSITORY_CLEAN=FAIL', TEXT)
        self.assertIn('status --porcelain --untracked-files=all', TEXT)

    def test_daily_and_weekly_native_schedules_exist(self):
        self.assertIn("cron: '17 3 * * *'", TEXT)
        self.assertIn("cron: '47 3 * * 0'", TEXT)
        self.assertIn('HOUSEKEEPING_DEPTH', TEXT)

    def test_no_new_monitor_or_private_address_is_embedded(self):
        for token in ('192.168.', '10.0.', '172.16.', 'docker run', 'pip install', 'apt-get install'):
            self.assertNotIn(token, TEXT)


if __name__ == '__main__':
    unittest.main()
