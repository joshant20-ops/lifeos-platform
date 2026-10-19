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
            calls = []

            def fake_run(args, timeout=4):
                calls.append((args, timeout))
                if args[0] == "findmnt":
                    return subprocess.CompletedProcess(args, 0, "/mnt/synology\n", "private source path")
                if args[:3] in (["docker", "volume", "inspect"], ["docker", "network", "inspect"]):
                    return subprocess.CompletedProcess(args, 0, args[2] + "\n", "")
                if args[:2] == ["docker", "compose"]:
                    return subprocess.CompletedProcess(args, 0, "", "hidden compose diagnostics")
                if args[:2] == ["docker", "ps"] and "--quiet" in args:
                    return subprocess.CompletedProcess(args, 0, "container-id\n", "")
                if args[:2] == ["docker", "ps"]:
                    return subprocess.CompletedProcess(args, 0, "running|healthy\nexited|\nunknown|custom\n", "container details")
                if args[0] == "curl":
                    return subprocess.CompletedProcess(args, 0, "200", "sensitive response body")
                raise AssertionError(args)

            with patch.object(audit, "PROJECT", root), patch.object(audit, "COMPOSE", root / "docker-compose.yml"), patch.object(audit, "DB_VERSION", root / "data/db/PG_VERSION"), patch.object(audit, "APP_DATA", root / "data/data"), patch.object(audit, "run", side_effect=fake_run):
                with patch("sys.stdout") as stdout:
                    audit.main()
                    output = "".join(call.args[0] for call in stdout.write.call_args_list)

        self.assertIn("PAPERLESS_AUDIT_MUTATIONS=NONE", output)
        self.assertIn("PAPERLESS_SECRET_KEY_PRESENT=YES", output)
        self.assertIn("PAPERLESS_DB_PG_VERSION=YES", output)
        self.assertIn("PAPERLESS_CONTAINER_COUNT=3", output)
        self.assertIn("PAPERLESS_API_HTTP_STATUS=200", output)
        self.assertIn("PAPERLESS_8010_PUBLISHED=YES", output)
        self.assertIn("PAPERLESS_CONTAINER_STATE_UNKNOWN=1", output)
        self.assertIn("PAPERLESS_CONTAINER_HEALTH_UNKNOWN=1", output)
        for private in ("do-not-print-this-secret", "16-secret-value", "private source path", "hidden compose diagnostics", "container details", "container-id", "sensitive response body"):
            self.assertNotIn(private, output)
        self.assertTrue(all(timeout <= 8 for _, timeout in calls))
        self.assertFalse(any(args[1] in {"up", "down", "start", "stop", "restart", "rm", "pull"} for args, _ in calls if args[0] == "docker"))

    def test_mount_check_accepts_synology_parent_mount_only(self):
        result = subprocess.CompletedProcess([], 0, "/mnt/synology\n", "")
        with patch.object(audit, "run", return_value=result):
            self.assertEqual(audit.mount_state("/mnt/synology/Joshan/paperless_media"), "MOUNTED")
        root_mount = subprocess.CompletedProcess([], 0, "/\n", "")
        with patch.object(audit, "run", return_value=root_mount):
            self.assertEqual(audit.mount_state("/mnt/synology/Intake"), "UNMOUNTED")

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
