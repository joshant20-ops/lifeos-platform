from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SELECTOR=(ROOT/"scripts/lifeos-pip-p4-exception-selector.py").read_text()
BRIDGE=(ROOT/"homelab/live/home/joshan/automation/lifeos_paperless_local_ai.py").read_text()

def test_selector_reuses_accepted_native_evaluator_and_is_read_only():
    assert 'p2_library=p2_source.rsplit' in SELECTOR
    assert "representative_sample(documents)" in SELECTOR
    assert "native_matches(" in SELECTOR
    assert ".save(" not in SELECTOR and ".update(" not in SELECTOR and ".delete(" not in SELECTOR
    assert "P4_SELECTOR=PAPERLESS_NATIVE_EXCEPTION_ONLY" in SELECTOR

def test_private_content_not_emitted():
    assert "P4_PRIVATE_CONTENT_EMITTED=NONE" in SELECTOR
    assert "print(document" not in SELECTOR and "print(unresolved)" not in SELECTOR

def test_bridge_is_governed_local_only():
    assert 'generate(prompt, privacy="local-only", force_provider="ollama")' in BRIDGE
    assert "_ollama(prompt" not in BRIDGE
    assert "paperless_writeback_performed': False" in BRIDGE
