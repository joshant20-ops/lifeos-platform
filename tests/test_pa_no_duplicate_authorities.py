import ast
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

def _task_view_writers(path):
    source=path.read_text(errors='ignore')
    try:
        tree=ast.parse(source)
    except SyntaxError:
        return False
    bindings=set()
    for node in ast.walk(tree):
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            value=node.value
            rendered=ast.unparse(value) if value is not None else ''
            if 'lifeos_tasks.json' in rendered and 'www' in rendered:
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                bindings.update(t.id for t in targets if isinstance(t,ast.Name))
    if not bindings:
        return False
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call):
            continue
        fn=node.func
        if isinstance(fn,ast.Attribute) and fn.attr in {'replace','rename','write_text','write_bytes'}:
            names={x.id for x in ast.walk(node) if isinstance(x,ast.Name)}
            if fn.attr in {'replace','rename'} and names.intersection(bindings):
                return True
            if fn.attr in {'write_text','write_bytes'} and isinstance(fn.value,ast.Name) and fn.value.id in bindings:
                return True
        if isinstance(fn,ast.Attribute) and fn.attr=='replace' and isinstance(fn.value,ast.Name) and fn.value.id=='os':
            names={x.id for x in ast.walk(node) if isinstance(x,ast.Name)}
            if len(node.args)>=2 and isinstance(node.args[1],ast.Name) and node.args[1].id in bindings:
                return True
    return False

def test_only_one_active_personal_task_publisher():
    publishers=[]
    for path in ROOT.rglob('*.py'):
        if 'archive' in path.parts:
            continue
        if _task_view_writers(path):
            publishers.append(str(path.relative_to(ROOT)))
    assert publishers==['homelab/live/home/joshan/automation/lifeos_task_reconciler.py'], publishers
