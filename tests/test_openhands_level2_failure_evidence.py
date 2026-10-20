from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/openhands-level2-current-profile.yml"


class OpenHandsLevel2FailureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()

    def test_checkpoint_dependency_is_imported_in_embedded_script(self):
        self.assertIn(
            "import json, os, pathlib, subprocess, sys, time, urllib.request, uuid",
            self.workflow,
        )

    def test_task_understanding_is_derived_from_issue_inspection_evidence(self):
        self.assertIn(
            '"task_understood":bool(evidence.get("issue_935_inspected",False))',
            self.workflow,
        )
        self.assertNotIn('"task_understood":True', self.workflow)

    def test_recovery_replays_authoritative_task_and_declared_tool_guidance(self):
        self.assertIn('"Tool boundary: use only tools exposed in this session', self.workflow)
        self.assertIn('input=json.dumps({**snapshot,"task_context":prompt})', self.workflow)
        self.assertIn('"text":ledger["recovery_message"]', self.workflow)

    def test_sanitized_conversation_checkpoint_precedes_incomplete_gate(self):
        marker = 'print("OPENHANDS_LEVEL2_CURRENT_PROFILE_EVIDENCE="'
        marker_at = self.workflow.index(marker)
        incomplete_at = self.workflow.index(
            'if not ledger.get("complete"):'
        )
        checkpoint = self.workflow[
            self.workflow.rfind("evidence_record={", 0, marker_at):marker_at
        ]

        self.assertLess(marker_at, incomplete_at)
        self.assertIn('pathlib.Path(os.environ["RUNNER_TEMP"])', checkpoint)
        self.assertIn("conversation_evidence", checkpoint)
        self.assertIn("temporary.replace(evidence_path)", checkpoint)

    def test_checkpoint_artifact_upload_runs_after_failure(self):
        step_name = "- name: Retain sanitized current-profile evidence"
        self.assertIn(step_name, self.workflow)
        upload_step = self.workflow.split(step_name, 1)[1].split(
            "\n      - name:", 1
        )[0]

        self.assertIn("if: always()", upload_step)
        self.assertIn("actions/upload-artifact@v4", upload_step)
        self.assertIn("openhands-level2-evidence.json", upload_step)
        self.assertIn("retention-days: 30", upload_step)

    def test_incomplete_ledger_still_fails_acceptance(self):
        gate_at = self.workflow.index('if not ledger.get("complete"):')
        incomplete_marker_at = self.workflow.index(
            'OPENHANDS_LEVEL2_CURRENT_PROFILE_LEDGER=INCOMPLETE'
        )
        pass_marker_at = self.workflow.index(
            "echo OPENHANDS_LEVEL2_CURRENT_PROFILE=PASS"
        )

        self.assertLess(gate_at, incomplete_marker_at)
        self.assertLess(incomplete_marker_at, pass_marker_at)


if __name__ == "__main__":
    unittest.main()
