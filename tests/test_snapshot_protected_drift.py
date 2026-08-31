import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE = ROOT / "homelab" / "live"
POLICY = ROOT / "homelab" / ".snapshot-protected.txt"


class SnapshotProtectedDriftTests(unittest.TestCase):
    def test_protected_files_match_known_desired_state_markers(self):
        """Fail CI if a Pi snapshot re-imports stale protected control binaries."""
        protected = {
            line.strip()
            for line in POLICY.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        required = {
            "usr/local/sbin/lifeos-job-publisher": (
                "def sync_repo():",
                "script.relative_to(allowed_root)",
                "Strict FIFO: only the oldest staged manifest is considered per run.",
            ),
            "usr/local/sbin/lifeos-github-sync": (
                'PROTECTED_MANIFEST="$REPO/homelab/.snapshot-protected.txt"',
                '[ -f "$PROTECTED_MANIFEST" ] || fail "Snapshot protection policy missing"',
                "# Seed protected files from the just-pulled canonical repository snapshot.",
                'if protected_live_file "$f"; then',
            ),
        }

        for rel, markers in required.items():
            self.assertIn(rel, protected, f"security-critical file missing from protection policy: {rel}")
            path = LIVE / rel
            self.assertTrue(path.is_file(), f"protected desired-state file missing: {rel}")
            text = path.read_text()
            for marker in markers:
                self.assertIn(marker, text, f"protected desired-state drift detected in {rel}: missing {marker!r}")


if __name__ == "__main__":
    unittest.main()
