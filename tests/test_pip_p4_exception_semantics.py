from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SELECTOR=(ROOT/"scripts/lifeos-pip-p4-exception-selector.py").read_text()
BRIDGE=(ROOT/"homelab/live/home/joshan/automation/lifeos_paperless_local_ai.py").read_text()

def test_selector_is_exception_only_and_read_only():
    assert "native_match(doc)" in SELECTOR
    assert "Document.objects" in SELECTOR
    assert ".save(" not in SELECTOR
    assert ".update(" not in SELECTOR
    assert ".delete(" not in SELECTOR
    assert "P4_SELECTOR=PAPERLESS_NATIVE_EXCEPTION_ONLY" in SELECTOR

def test_private_content_not_default_output():
    assert "P4_PRIVATE_CONTENT_EMITTED=NONE" in SELECTOR
    assert "doc.content" not in SELECTOR.split("def main():",1)[1]

def test_bridge_is_governed_local_only():
    assert 'generate(prompt, privacy="local-only", force_provider="ollama")' in BRIDGE
    assert "_ollama(prompt" not in BRIDGE
    assert "paperless_writeback_performed': False" in BRIDGE
