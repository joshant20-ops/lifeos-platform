import copy
import importlib.util
import json
from pathlib import Path

from tests.test_pip_p1_contract import validate


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "homelab/live/home/joshan/automation/lifeos_pip_deterministic.py"
SPEC = importlib.util.spec_from_file_location("pip_deterministic", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(**overrides):
    value = {
        "id": 42, "checksum": "a" * 64,
        "title": "Synthetic rental repair invoice",
        "content": "Synthetic invoice for property repair. Invoice reference SYN-1.",
        "created": "2026-08-20", "modified": "2026-09-01T12:00:00+00:00",
        "correspondent_id": 7, "document_type_name": "Synthetic invoice",
        "tag_names": ["Synthetic property"],
    }
    value.update(overrides)
    return value


def test_processor_is_idempotent_and_preserves_authority():
    document = fixture()
    first = MODULE.process(document, "0" * 40)
    second = MODULE.process(copy.deepcopy(document), "0" * 40)
    assert first == second
    assert MODULE.logical_digest([first]) == MODULE.logical_digest([second])
    assert first["source"]["system"] == "paperless"
    assert first["source"]["content_copied"] is False
    assert first["source"]["authoritative_ref"] == "paperless:document:42"
    assert "content" not in first and "title" not in first
    schema = json.loads((ROOT / "governor/contracts/personal-information-processing.schema.json").read_text())
    validate(first, schema, schema)


def test_known_property_invoice_is_deterministic_high_confidence():
    record = MODULE.process(fixture(), "0" * 40)
    assert record["classification"]["domain"] == "property"
    assert record["classification"]["information_type"] == "invoice"
    assert record["classification"]["method"] == "deterministic"
    assert record["classification"]["confidence"]["band"] == "high"
    assert record["processing"]["state"] == "processed"


def test_unknown_and_conflict_fail_toward_semantic_queue():
    unknown = MODULE.process(fixture(title="Synthetic archive", content="Unclassified synthetic material", document_type_name="", tag_names=[]), "0" * 40)
    conflict = MODULE.process(fixture(title="Synthetic payslip and vehicle MOT", content="payslip vehicle MOT", document_type_name="", tag_names=[]), "0" * 40)
    assert unknown["processing"]["state"] == "pending-semantic"
    assert unknown["exception"]["code"] == "insufficient-evidence"
    assert conflict["processing"]["state"] == "pending-semantic"
    assert conflict["exception"]["code"] == "classification-conflict"


def test_all_production_mutation_controls_are_false():
    controls = MODULE.process(fixture(), "0" * 40)["mutation_control"]
    assert controls and all(value is False for value in controls.values())
    source = PATH.read_text(encoding="utf-8")
    for forbidden in ("._ollama(", "openai", "Document.objects.update", "Document.objects.create", ".save(", ".delete("):
        assert forbidden not in source


def test_representative_sampling_is_stable_and_bounded():
    documents = [fixture(id=i, checksum=(f"{i:064x}"[-64:])) for i in range(1, 301)]
    first = MODULE.representative_sample(documents, 96)
    second = MODULE.representative_sample(list(reversed(documents)), 96)
    assert [x["id"] for x in first] == [x["id"] for x in second]
    assert len(first) == 96
