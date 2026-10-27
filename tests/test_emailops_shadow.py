"""Contracts for the isolated EmailOps shadow boundary."""
import json
from pathlib import Path
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from governor import emailops_runtime_audit as audit
from governor import emailops_adapter as adapter
from governor import emailops_shadow_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]


class EmailOpsShadowTests(unittest.TestCase):
    def test_shadow_model_is_scoped_and_does_not_change_shared_broker(self):
        original = runtime.ai_broker.OLLAMA_MODEL
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.json"
            with patch.object(runtime, "POLICY", policy):
                policy.write_text(json.dumps({"shadow_model": "qwen2.5-coder:7b-instruct"}))
                self.assertEqual(runtime.shadow_model(), "qwen2.5-coder:7b-instruct")
                self.assertEqual(runtime.ai_broker.OLLAMA_MODEL, original)
                policy.write_text("{}")
                self.assertEqual(runtime.shadow_model(), original)
                for value in ("", " model ", None, 7):
                    policy.write_text(json.dumps({"shadow_model": value}))
                    with self.assertRaisesRegex(adapter.EmailOpsError, "^shadow_model_invalid$"):
                        runtime.shadow_model()

    def test_ai_failure_subtypes_suppress_private_native_messages(self):
        for message, expected in (
            ("AI error: structured completion reached token limit", "cli_ai_token_limit"),
            ("AI error: structured completion answer empty", "cli_ai_empty_answer"),
            ("AI error: Generation timed out PRIVATE_SENTINEL", "cli_ai_timeout"),
            ("AI error: Failed to parse response PRIVATE_SENTINEL", "cli_ai_parse"),
            ("AI error: task extraction reply held no JSON object", "cli_ai_parse"),
            ("AI error: Failed to connect to Ollama PRIVATE_SENTINEL", "cli_ai_connect"),
            ("AI error: Ollama error: PRIVATE_SENTINEL", "cli_ai_provider_response"),
            ("PRIVATE_SENTINEL", "cli_ai"),
        ):
            payload = json.dumps({"ok": False, "error": {"code": "ai", "message": message}})
            with self.assertRaises(adapter.EmailOpsError) as caught:
                adapter.envelope(payload, 6)
            self.assertEqual(str(caught.exception), expected)


    def test_ai_readiness_uses_only_a_bounded_synthetic_gateway_request(self):
        import io
        calls = []
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        def opened(request, **kwargs):
            calls.append((request, kwargs))
            return Response(b'{"done":true,"response":"PRIVATE_SENTINEL"}')
        output = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=opened), redirect_stdout(output):
            runtime.ensure_local_ai_ready("http://127.0.0.1:18114", "qwen2.5-coder:7b-instruct")
        request, options = calls[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18114/api/generate")
        self.assertEqual(options["timeout"], 420)
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "qwen2.5-coder:7b-instruct")
        self.assertEqual(payload["prompt"], "Reply OK.")
        self.assertEqual(payload["options"]["num_predict"], 8)
        self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
        self.assertIn("EMAILOPS_AI_READINESS=PASS", output.getvalue())


    def test_same_pi_ai_gateway_uses_loopback_without_rewriting_other_routes(self):
        with patch.object(runtime.ai_broker, "OLLAMA_URL", "http://ai.lan:18114/api/generate"):
            self.assertEqual(runtime.local_ollama_host(), "http://127.0.0.1:18114")
        with patch.object(runtime.ai_broker, "OLLAMA_URL", "https://other.lan:18114/api/generate"):
            self.assertEqual(runtime.local_ollama_host(), "https://other.lan:18114")


    def test_sync_prefix_is_ignored_but_final_json_and_exit_status_remain_required(self):
        payload = 'PRIVATE_SENTINEL sync diagnostic\n' + json.dumps({"ok": True, "data": {"synced": "a"}, "error": None}, indent=2)
        self.assertEqual(adapter.envelope(payload), {"synced": "a"})
        for malformed in (payload + "\ntrailing diagnostic", 'PRIVATE_SENTINEL {"ok":true}'):
            with self.assertRaisesRegex(adapter.EmailOpsError, "^cli_invalid_json$"):
                adapter.envelope(malformed)
        with self.assertRaises(adapter.EmailOpsError) as caught:
            adapter.envelope(payload, 1)
        self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))


    def test_systemd_password_handoff_is_private_and_removed_on_success_and_failure(self):
        import os
        for fail in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                credential = root / "gmail-imap-password"
                credential.write_bytes(b"PRIVATE_SENTINEL")
                credential.chmod(0o440)
                paths = []
                class Client:
                    def _call(self, *args):
                        path = Path(args[args.index("--password-file") + 1])
                        paths.append(path)
                        assert path.stat().st_mode & 0o777 == 0o600
                        assert path.read_bytes() == b"PRIVATE_SENTINEL"
                        assert "PRIVATE_SENTINEL" not in str(args)
                        if fail:
                            raise adapter.EmailOpsError("cli_auth")
                        return {"id": "synthetic"}
                with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(root)}):
                    if fail:
                        with self.assertRaisesRegex(adapter.EmailOpsError, "^cli_auth$"):
                            runtime.add_imap_account(Client(), "synthetic@example.test", root, "2026-10-01")
                    else:
                        self.assertEqual(runtime.add_imap_account(Client(), "synthetic@example.test", root, "2026-10-01"), {"id": "synthetic"})
                self.assertTrue(paths)
                self.assertFalse(paths[0].exists())
                self.assertEqual(credential.stat().st_mode & 0o777, 0o440)


    def test_fixed_input_reason_uses_native_detail_without_disclosing_values(self):
        payload = json.dumps({"ok": False, "error": {"code": "invalid_input",
            "message": "Invalid input: password file must be private",
            "params": {"detail": "password file must be private"}}})
        with self.assertRaisesRegex(adapter.EmailOpsError, "^cli_password_file_permissions$"):
            adapter.envelope(payload, 2)

    def test_failure_categories_never_include_native_details(self):
        for code, expected in (("keyring", "cli_keyring"), ("auth", "cli_auth"),
                               ("PRIVATE_SENTINEL", "cli_failed")):
            payload = json.dumps({"ok": False, "error": {"code": code,
                "message": "PRIVATE_SENTINEL", "params": {"detail": "PRIVATE_SENTINEL"}}})
            with self.assertRaises(adapter.EmailOpsError) as caught:
                adapter.envelope(payload, 1)
            self.assertEqual(str(caught.exception), expected)

    def test_shadow_policy_refuses_junk_even_with_a_matching_installed_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy, manifest = root / "policy.json", root / "manifest.json"
            policy.write_text(json.dumps({"mode": "shadow", "mailbox_writes": False, "commit": "a", "patch_sha256": "b"}))
            manifest.write_text(json.dumps({"source_commit": "a", "patch_sha256": "b"}))
            with patch.object(adapter, "POLICY", policy), patch.object(adapter, "MANIFEST", manifest):
                with self.assertRaisesRegex(adapter.EmailOpsError, "emailops_acceptance_required"):
                    adapter.require_acceptance()

    def test_all_sources_resolve_before_any_junk_mutation_and_proof_is_required(self):
        import subprocess
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            if "accounts" in argv:
                data = [{"id": "a"}]
            elif "report-junk" in argv:
                data = {"filed": True, "verified": False}
            else:
                data = [{"id": "e", "accountId": "a", "messageId": "<one@example.test>"}]
            return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "data": data, "error": None}), "")

        with patch.object(adapter, "require_acceptance"):
            with self.assertRaisesRegex(adapter.EmailOpsError, "source_lookup_not_unique"):
                adapter.confirm_junk_native(["<one@example.test>", "<missing@example.test>"], runner=runner)
            self.assertFalse(any("report-junk" in call for call in calls))
            with self.assertRaisesRegex(adapter.EmailOpsError, "emailops_junk_unverified"):
                adapter.confirm_junk_native(["<one@example.test>"], runner=runner)

    def test_cloud_ai_route_is_refused(self):
        with patch.object(runtime.ai_broker, "OLLAMA_URL", "https://example.com/api/generate"):
            with self.assertRaisesRegex(adapter.EmailOpsError, "local_ai_route_invalid"):
                runtime.local_ollama_host()

    def test_shadow_orchestration_preserves_tasks_and_keeps_private_output_local(self):
        class Client:
            account = None
            def _call(self, *args, **kwargs):
                return {"synced": "a"} if args[0] == "sync" else {}
            def accounts(self):
                return [{"id": "a", "email": "synthetic@example.test", "provider": "imap"}]
            def doctor(self):
                return {"ok": True, "provider": "ollama"}
            def emails(self, limit):
                return [{"id": "e", "messageId": "<one@example.test>", "mailbox": "inbox"}]
            def analyze(self, email_id):
                return {"source_message_ids": ["<one@example.test>"], "proposals": [{"title": "PRIVATE_SENTINEL"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, user = root / "tasks.json", root / "user.json"
            state.write_text(json.dumps({"tasks": [{"id": "task", "source_message_ids": ["<one@example.test>"]}]}))
            user.write_text('{"comments":["preserve"]}')
            (root / "gmail-imap-user").write_text("synthetic@example.test")
            original = (state.read_bytes(), user.read_bytes())
            output = io.StringIO()
            with patch.object(runtime, "PROFILE", root), patch.object(runtime, "STATE", state), \
                 patch.object(runtime, "USER_STATE", user), patch.object(runtime, "ShadowClient", Client), \
                 patch.object(runtime, "unlock_keyring"), patch.object(runtime, "shadow_model", return_value="qwen2.5-coder:7b-instruct"), patch.object(runtime, "ensure_local_ai_ready"), patch.object(runtime, "local_ollama_host", return_value="http://ai.lan:18114"), \
                 patch.object(runtime.platform, "node", return_value="Docker"), patch.object(runtime.os, "geteuid", return_value=1000), \
                 patch.dict(runtime.os.environ, {"CREDENTIALS_DIRECTORY": str(root)}), \
                 patch.object(runtime.sys, "argv", ["runtime"]), redirect_stdout(output):
                self.assertEqual(runtime.main(), 0)
            self.assertEqual((state.read_bytes(), user.read_bytes()), original)
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
            self.assertIn("EMAILOPS_SHADOW=PASS", output.getvalue())
            self.assertIn("PRIVATE_SENTINEL", (root / "shadow-report.json").read_text())

    def test_native_cli_failure_does_not_leak_private_errors(self):
        with self.assertRaisesRegex(adapter.EmailOpsError, "^cli_failed$"):
            adapter.envelope('{"ok":false,"error":{"message":"PRIVATE_BODY"}}')

    def test_normalization_preserves_exact_source_and_never_invents_completion(self):
        result = adapter.normalize_analysis({
            "schema": "emailops_analysis_v1",
            "source": {"id": "1", "accountId": "a", "threadId": "t", "messageId": "<one@example.test>"},
            "extraction": {"tasks": [{"title": "Review", "due_at_iso": "2026-12-01"}]},
        })
        self.assertEqual(result["source_message_ids"], ["<one@example.test>"])
        self.assertEqual(result["proposals"][0]["due_date"], "2026-12-01")
        self.assertEqual(result["lifecycle"], "UNKNOWN")
        self.assertFalse(result["promotion_ready"])

    def test_missing_source_and_malformed_model_date_are_held(self):
        with self.assertRaises(adapter.EmailOpsError):
            adapter.source_identity({"messageId": "uid:17"})
        with self.assertRaisesRegex(adapter.EmailOpsError, "analysis_due_date_invalid"):
            adapter.normalize_analysis({
                "schema": "emailops_analysis_v1",
                "source": {"id": "1", "accountId": "a", "threadId": "t", "messageId": "<one@example.test>"},
                "extraction": {"tasks": [{"title": "Review", "due_at_iso": "next Tuesday"}]},
            })

    def test_shadow_rejects_mailbox_mutation_before_starting_cli(self):
        from unittest.mock import Mock
        runner = Mock()
        client = adapter.ShadowClient(runner=runner)
        for command in ("report-junk", "compose", "draft", "delete", "snooze"):
            with self.assertRaisesRegex(adapter.EmailOpsError, "shadow_command_blocked"):
                client._call(command, "synthetic")
        runner.assert_not_called()

    def test_pin_is_exact_and_mailbox_writes_are_disabled(self):
        pin = json.loads((ROOT / "config/emailops-upstream.json").read_text())
        self.assertRegex(pin["commit"], r"^[a-f0-9]{40}$")
        self.assertRegex(pin["archive_sha256"], r"^[a-f0-9]{64}$")
        self.assertFalse(pin["mailbox_writes"])
        self.assertEqual(pin["mode"], "shadow")

    def test_audit_does_not_expose_probe_output_or_access_credentials(self):
        import subprocess
        private = "PRIVATE_SENTINEL_DO_NOT_LOG"
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(audit, "PROFILE", Path(directory)), \
             patch.object(audit.shutil, "which", return_value="/usr/bin/busctl"), \
             patch.object(audit, "probe_command", return_value=subprocess.CompletedProcess([], 0, private, private)), \
             patch.object(audit.shutil, "disk_usage", return_value=type("Usage", (), {"free": 1000000})()):
            result = audit.audit()
        self.assertNotIn(private, str(result))
        self.assertEqual(result["EMAILOPS_SECRET_SERVICE"], "NOT_ACTIVE")
        self.assertEqual(result["EMAILOPS_MAILBOX_WRITES"], "DISABLED")

    def test_wrong_runtime_is_blocked_before_probing(self):
        with patch.object(audit.platform, "node", return_value="cloud"), patch.object(audit, "audit") as probe:
            self.assertEqual(audit.main(), 20)
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class BroaderShadowTests(unittest.TestCase):
    def test_balances_known_and_unmatched_without_junk_or_duplicates(self):
        rows = [{"id":str(i),"messageId":"<%s@example.test>"%i,"mailbox":"inbox"} for i in range(20)]
        known = {r["messageId"]:["task"] for r in rows[:12]}
        selected = runtime.select_sample(rows + [rows[0]], known)
        self.assertEqual(len(selected),8)
        self.assertEqual(sum(r["messageId"] in known for r in selected),4)
        self.assertEqual(len({r["messageId"] for r in selected}),8)
        self.assertEqual(runtime.select_sample([{"messageId":"<spam@example.test>","mailbox":"spam"}],{}),[])

    def test_all_message_evidence_survives_one_task_preview(self):
        report = {"generated_at":123,"results":[
            {"matched_task_ids":["task"],"source_message_ids":["<one@example.test>"],
             "summary":"First request","proposals":[{"title":"Reply","due_date":None}]},
            {"matched_task_ids":["task"],"source_message_ids":["<two@example.test>"],
             "summary":"Progress","proposals":[{"title":"Reply","due_date":None}]}
        ]}
        preview = adapter.task_previews(report)["task"]
        self.assertEqual(preview["source_message_ids"],["<one@example.test>","<two@example.test>"])
        self.assertIn("First request",preview["summary"])
        self.assertIn("Progress",preview["summary"])
        self.assertEqual(len(preview["proposals"]),1)
        self.assertEqual(preview["sampled_messages"],2)
        self.assertEqual(preview["lifecycle"],"UNKNOWN")
        self.assertFalse(preview["promotion_ready"])
