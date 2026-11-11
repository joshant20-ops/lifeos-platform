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


def test_restore_scope_rejects_user_controlled_paths():
    assert gateway.parse_request(["restore-rehearsal"]) == ("restore-rehearsal", [])
    assert gateway.parse_request(["restore-rehearsal", "adguard-config"]) == (
        "restore-rehearsal", ["adguard-config"],
    )
    assert gateway.parse_request(["restore-rehearsal", "adguard-tree"]) == (
        "restore-rehearsal", ["adguard-tree"],
    )
    assert gateway.parse_request(["restore-rehearsal", "adguard-archive"]) == (
        "restore-rehearsal", ["adguard-archive"],
    )
    for args in (["restore-rehearsal", "adguard-archive", "/tmp/other"],
                 ["restore-rehearsal", "adguard-tree", "/tmp/other"],
                 ["restore-rehearsal", "/tmp/other"],
                 ["restore-rehearsal", "adguard-config", "/tmp/other"]):
        try:
            gateway.parse_request(args)
        except SystemExit as error:
            assert error.code == 64
        else:
            raise AssertionError("arbitrary path was accepted")

def test_mqtt_rotation_scope_rejects_arguments():
    assert gateway.parse_request(["storage-mqtt-retain-rotation"]) == (
        "storage-mqtt-retain-rotation", [],
    )
    try:
        gateway.parse_request(["storage-mqtt-retain-rotation", "arbitrary"])
    except SystemExit as exc:
        assert exc.code == 64
    else:
        raise AssertionError("rotation accepted a caller-supplied argument")

def test_mqtt_archive_scope_rejects_arguments():
    assert gateway.parse_request(["storage-mqtt-retained-archive"]) == (
        "storage-mqtt-retained-archive", [],
    )
    try:
        gateway.parse_request(["storage-mqtt-retained-archive", "arbitrary"])
    except SystemExit as exc:
        assert exc.code == 64
    else:
        raise AssertionError("archive accepted a caller-supplied argument")

def test_mqtt_log_review_accepts_only_fixed_modes():
    for mode in ("retained", "monthly"):
        assert gateway.parse_request(["storage-mqtt-log-review", mode]) == (
            "storage-mqtt-log-review", [mode],
        )
    for argv in (["storage-mqtt-log-review"], ["storage-mqtt-log-review", "/tmp/input"]):
        try:
            gateway.parse_request(argv)
        except SystemExit as exc:
            assert exc.code == 64
        else:
            raise AssertionError("review accepted unsupported arguments")

def test_mqtt_reclaim_scope_rejects_arguments():
    assert gateway.parse_request(["storage-mqtt-verified-reclaim"]) == (
        "storage-mqtt-verified-reclaim", [],
    )
    try:
        gateway.parse_request(["storage-mqtt-verified-reclaim", "arbitrary"])
    except SystemExit as exc:
        assert exc.code == 64
    else:
        raise AssertionError("reclaim accepted a caller-supplied argument")
