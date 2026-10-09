import importlib.util
import importlib.machinery
import pathlib

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "homelab" / "live" / "usr" / "local" / "sbin" / "lifeos-deploy-gateway"
loader = importlib.machinery.SourceFileLoader("lifeos_deploy_gateway", str(MODULE_PATH))
spec = importlib.util.spec_from_loader("lifeos_deploy_gateway", loader)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def test_adguard_dns_operation_is_narrowly_allowlisted_and_root_run():
    assert gateway.OPS["configure-ai-dns"] == {
        "script": "scripts/lifeos-configure-ai-dns.sh",
        "privileged": True,
    }
    assert gateway.parse_request(["configure-ai-dns"]) == ("configure-ai-dns", [])


def test_adguard_dns_operation_rejects_arguments(capsys):
    try:
        gateway.parse_request(["configure-ai-dns", "arbitrary"])
    except SystemExit as error:
        assert error.code == 64
    else:
        raise AssertionError("allow-listed DNS operation accepted arbitrary arguments")
    assert "configure-ai-dns" in capsys.readouterr().out
