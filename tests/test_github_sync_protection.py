import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SYNC = ROOT / "homelab/live/usr/local/sbin/lifeos-github-sync"
POLICY = ROOT / "homelab/.snapshot-protected.txt"


class SnapshotProtectionTests(unittest.TestCase):
    def test_security_critical_control_files_are_protected(self):
        protected = {
            line.strip()
            for line in POLICY.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        required = {
            "usr/local/sbin/lifeos-github-sync",
            "usr/local/sbin/lifeos-job-publisher",
            "usr/local/sbin/lifeos-pi-control-runner",
            "usr/local/sbin/lifeos-root-broker",
            "usr/local/sbin/lifeos-ansible-adopt",
            "usr/local/sbin/lifeos-gitleaks-gate",
        }
        self.assertTrue(required <= protected)

    def test_canonical_copy_is_seeded_before_live_scan(self):
        text = SYNC.read_text()
        seed = text.index("# Seed protected files from the just-pulled canonical repository snapshot.")
        live_scan = text.index('for root in "${ROOTS[@]}"; do', seed)
        self.assertLess(seed, live_scan)
        self.assertIn('src="$LIVE/$rel"', text[seed:live_scan])
        self.assertIn('cp -a "$src" "$dst"', text[seed:live_scan])
        self.assertIn('printf \'%s\\n\' "$rel" >>"$NEW_MANIFEST"', text[seed:live_scan])

    def test_live_runtime_copy_is_skipped_before_general_discovery(self):
        text = SYNC.read_text()
        scan = text.index('for root in "${ROOTS[@]}"; do', text.index("# Seed protected files"))
        protected_check = text.index('if protected_live_file "$f"; then', scan)
        general_filter = text.index('if excluded "$f"; then', protected_check)
        copy_live = text.index('cp -a "$f" "$dst"', general_filter)
        self.assertLess(protected_check, general_filter)
        self.assertLess(general_filter, copy_live)

    def test_missing_protection_policy_fails_closed(self):
        text = SYNC.read_text()
        self.assertIn('[ -f "$PROTECTED_MANIFEST" ] || fail "Snapshot protection policy missing"', text)
        self.assertIn('fail "Protected canonical source missing: homelab/live/$rel"', text)
        self.assertIn('fail "Invalid protected snapshot path: $rel"', text)


if __name__ == "__main__":
    unittest.main()
