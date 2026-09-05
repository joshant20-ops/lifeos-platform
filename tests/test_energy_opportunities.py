import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

P=Path(__file__).resolve().parents[1]/'energy/app/opportunities.py'
spec=importlib.util.spec_from_file_location('energy_opportunities',P)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class EnergyOpportunityTests(unittest.TestCase):
    def test_groups_consecutive_negative_slots_only(self):
        t=datetime(2026,9,6,0,0,tzinfo=timezone.utc)
        slots=[
            m.RateSlot(t,t+timedelta(minutes=30),2.0),
            m.RateSlot(t+timedelta(minutes=30),t+timedelta(minutes=60),-1.2),
            m.RateSlot(t+timedelta(minutes=60),t+timedelta(minutes=90),-4.5),
            m.RateSlot(t+timedelta(minutes=90),t+timedelta(minutes=120),1.0),
            m.RateSlot(t+timedelta(minutes=120),t+timedelta(minutes=150),-0.1),
        ]
        out=m.group_negative_import_slots(slots,detected_at=t,source='home_assistant_octopus')
        self.assertEqual(len(out),2)
        self.assertEqual(out[0].duration_minutes,60)
        self.assertEqual(out[0].minimum_price_p_per_kwh,-4.5)
        self.assertEqual(len(out[0].slots),2)
        self.assertEqual(out[1].duration_minutes,30)

    def test_id_is_stable_across_detection_times(self):
        t=datetime(2026,9,6,0,0,tzinfo=timezone.utc)
        s=[m.RateSlot(t,t+timedelta(minutes=30),-1.0)]
        a=m.group_negative_import_slots(s,detected_at=t,source='ha')[0]
        b=m.group_negative_import_slots(s,detected_at=t+timedelta(hours=1),source='ha')[0]
        self.assertEqual(a.opportunity_id,b.opportunity_id)

    def test_ledger_persists_dedup(self):
        t=datetime(2026,9,6,0,0,tzinfo=timezone.utc)
        o=m.group_negative_import_slots([m.RateSlot(t,t+timedelta(minutes=30),-1)],detected_at=t,source='ha')[0]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json'
            a=m.OpportunityLedger(p); self.assertEqual(a.unseen([o]),[o])
            a.mark_notified(o,['alexa','whatsapp'])
            b=m.OpportunityLedger(p); self.assertEqual(b.unseen([o]),[])

    def test_zero_and_cheap_positive_are_not_enabled(self):
        t=datetime(2026,9,6,0,0,tzinfo=timezone.utc)
        slots=[m.RateSlot(t,t+timedelta(minutes=30),0),m.RateSlot(t+timedelta(minutes=30),t+timedelta(minutes=60),4.9)]
        self.assertEqual(m.group_negative_import_slots(slots,detected_at=t,source='ha'),[])

if __name__=='__main__': unittest.main()
