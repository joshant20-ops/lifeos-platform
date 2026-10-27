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

    def test_native_owned_canvas_recreation_does_not_require_old_id(self):
        before=self.fleet();after=copy.deepcopy(before)
        after["lifeos-agent-canvas"]["id"]="native_recreated"
        validate_fleet(before,after)

    def test_canvas_image_network_and_persistent_mounts_must_match(self):
        from governor.storage_boot_acceptance import validate_canvas_row
        row={"Config":{"Image":"nginx:1.29-alpine"},"HostConfig":{"NetworkMode":"host"},"Mounts":[{"Type":"bind","Source":"/home/joshan/lifeos-canvas-tls","Destination":"/tls","RW":False}]}
        validate_canvas_row("lifeos-agent-canvas-tls",row)
        for mutation in ["image","network","source","writable"]:
            changed=copy.deepcopy(row)
            if mutation=="image":changed["Config"]["Image"]="different"
            if mutation=="network":changed["HostConfig"]["NetworkMode"]="bridge"
            if mutation=="source":changed["Mounts"][0]["Source"]="/different"
            if mutation=="writable":changed["Mounts"][0]["RW"]=True
            with self.assertRaises(RuntimeError):validate_canvas_row("lifeos-agent-canvas-tls",changed)
