from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_pa_has_single_current_information_processing_authority():
    old=(ROOT/'docs/architecture/personal-information-processing.md').read_text()
    current=(ROOT/'docs/architecture/personal-information-processing-paperless-first.md').read_text()
    authority=(ROOT/'docs/architecture/pa-ots-authority-map.md').read_text()
    assert 'SUPERSEDED' in old and 'not the current implementation plan' in old
    assert 'P0–P10 accepted' in current
    assert 'Paperless native mail is the production email-to-document ingestion path' in authority

def test_custom_email_paperless_adapter_is_acceptance_only_and_not_scheduled():
    adapter=(ROOT/'homelab/live/home/joshan/automation/lifeos_email_paperless_selective.py').read_text()
    assert 'must not be scheduled or used as a continuous production importer' in adapter
    active='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'.github/workflows').glob('*.yml'))
    # CI may compile/import the adapter, but no active workflow may execute its acceptance
    # path as a production ingestion job.
    assert 'lifeos_email_paperless_selective.py acceptance' not in active

def test_only_one_active_personal_task_publisher():
    hits=[]
    for p in ROOT.rglob('*.py'):
        if 'archive' in p.parts: continue
        text=p.read_text(errors='ignore')
        if 'www/lifeos_tasks.json' in text: hits.append(str(p.relative_to(ROOT)))
    assert hits==['homelab/live/home/joshan/automation/lifeos_task_reconciler.py'], hits
