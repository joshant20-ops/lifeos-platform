import copy
import unittest
from governor.storage_boot_acceptance import EXPECTED,validate_fleet
class BootFleetAcceptance(unittest.TestCase):
    def fleet(self):
        data={n:{"id":str(i),"state":"running","health":"healthy","policy":"unless-stopped"} for i,n in enumerate(sorted(EXPECTED))}
        data["legacy"]={"id":"old","state":"exited","health":"none","policy":"unless-stopped"}
        return data
    def test_same_id_healthy_fleet_passes(self):
        rows=self.fleet();validate_fleet(rows,copy.deepcopy(rows))
    def test_recreated_missing_unhealthy_or_resurrected_container_fails(self):
        before=self.fleet()
        for mutation in ["identity","missing","health","legacy"]:
            after=copy.deepcopy(before)
            if mutation=="identity":after["homeassistant"]["id"]="replacement"
            if mutation=="missing":after["homeassistant"]["state"]="exited"
            if mutation=="health":after["homeassistant"]["health"]="unhealthy"
            if mutation=="legacy":after["legacy"]["state"]="running"
            with self.assertRaises(RuntimeError):validate_fleet(before,after)
