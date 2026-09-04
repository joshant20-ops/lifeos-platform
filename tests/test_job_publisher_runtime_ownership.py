import importlib.machinery
import importlib.util
import pathlib

SOURCE = pathlib.Path('homelab/live/usr/local/sbin/lifeos-job-publisher')


def load_module():
    loader = importlib.machinery.SourceFileLoader('lifeos_job_publisher_runtime_ownership', str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_all_runtime_queue_spellings_are_protected_from_git_sync():
    module = load_module()
    assert 'jobs/staging' in module.RUNTIME_SPECS
    assert 'jobs/staged' in module.RUNTIME_SPECS
    assert 'jobs/pending' in module.RUNTIME_SPECS
    assert 'jobs/archive' in module.RUNTIME_SPECS
    assert 'jobs/scripts' in module.RUNTIME_SPECS
    assert 'jobs/change-scripts' in module.RUNTIME_SPECS
    assert 'jobs/root-scripts' in module.RUNTIME_SPECS
    assert 'results' in module.RUNTIME_SPECS
    assert 'state' in module.RUNTIME_SPECS
