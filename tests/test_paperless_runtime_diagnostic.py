import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = pathlib.Path(__file__).resolve().parents[1] / "governor" / "paperless_runtime_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("paperless_runtime_diagnostic", MODULE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PaperlessRuntimeDiagnosticTests(unittest.TestCase):
    def test_fixed_fields_redact_values_and_command_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / "docker-compose.yml").write_text("services: {}\n")
            (root / ".env").write_text("PAPERLESS_SECRET_KEY=do-not-print-this-secret\n")
            (root / "data/db").mkdir(parents=True)
            (root / "data/db/PG_VERSION").write_text("16-secret-value\n")
            (root / "data/data").mkdir()
            fstab = root / "fstab"
            fstab.write_text(
                "/dev/disk/by-id/private /mnt/synology nfs credentials=/private/secret 0 0\n"
                "/dev/disk/by-id/private-nested /mnt/synology/Joshan/Intake nfs credentials=/private/secret 0 0\n"
            )
            (root / "mountinfo").write_text(
                "36 25 0:32 / /mnt/synology rw,relatime - nfs server:/private rw\\n"
            )
            calls = []

            def fake_run(args, timeout=4):
                calls.append((args, timeout))
                if args[0] == "findmnt":
                    return subprocess.CompletedProcess(args, 0, "/mnt/synology\n", "private source path")
                if args[0] == "systemd-escape":
                    return subprocess.CompletedProcess(args, 0, "mnt-synology.mount\n", "")
                if args[:2] == ["systemctl", "is-enabled"]:
                    return subprocess.CompletedProcess(args, 0, "generated\n", "")
                if args[:2] == ["systemctl", "show"]:
                    value = "mounted\n" if "--property=SubState" in args else "success\n"
                    return subprocess.CompletedProcess(args, 0, value, "")
                if args[:2] == ["systemctl", "is-active"]:
                    return subprocess.CompletedProcess(args, 0, "active\n", "")
                if args[:3] in (["docker", "volume", "inspect"], ["docker", "network", "inspect"]):
                    return subprocess.CompletedProcess(args, 0, args[3] + "\n", "")
                if args[:2] == ["docker", "compose"]:
                    return subprocess.CompletedProcess(args, 0, "", "hidden compose diagnostics")
                if args[:2] == ["docker", "ps"] and "--quiet" in args:
                    return subprocess.CompletedProcess(args, 0, "container-id\n", "")
                if args[:2] == ["docker", "ps"]:
                    return subprocess.CompletedProcess(args, 0, "running|Up 4 minutes (healthy)\nexited|Exited (1) 2 minutes ago\nunknown|Created\n", "container details")
                if args[0] == "curl":
                    return subprocess.CompletedProcess(args, 0, "200", "sensitive response body")
                raise AssertionError(args)

            with patch.object(audit, "PROJECT", root), patch.object(audit, "COMPOSE", root / "docker-compose.yml"), patch.object(audit, "DB_VERSION", root / "data/db/PG_VERSION"), patch.object(audit, "APP_DATA", root / "data/data"), patch.object(audit, "FSTAB", fstab), patch.object(audit, "MOUNTINFO", root / "mountinfo"), patch.object(audit, "run", side_effect=fake_run):
                with patch("sys.stdout") as stdout:
                    audit.main()
                    output = "".join(call.args[0] for call in stdout.write.call_args_list)

        self.assertIn("PAPERLESS_AUDIT_MUTATIONS=NONE", output)
        self.assertIn("PAPERLESS_SECRET_KEY_PRESENT=YES", output)
        self.assertIn("PAPERLESS_DB_PG_VERSION=YES", output)
        self.assertIn("PAPERLESS_REDIS_VOLUME=PRESENT", output)
        self.assertIn("PAPERLESS_REVERSE_PROXY_NETWORK=PRESENT", output)
        self.assertIn("PAPERLESS_FSTAB_SYNOLOGY=YES", output)
        self.assertIn("PAPERLESS_SYNOLOGY_MOUNT=MOUNTED", output)
        self.assertIn("PAPERLESS_SYNOLOGY_FINDMNT_RELATION=EXACT", output)
        self.assertIn("PAPERLESS_MEDIA_FINDMNT_RELATION=ANCESTOR", output)
        self.assertIn("PAPERLESS_SYNOLOGY_PROC_MOUNTINFO=MOUNTED", output)
        self.assertIn("PAPERLESS_SYNOLOGY_KERNEL_MOUNT_CONSISTENCY=CONSISTENT", output)
        self.assertIn("PAPERLESS_SYNOLOGY_UNIT_SUBSTATE=MOUNTED", output)
        self.assertIn("PAPERLESS_SYNOLOGY_UNIT_RESULT=SUCCESS", output)
        self.assertIn("PAPERLESS_SYNOLOGY_MOUNT_CONSISTENCY=CONSISTENT", output)
        self.assertIn("PAPERLESS_DOCKER_SERVICE_ACTIVE=YES", output)
        self.assertIn("PAPERLESS_CONTAINERD_SERVICE_ACTIVE=YES", output)
        self.assertIn("PAPERLESS_RECONCILER_SERVICE_ACTIVE=YES", output)
        self.assertIn("PAPERLESS_ASSISTANT_SERVICE_ACTIVE=YES", output)
        self.assertIn("PAPERLESS_FSTAB_MEDIA=NO", output)
        self.assertIn("PAPERLESS_FSTAB_INTAKE=YES", output)
        self.assertIn("PAPERLESS_MOUNT_UNIT_SYNOLOGY_ENABLED=YES", output)
        self.assertIn("PAPERLESS_MOUNT_UNIT_SYNOLOGY_ACTIVE=YES", output)
        self.assertIn("PAPERLESS_CONTAINER_COUNT=3", output)
        self.assertIn("PAPERLESS_API_HTTP_STATUS=200", output)
        self.assertIn("PAPERLESS_8010_PUBLISHED=YES", output)
        self.assertIn("PAPERLESS_CONTAINER_STATE_UNKNOWN=1", output)
        self.assertIn("PAPERLESS_CONTAINER_HEALTH_NONE=2", output)
        self.assertIn("PAPERLESS_CONTAINER_HEALTH_UNKNOWN=0", output)
        for private in ("do-not-print-this-secret", "16-secret-value", "private source path", "hidden compose diagnostics", "container details", "container-id", "sensitive response body", "/dev/disk/by-id", "credentials=/private/secret"):
            self.assertNotIn(private, output)
        self.assertTrue(all(timeout <= 8 for _, timeout in calls))
        self.assertFalse(any(args[1] in {"up", "down", "start", "stop", "restart", "rm", "pull"} for args, _ in calls if args[0] == "docker"))

    def test_mount_consistency_detects_unit_mount_table_mismatch(self):
        self.assertEqual(audit.mount_consistency("UNMOUNTED", "MOUNTED"), "INCONSISTENT")
        self.assertEqual(audit.mount_consistency("MOUNTED", "UNMOUNTED"), "INCONSISTENT")
        self.assertEqual(audit.mount_consistency("MOUNTED", "MOUNTED"), "CONSISTENT")
        self.assertEqual(audit.mount_consistency("UNMOUNTED", "UNMOUNTED"), "CONSISTENT")
        self.assertEqual(audit.mount_consistency("UNMOUNTED", "FAILED"), "CONSISTENT")
        self.assertEqual(audit.mount_consistency("UNKNOWN", "UNKNOWN"), "UNKNOWN")

    def test_mountinfo_state_uses_exact_canonical_targets_and_redacts_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            mountinfo = pathlib.Path(temp) / "mountinfo"
            mountinfo.write_text("36 25 0:32 / /mnt/synology rw - nfs server:/private rw\\n")
            self.assertEqual(audit.mountinfo_state("/mnt/synology", mountinfo), "MOUNTED")
            self.assertEqual(audit.mountinfo_state("/mnt/synology/Joshan/Intake", mountinfo), "UNMOUNTED")
            self.assertEqual(audit.mountinfo_state("/etc", mountinfo), "UNKNOWN")
            mountinfo.write_text("invalid\\n")
            self.assertEqual(audit.mountinfo_state("/mnt/synology", mountinfo), "UNKNOWN")

    def test_mount_check_accepts_synology_parent_mount_only(self):
        result = subprocess.CompletedProcess([], 0, "/mnt/synology\n", "")
        with patch.object(audit, "run", return_value=result):
            self.assertEqual(audit.mount_state("/mnt/synology/Joshan/paperless_media"), "MOUNTED")
        root_mount = subprocess.CompletedProcess([], 0, "/\n", "")
        with patch.object(audit, "run", return_value=root_mount):
            self.assertEqual(audit.mount_state("/mnt/synology/Joshan/Intake"), "UNMOUNTED")

    def test_compose_consume_mount_uses_exact_canonical_intake_path(self):
        self.assertEqual(audit.NAS_PATHS["PAPERLESS_INTAKE_MOUNT"], "/mnt/synology/Joshan/Intake")
        with patch.object(audit, "run", return_value=subprocess.CompletedProcess([], 0, "/mnt/synology\n", "")) as mocked:
            self.assertEqual(audit.mount_state(audit.NAS_PATHS["PAPERLESS_INTAKE_MOUNT"]), "MOUNTED")
        self.assertEqual(mocked.call_args.args[0][4], "/mnt/synology/Joshan/Intake")

    def test_fstab_parser_returns_only_canonical_target_presence(self):
        with tempfile.TemporaryDirectory() as temp:
            fstab = pathlib.Path(temp) / "fstab"
            fstab.write_text("server:/private /mnt/synology nfs secrets=hidden 0 0\n")
            self.assertEqual(audit.fstab_targets(fstab), {"/mnt/synology"})
            self.assertIsNone(audit.fstab_targets(pathlib.Path(temp) / "missing"))

    def test_mount_unit_state_normalizes_only_fixed_values(self):
        expected_units = {
            "/mnt/synology": "mnt-synology.mount",
            "/mnt/synology/Joshan/paperless_media": "mnt-synology-Joshan-paperless_media.mount",
            "/mnt/synology/Joshan/paperless_export": "mnt-synology-Joshan-paperless_export.mount",
            "/mnt/synology/Joshan/Intake": "mnt-synology-Joshan-Intake.mount",
        }
        calls = []

        def fake_run(args, timeout=4):
            if args[0] == "systemd-escape":
                return subprocess.CompletedProcess(args, 0, expected_units[args[-1]] + "\n", "")
            calls.append(args)
            if args[1] == "is-enabled":
                return subprocess.CompletedProcess(args, 0, "generated\n", "private unit details")
            return subprocess.CompletedProcess(args, 0, "active\n", "private runtime details")

        with patch.object(audit, "run", side_effect=fake_run):
            for target in expected_units:
                with self.subTest(target=target):
                    self.assertEqual(audit.mount_unit_states(target), ("YES", "YES"))
        self.assertEqual([call[2] for call in calls if call[1] == "is-enabled"], list(expected_units.values()))
        self.assertEqual([call[2] for call in calls if call[1] == "is-active"], list(expected_units.values()))

    def test_mount_unit_rejects_unexpected_escaped_unit_before_systemctl(self):
        calls = []

        def fake_run(args, timeout=4):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "private/path.mount\n", "")

        with patch.object(audit, "run", side_effect=fake_run):
            self.assertEqual(audit.mount_unit_states("/mnt/synology"), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual(len(calls), 1)

    def test_command_errors_are_sanitized(self):
        with patch.object(audit.subprocess, "run", side_effect=FileNotFoundError("sensitive command path")):
            self.assertIsNone(audit.run(["docker", "ps"]))

    def test_env_is_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            env = pathlib.Path(temp) / ".env"
            env.write_text("PAPERLESS_SECRET_KEY=secret\n")
            with patch.object(audit, "MAX_ENV_BYTES", 4):
                self.assertEqual(audit.secret_present(env), "UNKNOWN")

    def test_nas_path_presence_is_separate_from_mount_state(self):
        with tempfile.TemporaryDirectory() as temp:
            present = pathlib.Path(temp) / "present"
            present.mkdir()
            missing = pathlib.Path(temp) / "missing"
            self.assertEqual(audit.path_presence(str(present)), "YES")
            self.assertEqual(audit.path_presence(str(missing)), "NO")
        with patch.object(audit.subprocess, "run", side_effect=subprocess.TimeoutExpired("docker", 5, output="sensitive output")):
            self.assertIsNone(audit.run(["docker", "ps"]))


if __name__ == "__main__":
    unittest.main()


def test_mount_check_does_not_treat_nested_mount_as_parent_mount():
    result = subprocess.CompletedProcess(
        [], 0, "/mnt/synology/Joshan/paperless_media\\n", ""
    )
    with patch.object(audit, "run", return_value=result):
        assert audit.mount_state("/mnt/synology") == "UNMOUNTED"


def test_mount_check_treats_findmnt_command_failure_as_unknown():
    result = subprocess.CompletedProcess([], 1, "", "private diagnostic")
    with patch.object(audit, "run", return_value=result):
        assert audit.mount_state("/mnt/synology") == "UNKNOWN"


def test_mount_check_treats_empty_success_output_as_unknown():
    result = subprocess.CompletedProcess([], 0, "", "")
    with patch.object(audit, "run", return_value=result):
        assert audit.mount_state("/mnt/synology") == "UNKNOWN"


def test_findmnt_relation_uses_fixed_categories_without_returning_paths():
    cases = [
        ("/mnt/synology", 0, "/mnt/synology\\n", ("MOUNTED", "EXACT")),
        ("/mnt/synology/child", 0, "/mnt/synology\\n", ("MOUNTED", "ANCESTOR")),
        ("/mnt/synology", 0, "/mnt/synology/child\\n", ("UNMOUNTED", "DESCENDANT")),
        ("/mnt/synology", 0, "/\\n", ("UNMOUNTED", "HOST_ROOT")),
        ("/mnt/synology", 1, "", ("UNKNOWN", "COMMAND_FAILED")),
        ("/mnt/synology", 0, "", ("UNKNOWN", "EMPTY_OUTPUT")),
    ]
    for path, code, stdout, expected in cases:
        result = subprocess.CompletedProcess([], code, stdout, "private details")
        with patch.object(audit, "run", return_value=result):
            assert audit.mount_state_diagnostic(path) == expected