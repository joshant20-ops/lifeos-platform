"""Privacy boundary for Actions' reconciler diagnostic summaries."""
import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "governor/scripts/deploy-pa-task-reconciler.sh"


def test_actions_summary_filter_accepts_only_numeric_error_counters():
    script = SCRIPT.read_text()
    match = re.search(r"grep -E '([^']+)'", script[script.index("# Forward only"):])
    assert match, "summary filter should use an explicit fixed-field allow-list"
    pattern = match.group(1)
    sample = "\n".join(
        [
            "TASK_FETCH_ERRORS=1",
            "TASK_CLASSIFICATION_ERRORS=0",
            "TASK_CLASSIFICATION_ERROR_TYPES=ValueError",
            "TASK_FETCH_ERROR_TYPES=PrivateClassName",
            "private@example.test document body",
        ]
    )
    result = subprocess.run(
        ["grep", "-E", pattern],
        input=sample,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "TASK_FETCH_ERRORS=1",
        "TASK_CLASSIFICATION_ERRORS=0",
    ]
    assert "PrivateClassName" not in result.stdout
    assert "private@example.test" not in result.stdout
