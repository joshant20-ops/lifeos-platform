import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


governor = load("governor", HERE / "governor.py")
intake = load("github_issue_intake", HERE / "github_issue_intake.py")
worker = load("queue_worker", HERE / "queue_worker.py")


class GithubIntakeTests(unittest.TestCase):
    def issue(self, number=5, body="<!-- lifeos-engineer:ready -->", login="joshant20-ops", labels=None):
        return {
            "number": number,
            "title": "Safe updater",
            "body": body,
            "html_url": f"https://github.com/joshant20-ops/lifeos-platform/issues/{number}",
            "updated_at": "2026-08-30T12:00:00Z",
            "user": {"login": login},
            "labels": labels or [],
        }

    def test_requires_ready_signal_and_trusted_author(self):
        allowed = {"joshant20-ops"}
        self.assertTrue(intake.eligible(self.issue(), "lifeos-engineer-ready", intake.DEFAULT_READY_MARKER, allowed))
        self.assertFalse(intake.eligible(self.issue(body="ordinary issue"), "lifeos-engineer-ready", intake.DEFAULT_READY_MARKER, allowed))
        self.assertFalse(intake.eligible(self.issue(login="outsider"), "lifeos-engineer-ready", intake.DEFAULT_READY_MARKER, allowed))

    def test_pull_requests_never_enter_queue(self):
        item = self.issue(); item["pull_request"] = {"url": "example"}
        self.assertFalse(intake.eligible(item, "lifeos-engineer-ready", intake.DEFAULT_READY_MARKER, {"joshant20-ops"}))

    def test_risk_and_context_metadata(self):
        body = "<!-- lifeos-engineer:ready -->\n<!-- lifeos-risk:HIGH_RISK -->\n<!-- lifeos-context:engineer/ai-governor -->"
        job = intake.build_job(self.issue(body=body), "joshant20-ops/lifeos-platform", "main", "a" * 40)
        self.assertEqual(job["risk"], "HIGH_RISK")
        self.assertEqual(job["context_paths"], ["engineer/ai-governor"])
        self.assertEqual(job["id"], "github-joshant20-ops-lifeos-platform-issue-5")

    def test_offline_fallback_requires_explicit_marker_or_label(self):
        normal = intake.build_job(self.issue(), "joshant20-ops/lifeos-platform", "main", "a" * 40)
        marked = intake.build_job(
            self.issue(body="<!-- lifeos-engineer:ready -->\n<!-- lifeos-offline-fallback:true -->"),
            "joshant20-ops/lifeos-platform",
            "main",
            "a" * 40,
        )
        labelled = intake.build_job(
            self.issue(labels=[{"name": "lifeos-engineer-ready"}, {"name": "provider:offline-fallback"}]),
            "joshant20-ops/lifeos-platform",
            "main",
            "a" * 40,
        )
        self.assertFalse(normal["allow_offline_fallback"])
        self.assertTrue(marked["allow_offline_fallback"])
        self.assertTrue(labelled["allow_offline_fallback"])

    def test_ingest_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(intake, "list_open_issues", return_value=[self.issue()]), \
                 mock.patch.object(intake, "base_commit", return_value="b" * 40):
                first = intake.ingest("joshant20-ops/lifeos-platform", "main", Path(td),
                                      "lifeos-engineer-ready", intake.DEFAULT_READY_MARKER,
                                      {"joshant20-ops"})
                second = intake.ingest("joshant20-ops/lifeos-platform", "main", Path(td),
                                       "lifeos-engineer-ready", intake.DEFAULT_READY_MARKER,
                                       {"joshant20-ops"})
            self.assertEqual(len(first["queued"]), 1)
            self.assertEqual(len(second["duplicates"]), 1)
            files = list((Path(td) / "queue" / "pending").glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)


class QueueWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gov = governor.Governor(HERE / "providers.json", self.root / "state")

    def tearDown(self):
        self.temp.cleanup()

    def test_job_validation_rejects_unsafe_id(self):
        with self.assertRaises(ValueError):
            worker.valid_job({
                "id": "../../bad", "task": "x", "risk": "NORMAL",
                "base_commit": "a" * 40, "acceptance_commands": ["true"],
            })

    def test_job_validation_propagates_offline_fallback(self):
        job = worker.valid_job({
            "id": "github-test-issue-fallback", "task": "x", "risk": "NORMAL",
            "base_commit": "a" * 40, "acceptance_commands": ["true"],
            "allow_offline_fallback": True,
        })
        self.assertTrue(job.allow_offline_fallback)

    def test_reviewable_changes_requires_nonempty_status(self):
        with mock.patch.object(worker, "git", return_value=mock.Mock(stdout="")):
            self.assertEqual(worker.reviewable_changes(self.root), [])
        with mock.patch.object(worker, "git", return_value=mock.Mock(stdout=" M engineer/file.py\n?? docs/new.md\n")):
            self.assertEqual(worker.reviewable_changes(self.root), ["engineer/file.py", "docs/new.md"])

    def test_route_only_worker_returns_job_to_pending(self):
        paths = worker.queue_dirs(self.root / "state")
        job = {
            "id": "github-test-issue-1", "task": "change docs", "risk": "NORMAL",
            "deterministic_available": False, "substantial": True, "requires_review": True,
            "base_commit": "a" * 40, "context_paths": [], "acceptance_commands": ["true"],
        }
        (paths["pending"] / "github-test-issue-1.json").write_text(json.dumps(job), encoding="utf-8")
        with mock.patch.object(worker, "ensure_base"), \
             mock.patch.object(self.gov, "route", return_value={"status": "ROUTED", "provider": "groq", "model": "test"}):
            result = worker.process_one(self.gov, self.root / "state", self.root, HERE / "adapters/openhands.sh",
                                        False, 10, 10)
        self.assertEqual(result["status"], "ROUTED_DRY_RUN")
        self.assertTrue((paths["pending"] / "github-test-issue-1.json").exists())

    def test_empty_successful_agent_draft_is_retried_not_reviewed(self):
        paths = worker.queue_dirs(self.root / "state")
        job = {
            "id": "github-test-issue-noop", "task": "make a real change", "risk": "NORMAL",
            "deterministic_available": False, "substantial": True, "requires_review": True,
            "base_commit": "a" * 40, "context_paths": [], "acceptance_commands": ["true"],
        }
        pending = paths["pending"] / "github-test-issue-noop.json"
        pending.write_text(json.dumps(job), encoding="utf-8")
        completed = mock.Mock(returncode=0, stdout="done", stderr="")
        with mock.patch.object(worker, "ensure_base"), \
             mock.patch.object(self.gov, "route", return_value={"status": "ROUTED", "provider": "ollama", "model": "test"}), \
             mock.patch.object(worker, "worktree_for", return_value=self.root), \
             mock.patch.object(worker, "compact_packet", return_value={}), \
             mock.patch.object(worker, "provider_environment", return_value={}), \
             mock.patch.object(worker.subprocess, "run", return_value=completed), \
             mock.patch.object(worker, "acceptance", return_value=[{"command": "true", "returncode": 0, "stdout_tail": "", "stderr_tail": ""}]), \
             mock.patch.object(worker, "reviewable_changes", return_value=[]), \
             mock.patch.object(worker, "git", return_value=mock.Mock(returncode=0, stdout="")):
            result = worker.process_one(self.gov, self.root / "state", self.root, HERE / "adapters/openhands.sh",
                                        True, 10, 10)
        self.assertEqual(result["status"], "FAILED_ATTEMPT")
        self.assertIn("no reviewable workspace changes", result["error"])
        self.assertTrue(result["retry"])
        self.assertTrue((paths["pending"] / "github-test-issue-noop.json").exists())
        self.assertFalse((paths["awaiting_review"] / "github-test-issue-noop.json").exists())

    def test_high_risk_goes_to_blocked_not_agent(self):
        paths = worker.queue_dirs(self.root / "state")
        job = {
            "id": "github-test-issue-2", "task": "production change", "risk": "HIGH_RISK",
            "deterministic_available": False, "substantial": True, "requires_review": True,
            "base_commit": "a" * 40, "context_paths": [], "acceptance_commands": ["true"],
        }
        (paths["pending"] / "github-test-issue-2.json").write_text(json.dumps(job), encoding="utf-8")
        with mock.patch.object(worker, "ensure_base"):
            result = worker.process_one(self.gov, self.root / "state", self.root, HERE / "adapters/openhands.sh",
                                        True, 10, 10)
        self.assertEqual(result["status"], "BLOCKED_GOVERNOR_GATE")
        self.assertTrue((paths["blocked"] / "github-test-issue-2.json").exists())


if __name__ == "__main__":
    unittest.main()
