import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('projector', ROOT / 'scripts/project-energy-opportunities-to-ha.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class EnergyAttentionProjectionTests(unittest.TestCase):
    def test_clear_projection_is_stable(self):
        a = M.build_projection([])
        b = M.build_projection([])
        self.assertEqual(a, b)
        self.assertEqual(a['state'], 'clear')
        self.assertEqual(a['count'], 0)

    def test_stable_opportunity_id_is_preserved(self):
        rows = [{
            'opportunity_id': 'negative-import-abc123',
            'severity': 'opportunity',
            'start': '2026-09-06T00:00:00+01:00',
            'end': '2026-09-06T00:30:00+01:00',
            'minimum_price_p_per_kwh': -2.5,
            'source': 'home_assistant_octopus_rate_events',
        }]
        p = M.build_projection(rows)
        self.assertEqual(p['attention_id'], 'negative-import-abc123')
        self.assertEqual(p['opportunity_ids'], ['negative-import-abc123'])
        self.assertEqual(p['state'], 'attention')

    def test_replay_is_byte_identical(self):
        rows = [{
            'opportunity_id': 'negative-import-replay',
            'severity': 'opportunity',
            'start': '2026-09-06T01:00:00+01:00',
            'end': '2026-09-06T02:00:00+01:00',
            'minimum_price_p_per_kwh': -1.0,
            'source': 'test',
        }]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'attention.json'
            M.atomic_write(out, M.build_projection(rows))
            first = out.read_bytes()
            M.atomic_write(out, M.build_projection(rows))
            second = out.read_bytes()
            self.assertEqual(first, second)

    def test_duplicate_ids_collapse_in_identity_list(self):
        row = {
            'opportunity_id': 'negative-import-same',
            'severity': 'opportunity',
            'start': '2026-09-06T01:00:00+01:00',
            'end': '2026-09-06T01:30:00+01:00',
            'minimum_price_p_per_kwh': -3,
            'source': 'test',
        }
        p = M.build_projection([row, dict(row)])
        self.assertEqual(p['opportunity_ids'], ['negative-import-same'])
        self.assertEqual(p['attention_id'], 'negative-import-same')


if __name__ == '__main__':
    unittest.main()
