import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "governor" / "scripts" / "openhands-github-task-hydrate.py"
spec = importlib.util.spec_from_file_location("task_hydrate", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def test_render_task_is_solution_neutral_and_bounded():
    issue = {"number": 935, "title": "Tiny real bug", "body": "inspect this"}
    comments = [{"user": {"login": "owner"}, "body": "context only"}]
    result = module.render_task("owner/repo", issue, comments, "/projects/repo")

    assert "Repository: owner/repo" in result
    assert "Persistent workspace: /projects/repo" in result
    assert "Issue: #935" in result
    assert "inspect this" in result
    assert "context only" in result
    assert "Independently inspect" in result
    assert "fix file" not in result.lower()


def test_render_task_caps_untrusted_issue_material():
    issue = {"number": 1, "title": "bounded", "body": "x" * (module.MAX_BODY_CHARS + 50)}
    comments = [
        {"user": {"login": "u"}, "body": "y" * (module.MAX_COMMENT_CHARS + 50)}
        for _ in range(module.MAX_COMMENTS + 5)
    ]
    result = module.render_task("owner/repo", issue, comments, "/projects/repo")

    assert "x" * (module.MAX_BODY_CHARS + 1) not in result
    assert result.count("Comment ") == module.MAX_COMMENTS
    assert "y" * (module.MAX_COMMENT_CHARS + 1) not in result
