import importlib.util
import pathlib
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "governor" / "tower_metrics.py"
spec = importlib.util.spec_from_file_location("tower_metrics", MODULE_PATH)
tower_metrics = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tower_metrics)


class TowerMetricsTests(unittest.TestCase):
    def test_safe_id_is_stable_for_linux_block_devices(self):
        self.assertEqual(tower_metrics.safe_id("sda"), "sda")
        self.assertEqual(tower_metrics.safe_id("nvme0n1"), "nvme0n1")

    def test_cpu_percent_uses_delta_not_lifetime_average(self):
        # 100 total ticks elapsed, 75 idle => 25% busy.
        self.assertAlmostEqual(tower_metrics.cpu_percent((100, 200), (175, 300)), 25.0)

    def test_disk_counters_exposes_whole_physical_disks_only(self):
        sample = "\n".join([
            "8 0 sda 1 0 10 0 2 0 20 0 0 0 0 0 0 0 0",
            "8 1 sda1 1 0 10 0 2 0 20 0 0 0 0 0 0 0 0",
            "259 0 nvme0n1 1 0 30 0 2 0 40 0 0 0 0 0 0 0 0",
            "259 1 nvme0n1p1 1 0 30 0 2 0 40 0 0 0 0 0 0 0 0",
            "7 0 loop0 1 0 50 0 2 0 60 0 0 0 0 0 0 0 0",
        ])
        real_read_text = pathlib.Path.read_text

        def fake_read_text(path, *args, **kwargs):
            if str(path) == "/proc/diskstats":
                return sample
            return real_read_text(path, *args, **kwargs)

        with mock.patch.object(pathlib.Path, "read_text", fake_read_text):
            disks = tower_metrics.disk_counters()
        self.assertEqual(disks, {"sda": (10, 20), "nvme0n1": (30, 40)})

    def test_idle_threshold_defaults_require_sustained_low_activity(self):
        self.assertGreaterEqual(tower_metrics.IDLE_SECONDS, 60)
        self.assertLessEqual(tower_metrics.CPU_IDLE_MAX, 10)
        self.assertLessEqual(tower_metrics.GPU_IDLE_MAX, 10)


if __name__ == "__main__":
    unittest.main()
