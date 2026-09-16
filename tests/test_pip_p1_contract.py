import json
import re
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "governor/contracts/personal-information-processing.schema.json"
TAXONOMY = ROOT / "governor/contracts/personal-information-processing-taxonomy.v1.json"
FIXTURES = ROOT / "governor/contracts/examples/personal-information-processing.synthetic.json"
ARCHITECTURE = ROOT / "docs/architecture/personal-information-processing.md"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)


def validate(value, rule, root):
    if "$ref" in rule:
        target = root
        for part in rule["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return validate(value, target, root)
    if "anyOf" in rule:
        failures = []
        for candidate in rule["anyOf"]:
            try:
                validate(value, candidate, root)
                return
            except AssertionError as error:
                failures.append(str(error))
        raise AssertionError(f"no anyOf branch accepted {value!r}: {failures}")
    if "const" in rule:
        assert value == rule["const"]
    if "enum" in rule:
        assert value in rule["enum"]
    kinds = rule.get("type")
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if kinds:
        accepted = {
            "object": lambda x: isinstance(x, dict),
            "array": lambda x: isinstance(x, list),
            "string": lambda x: isinstance(x, str),
            "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
            "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
            "boolean": lambda x: isinstance(x, bool),
            "null": lambda x: x is None,
        }
        assert any(accepted[k](value) for k in kinds)
    if isinstance(value, dict):
        required = set(rule.get("required", []))
        assert required <= set(value)
        if rule.get("additionalProperties") is False:
            assert set(value) <= set(rule.get("properties", {}))
        for key, child in value.items():
            if key in rule.get("properties", {}):
                validate(child, rule["properties"][key], root)
    if isinstance(value, list):
        if rule.get("uniqueItems"):
            assert len({json.dumps(x, sort_keys=True) for x in value}) == len(value)
        if "items" in rule:
            for child in value:
                validate(child, rule["items"], root)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        assert value >= rule.get("minimum", value)
        assert value <= rule.get("maximum", value)
    if isinstance(value, str):
        if "pattern" in rule:
            assert re.search(rule["pattern"], value)
        if rule.get("format") == "date":
            date.fromisoformat(value)
        if rule.get("format") == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def test_schema_is_strict_versioned_local_proposal_contract():
    schema = load(SCHEMA)
    assert schema["$schema"].endswith("draft/2020-12/schema")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": 1}
    assert schema["properties"]["privacy"] == {"const": "local-only"}
    assert schema["properties"]["mode"] == {"const": "proposal-only"}
    assert schema["$defs"]["source"]["properties"]["content_copied"] == {"const": False}
    mutation = schema["$defs"]["mutation_control"]["properties"]
    assert all(value == {"const": False} for value in mutation.values())


def test_taxonomy_and_schema_enums_are_identical_and_bounded():
    schema, taxonomy = load(SCHEMA), load(TAXONOMY)
    classification = schema["$defs"]["classification"]["properties"]
    assert taxonomy["domains"] == classification["domain"]["enum"]
    assert taxonomy["information_types"] == classification["information_type"]["enum"]
    assert len(taxonomy["domains"]) <= 8
    assert len(taxonomy["information_types"]) <= 16
    assert taxonomy["source_metadata_policy"]["replace_user_organisation_automatically"] is False


def test_synthetic_fixtures_cover_success_review_and_exception_semantics():
    schema = load(SCHEMA)
    records = load(FIXTURES)["fixtures"]
    assert {r["processing"]["state"] for r in records} == {"processed", "review", "ocr-failure"}
    assert {r["classification"]["confidence"]["band"] for r in records} == {"high", "medium", "unknown"}
    assert {r["exception"]["code"] for r in records} == {"none", "insufficient-evidence", "ocr-missing"}
    required = set(load(SCHEMA)["required"])
    for record in records:
        validate(record, schema, schema)
        assert set(record) == required
        assert record["source"]["system"] == "synthetic-fixture"
        assert record["source"]["content_copied"] is False
        assert record["mutation_control"] == {
            "production_write_permitted": False,
            "paperless_write_performed": False,
            "gmail_write_performed": False,
            "authority_delete_performed": False,
        }


def test_fixture_has_no_private_payload_or_credential_fields():
    fixture = load(FIXTURES)
    forbidden = {
        "title", "filename", "content", "ocr", "subject", "body", "attachment",
        "name", "address", "account_number", "sort_code", "iban", "balance",
        "amount", "tenant", "credential", "password", "token", "secret", "raw_payload",
    }
    assert {k.lower() for k in walk_keys(fixture)}.isdisjoint(forbidden)
    assert "synthetic" in json.dumps(fixture).lower()


def test_contract_preserves_authoritative_source_references_and_ai_limits():
    schema = load(SCHEMA)
    source = schema["$defs"]["source"]["properties"]
    assert source["system"]["enum"] == ["synthetic-fixture", "paperless", "gmail"]
    assert "authoritative_ref" in source
    methods = schema["$defs"]["classification"]["properties"]["method"]["enum"]
    assert "deterministic" in methods and "local-ai-proposal" in methods
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "P1 processing contract" in text
    assert "synthetic fixtures only" in text
    assert "no production Paperless or Gmail mutation" in text
