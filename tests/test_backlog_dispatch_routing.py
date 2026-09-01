import importlib.machinery
import os
from pathlib import Path


SOURCE = Path("governor/autonomous_agent.py")


def load_agent(tmp_path):
    old = os.environ.get("LIFEOS_AGENT_STATE")
    os.environ["LIFEOS_AGENT_STATE"] = str(tmp_path / "state")
    try:
        return importlib.machinery.SourceFileLoader(
            f"dispatch_agent_{tmp_path.name}", str(SOURCE)
        ).load_module()
    finally:
        if old is None:
            os.environ.pop("LIFEOS_AGENT_STATE", None)
        else:
            os.environ["LIFEOS_AGENT_STATE"] = old


def configure_token(module, tmp_path, monkeypatch):
    token_file = tmp_path / "dispatcher.token"
    token_file.write_text("test-dispatch-capability\n")
    monkeypatch.setattr(module, "DISPATCH_TOKEN_FILE", str(token_file))
    return {"Authorization": "Bearer test-dispatch-capability"}


def test_ordinary_submission_keeps_conservative_automatic_route(tmp_path, monkeypatch):
    module = load_agent(tmp_path)
    monkeypatch.setattr(module, "BUILDER", "/cloud")
    assert module.authenticated_dispatch_route({}, {"request": "private documents"}) == (None, None)
    assert module.builder_route({"privacy": "local-only"}) == ("local", None)
    assert module.builder_route({"privacy": "normal"}) == ("normal", "/cloud")


def test_unauthorized_caller_cannot_assert_less_restrictive_route(tmp_path, monkeypatch):
    module = load_agent(tmp_path)
    configure_token(module, tmp_path, monkeypatch)
    assert module.authenticated_dispatch_route(
        {}, {"request": "private documents", "dispatch_builder": "normal"}
    ) == (None, "dispatcher_capability_required")
    assert module.authenticated_dispatch_route(
        {"Authorization": "Bearer wrong"}, {"dispatch_builder": "normal"}
    ) == (None, "dispatcher_capability_required")


def test_dispatcher_accepts_exactly_two_builder_classes(tmp_path, monkeypatch):
    module = load_agent(tmp_path)
    headers = configure_token(module, tmp_path, monkeypatch)
    assert module.authenticated_dispatch_route(headers, {"dispatch_builder": "normal"}) == ("normal", None)
    assert module.authenticated_dispatch_route(headers, {"dispatch_builder": "local"}) == ("local", None)
    for invalid in ("cloud", "LOCAL", "", None, 1):
        assert module.authenticated_dispatch_route(headers, {"dispatch_builder": invalid}) == (
            None, "invalid_dispatch_builder"
        )


def test_authenticated_decision_is_not_reclassified_from_prompt_wording(tmp_path, monkeypatch):
    module = load_agent(tmp_path)
    headers = configure_token(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "BUILDER", "/cloud")
    route, error = module.authenticated_dispatch_route(
        headers, {"request": "mentions private documents", "dispatch_builder": "normal"}
    )
    assert error is None
    job = module.new_job("mentions private documents", dispatch_builder=route)
    assert job["privacy"] == "normal"
    assert module.builder_route(job) == ("normal", "/cloud")


def test_authenticated_local_route_remains_fail_closed_when_unavailable(tmp_path, monkeypatch):
    module = load_agent(tmp_path)
    headers = configure_token(module, tmp_path, monkeypatch)
    route, error = module.authenticated_dispatch_route(
        headers, {"request": "ordinary wording", "dispatch_builder": "local"}
    )
    assert error is None
    monkeypatch.setattr(module, "LOCAL_BUILDER", "")
    assert module.builder_route({"privacy": "normal", "dispatch_builder": route}) == ("local", None)


def test_installer_sends_route_only_with_systemd_credential():
    installer = Path("governor/scripts/install-backlog-runner-pi5.sh").read_text()
    assert 'payload = {"request": prompt, "dispatch_builder": "local" if is_private else "normal"}' in installer
    assert 'LoadCredential=backlog-dispatcher.token:$DISPATCH_TOKEN' in installer
    assert 'req.add_header("Authorization", f"Bearer {token}")' in installer
