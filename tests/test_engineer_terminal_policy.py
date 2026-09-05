import importlib.util
import pathlib
import unittest


SOURCE = pathlib.Path("governor/job_records.py")
SPEC = importlib.util.spec_from_file_location("lifeos_job_records_terminal_test", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EngineerTerminalPolicyTests(unittest.TestCase):
    def record(self, status, stage, reason="", iterations=None):
        job = {
            "id": "terminal-test",
            "request": "test autonomous repair terminal policy",
            "privacy": "normal",
            "status": status,
            "stage": stage,
            "iterations": iterations or [],
        }
        if reason:
            job["blocked_reason"] = reason
        return MODULE.make_record(job, "PUBLISHED")

    def test_pass_is_terminal_and_not_retryable(self):
        outcome = self.record("PASS", "complete")["terminal_outcome"]
        self.assertEqual(outcome["kind"], "PASS")
        self.assertTrue(outcome["terminal"])
        self.assertFalse(outcome["retry_allowed"])

    def test_external_block_is_terminal_and_not_retryable(self):
        outcome = self.record(
            "BLOCKED", "blocked", "required hardware is unavailable"
        )["terminal_outcome"]
        self.assertEqual(outcome["kind"], "BLOCKED")
        self.assertTrue(outcome["terminal"])
        self.assertFalse(outcome["retry_allowed"])

    def test_repeated_failure_is_distinct_terminal_reason(self):
        iterations = [{"failure_signature": "abc123"}] * 3
        outcome = self.record(
            "BLOCKED",
            "blocked_repeated_failure",
            "repeated deterministic failure detected (3 occurrences); stopped before exhausting the full iteration budget",
            iterations,
        )["terminal_outcome"]
        self.assertEqual(outcome["kind"], "REPEATED_FAILURE")
        self.assertEqual(outcome["iteration_count"], 3)
        self.assertEqual(outcome["last_failure_signature"], "abc123")
        self.assertFalse(outcome["retry_allowed"])

    def test_iteration_ceiling_is_distinct_terminal_reason(self):
        outcome = self.record(
            "BLOCKED", "blocked", "maximum iterations reached", [{}] * 8
        )["terminal_outcome"]
        self.assertEqual(outcome["kind"], "ITERATION_LIMIT")
        self.assertEqual(outcome["iteration_count"], 8)
        self.assertTrue(outcome["terminal"])
        self.assertFalse(outcome["retry_allowed"])

    def test_running_state_is_the_only_retryable_record(self):
        outcome = self.record("RUNNING", "verifier")["terminal_outcome"]
        self.assertEqual(outcome["kind"], "NON_TERMINAL")
        self.assertFalse(outcome["terminal"])
        self.assertTrue(outcome["retry_allowed"])

    def test_agent_terminal_paths_all_publish_through_finish_job(self):
        text = pathlib.Path("governor/autonomous_agent.py").read_text()
        self.assertIn("return finish_job(job, \"complete\"", text)
        self.assertIn("return finish_job(job, \"blocked\"", text)
        self.assertIn("return finish_job(job, \"blocked_repeated_failure\"", text)
        self.assertIn('job["blocked_reason"] = "maximum iterations reached"', text)
        self.assertIn("job[\"record_publication\"] = publish_record", text)

    def test_continuation_requires_pass_so_terminal_blocks_cannot_spawn_children(self):
        text = pathlib.Path("governor/autonomous_agent.py").read_text()
        self.assertIn('if str(job.get("status") or "").upper() != "PASS":', text)
        self.assertIn("# BLOCKED and repeated deterministic failure stop before this point.", text)


if __name__ == "__main__":
    unittest.main()
