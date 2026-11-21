import unittest
from datetime import datetime, timedelta, timezone
from happy_hour import Slot, recommend

class HappyHourTests(unittest.TestCase):
    def test_joint_plan_beats_independent_ranking(self):
        now = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)
        a, b, c = [Slot(now + timedelta(hours=h), now + timedelta(hours=h+1)) for h in (1, 2, 3)]
        costs = {frozenset(): 100, frozenset([a]): 60, frozenset([b]): 70,
                 frozenset([c]): 80, frozenset([a,b]): 55,
                 frozenset([a,c]): 20, frozenset([b,c]): 40}
        self.assertEqual(recommend([a,b,c], 2, now, lambda s: costs[frozenset(s)]), ((a,c),80))
        self.assertEqual(recommend([a,b,c], 0, now, lambda s: costs[frozenset(s)]), ((),0))
        self.assertEqual(recommend([a,b,c], 2, now, lambda s: 100), ((),0))
        self.assertEqual(recommend([a,b,c], 1, now, lambda s: costs[frozenset(s)]), ((a,),40))

    def test_confirmed_and_expired(self):
        now = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)
        a = Slot(now, now + timedelta(hours=1))
        b = Slot(now + timedelta(hours=2), now + timedelta(hours=3))
        self.assertEqual(recommend([a,b,b], 1, now, lambda s: 100-20*len(s), (b,)), ((),0))

if __name__ == "__main__":
    unittest.main()
