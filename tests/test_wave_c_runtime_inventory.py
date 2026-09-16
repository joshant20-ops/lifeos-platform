import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts/lifeos-wave-c-runtime-inventory.sh").read_text()
WORKFLOW = (ROOT / ".github/workflows/lifeos-wave-c-runtime-inventory.yml").read_text()


def test_inventory_is_read_only_and_keeps_mutation_gates_closed():
    assert "MUTATION_GATE=READ_ONLY" in SCRIPT
    assert "LEDGER_WRITES=BLOCKED" in SCRIPT
    assert "BANK_WRITES=BLOCKED" in SCRIPT
    assert "HMRC_SUBMISSIONS=BLOCKED" in SCRIPT
    for forbidden in (" curl -X POST", " curl -X PUT", " curl -X PATCH", " curl -X DELETE"):
        assert forbidden not in SCRIPT


def test_inventory_never_prints_secret_values_or_private_records():
    assert "-printf '%f\\n'" in SCRIPT
    assert "{{.Names}}" in SCRIPT
    assert "{{.Image}}" in SCRIPT
    for forbidden in ("cat /etc/lifeos/secrets", "printenv", "docker inspect -f '{{json .Config.Env}}'", "values()"):
        assert forbidden not in SCRIPT
    assert "values_list('id', flat=True).first()" in SCRIPT
    assert "document metadata or counts" in SCRIPT


def test_inventory_covers_shortlisted_and_reusable_interfaces():
    for marker in (
        "ACCOUNTING_FREEAGENT",
        "ACCOUNTING_XERO",
        "ACCOUNTING_QUICKBOOKS",
        "ACCOUNTING_SAGE",
        "OPEN_BANKING_TRUELAYER",
        "OPEN_BANKING_GOCARDLESS",
        "PAPERLESS_READ_BOUNDARY",
        "FINANCIAL_IMPORT_FORMAT_CANDIDATE",
    ):
        assert marker in SCRIPT


def test_workflow_uses_governed_pi_runner_and_canonical_reconcile():
    assert "lifeos-pi5" in WORKFLOW
    assert "scripts/reconcile-canonical-checkout.py" in WORKFLOW
    assert "lifeos-wave-c-runtime-inventory.sh" in WORKFLOW
    assert "REPOSITORY_FINAL=PASS" in WORKFLOW
