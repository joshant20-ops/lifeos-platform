"""Real pinned IQ ORM/native queue contracts, always against an isolated DB."""
import asyncio
import ast
import logging
from types import SimpleNamespace
import atexit
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.request
from uuid import uuid4
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///:memory:'
from governor.paperless_iq_patch import EXPECTED, UPSTREAM_REVISION, build_sources

if os.environ.get('IQ_NATIVE_BACKEND_ROOT'):
    sys.path.insert(0, os.environ['IQ_NATIVE_BACKEND_ROOT'])
else:
    workspace = tempfile.TemporaryDirectory()
    atexit.register(workspace.cleanup)
    source = Path(workspace.name) / 'source'
    source.mkdir()
    extras = {'backend/database.py': '19dee49d633bc17bdfe6205f8ee65fa264831e9f9112fec0fce6475578dd084b',
              'backend/orm_models.py': 'c0dc8804916f20c10fcdf58e4666f911ca9df8a4636cc1fe6e6106b38a9de403'}
    for name, digest in {**EXPECTED, **extras}.items():
        if os.environ.get('IQ_UPSTREAM_SOURCE'):
            raw = (Path(os.environ['IQ_UPSTREAM_SOURCE']) / name).read_bytes()
        else:
            url = f'https://raw.githubusercontent.com/knows-cloud/paperless-iq/{UPSTREAM_REVISION}/{name}'
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = response.read(524289)
        if len(raw) > 524288 or hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError('PINNED_NATIVE_TEST_SOURCE_MISMATCH')
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    target = Path(workspace.name) / 'patched'
    build_sources(source, target)
    for name in extras:
        (target / name).write_bytes((source / name).read_bytes())
    sys.path.insert(0, str(target))

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.database import Base
from backend.orm_models import AuditLogORM, DocumentTrackingORM, SuggestionORM
from backend.models import MetadataSuggestion
from backend.approval_queue import ApprovalQueueService
from backend.inbox_monitor import InboxMonitor, Scheduler


def suggestion(identifier):
    return MetadataSuggestion(id=uuid4(), document_id=identifier, status='pending',
        created_at=datetime.now(UTC), llm_provider='ollama', llm_model='fixture',
        analysis_mode='ocr', prompt_used='fixture', raw_llm_response='{}')


class NativeAutomationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_async_engine('sqlite+aiosqlite:///' + self.directory.name + '/isolated.db')
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.sessions()
        self.calls = []
        for identifier in range(1, 9):
            self.session.add(DocumentTrackingORM(document_id=identifier, embedding_stored=True))
        await self.session.commit()
        self.fetch = AsyncMock(return_value=list(range(1, 9)))

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()
        self.directory.cleanup()

    async def submit(self, identifier):
        self.calls.append(identifier)
        return await ApprovalQueueService(self.session).enqueue(suggestion(identifier), automation_limit=20)

    def scheduler(self, **kwargs):
        return Scheduler(self.session, self.fetch, self.submit, resource_check=lambda: True, **kwargs)

    async def test_embedded_tracking_is_eligible_and_total_run_is_capped(self):
        self.assertEqual(await self.scheduler(batch_size=2).run_batch(), [[8, 7]])
        self.assertEqual(self.calls, [8, 7])
        rows = (await self.session.execute(select(DocumentTrackingORM.last_analyzed_at,
            DocumentTrackingORM.embedding_stored).where(DocumentTrackingORM.document_id == 8))).one()
        self.assertIsNotNone(rows[0])
        self.assertTrue(rows[1])

    async def test_pending_and_human_rejected_completed_docs_are_not_reprocessed(self):
        await ApprovalQueueService(self.session).enqueue(suggestion(8))
        self.assertEqual(await self.scheduler(batch_size=2).run_batch(), [[7, 6]])
        await self.session.execute(update(SuggestionORM).where(SuggestionORM.document_id == 7).values(status='rejected'))
        await self.session.commit()
        self.assertEqual(await self.scheduler(batch_size=2).run_batch(), [[5, 4]])
        self.assertEqual(len(self.calls), len(set(self.calls)))
        self.assertNotIn(8, self.calls)

    async def test_queue_backpressure_prevents_fetching_or_inference(self):
        await ApprovalQueueService(self.session).enqueue(suggestion(1))
        await ApprovalQueueService(self.session).enqueue(suggestion(1))
        self.assertEqual(await self.scheduler(batch_size=5, pending_limit=3).run_batch(), [[8]])
        self.fetch.reset_mock()
        self.assertEqual(await self.scheduler(batch_size=5, pending_limit=3).run_batch(), [])
        self.fetch.assert_not_awaited()

    async def test_missing_persistence_never_marks_analysis_success(self):
        async def missing(identifier):
            return object()
        scheduler = Scheduler(self.session, self.fetch, missing, 1, resource_check=lambda: True)
        self.assertEqual(await scheduler.run_batch(), [])
        value = await self.session.scalar(select(DocumentTrackingORM.last_analyzed_at).where(DocumentTrackingORM.document_id == 8))
        self.assertIsNone(value)
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(AuditLogORM).where(AuditLogORM.action_type == 'analysis_failed')), 1)

    async def test_failure_budget_and_recovery_preserve_retryable_tracking(self):
        async def failed(identifier):
            self.calls.append(identifier)
            raise ConnectionError('fixture provider unavailable')
        scheduler = Scheduler(self.session, self.fetch, failed, 2, resource_check=lambda: True)
        self.assertEqual(await scheduler.run_batch(), [])
        self.assertEqual(await scheduler.run_batch(), [])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(await scheduler.run_batch(), [])
        self.assertEqual(len(self.calls), 3)
        await self.session.execute(update(AuditLogORM).values(changed_at=datetime.now(UTC) - timedelta(minutes=16)))
        await self.session.commit()
        self.calls.clear()
        self.assertEqual(await self.scheduler(batch_size=1).run_batch(), [[8]])
        self.assertEqual(self.calls, [8])

    async def test_resource_failure_does_not_start_work(self):
        scheduler = Scheduler(self.session, self.fetch, self.submit, 2, resource_check=lambda: False)
        self.assertEqual(await scheduler.run_batch(), [])
        self.fetch.assert_not_awaited()

    async def test_atomic_same_document_producers_create_only_one_pending(self):
        async def producer():
            async with self.sessions() as session:
                return await ApprovalQueueService(session).enqueue(suggestion(20), automation_limit=20)
        results = await asyncio.gather(producer(), producer())
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM).where(SuggestionORM.document_id == 20)), 1)

    async def test_atomic_cap_when_another_producer_fills_last_slot(self):
        await ApprovalQueueService(self.session).enqueue(suggestion(1))
        async def producer(identifier):
            async with self.sessions() as session:
                return await ApprovalQueueService(session).enqueue(suggestion(identifier), automation_limit=2)
        results = await asyncio.gather(producer(20), producer(21))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 2)

    async def test_other_producer_pending_during_analysis_is_preserved(self):
        async def raced(identifier):
            async with self.sessions() as other:
                await ApprovalQueueService(other).enqueue(suggestion(identifier))
            return await ApprovalQueueService(self.session).enqueue(suggestion(identifier), automation_limit=20)
        scheduler = Scheduler(self.session, self.fetch, raced, 1, resource_check=lambda: True)
        self.assertEqual(await scheduler.run_batch(), [])
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 1)
        self.assertIsNone(await self.session.scalar(select(DocumentTrackingORM.last_analyzed_at).where(DocumentTrackingORM.document_id == 8)))

    def callbacks(self, config, analyze):
        # Execute the actual generated callbacks with isolated dependencies. No
        # full FastAPI import, live endpoints, documents or inference services.
        import backend.inbox_monitor as policy
        resource_patch = patch.object(policy, 'resources_available', return_value=True)
        resource_mock = resource_patch.start()
        self.addCleanup(resource_patch.stop)
        tree = ast.parse((Path(policy.__file__).parent / 'main.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name in {'_iq_lock', '_make_analysis_callbacks'}]
        globals_ = dict(asyncio=asyncio, FastAPI=object, AsyncSession=object,
            _settings_svc=SimpleNamespace(config=config), select=select, func=func,
            SuggestionORM=SuggestionORM, ApprovalQueueService=ApprovalQueueService,
            logger=logging.getLogger('fixture.callbacks'), resource_mock=resource_mock,
            Priority=SimpleNamespace(ANALYSIS='analysis'))
        exec(compile(tree, 'generated_callbacks', 'exec'), globals_)
        app = SimpleNamespace(state=SimpleNamespace(paperless_client=object(),
            manual_analysis_svc=SimpleNamespace(analyze=analyze)))
        return globals_, app

    async def test_callbacks_never_auto_apply_and_recheck_after_inference(self):
        config = SimpleNamespace(automation_enabled=True, auto_apply=True,
            automation_pending_limit=20, inbox_tag_id=None)
        analyze = AsyncMock(return_value=suggestion(8))
        globals_, app = self.callbacks(config, analyze)
        _, submit = globals_['_make_analysis_callbacks'](app, self.session, 'fixture')
        self.assertIsNone(await submit(8))
        analyze.assert_not_awaited()
        config.auto_apply = False
        async def changed_during_inference(identifier):
            config.auto_apply = True
            return suggestion(identifier)
        app.state.manual_analysis_svc.analyze = changed_during_inference
        # The native service object is shared by the callback closure.
        self.assertIsNone(await submit(8))
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 0)

    async def test_concurrent_callbacks_share_lock_and_only_infer_once(self):
        config = SimpleNamespace(automation_enabled=True, auto_apply=False,
            automation_pending_limit=20, inbox_tag_id=None)
        async def analyze(identifier):
            await asyncio.sleep(0)
            self.calls.append(identifier)
            return suggestion(identifier)
        globals_, app = self.callbacks(config, analyze)
        async def producer():
            async with self.sessions() as session:
                _, submit = globals_['_make_analysis_callbacks'](app, session, 'fixture')
                return await submit(8)
        results = await asyncio.gather(producer(), producer())
        self.assertEqual(self.calls, [8])
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 1)

    async def test_queued_execution_rechecks_resources_and_flags_without_failures(self):
        config = SimpleNamespace(automation_enabled=True, auto_apply=False,
            automation_pending_limit=20, inbox_tag_id=None)
        analyze = AsyncMock(return_value=suggestion(8))
        globals_, app = self.callbacks(config, analyze)
        for change in ('resources', 'disabled', 'auto_apply'):
            config.automation_enabled, config.auto_apply = True, False
            globals_['resource_mock'].return_value = True
            async def queue_submit(priority, job, **kwargs):
                if change == 'resources':
                    globals_['resource_mock'].return_value = False
                elif change == 'disabled':
                    config.automation_enabled = False
                else:
                    config.auto_apply = True
                return await job()
            app.state.ollama_queue = SimpleNamespace(submit=queue_submit)
            _, submit = globals_['_make_analysis_callbacks'](app, self.session, 'fixture')
            self.assertIsNone(await submit(8))
        analyze.assert_not_awaited()
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(AuditLogORM)), 0)
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 0)

    async def test_callback_persistence_error_propagates_for_failure_accounting(self):
        config = SimpleNamespace(automation_enabled=True, auto_apply=False,
            automation_pending_limit=20, inbox_tag_id=None)
        globals_, app = self.callbacks(config, AsyncMock(return_value=suggestion(8)))
        _, submit = globals_['_make_analysis_callbacks'](app, self.session, 'fixture')
        with patch.object(ApprovalQueueService, 'enqueue', side_effect=RuntimeError('fixture persistence failure')):
            scheduler = Scheduler(self.session, self.fetch, submit, 1, resource_check=lambda: True)
            self.assertEqual(await scheduler.run_batch(), [])
        self.assertIsNone(await self.session.scalar(select(DocumentTrackingORM.last_analyzed_at).where(DocumentTrackingORM.document_id == 8)))
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(AuditLogORM).where(AuditLogORM.action_type == 'analysis_failed')), 1)

    async def test_automatic_analysis_timeout_is_bounded_and_retryable(self):
        config = SimpleNamespace(automation_enabled=True, auto_apply=False,
            automation_pending_limit=20, inbox_tag_id=None, llm_timeout_seconds=1)
        cancelled = asyncio.Event()
        async def hanging(identifier):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        globals_, app = self.callbacks(config, hanging)
        _, submit = globals_['_make_analysis_callbacks'](app, self.session, 'fixture')
        scheduler = Scheduler(self.session, self.fetch, submit, 1, resource_check=lambda: True)
        self.assertEqual(await asyncio.wait_for(scheduler.run_batch(), 3), [])
        self.assertTrue(cancelled.is_set())
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 0)
        self.assertIsNone(await self.session.scalar(select(DocumentTrackingORM.last_analyzed_at).where(DocumentTrackingORM.document_id == 8)))
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(AuditLogORM).where(AuditLogORM.action_type == 'analysis_failed')), 1)

    async def test_terminal_uuid_idempotence_releases_sqlite_writer(self):
        existing = suggestion(8)
        await ApprovalQueueService(self.session).enqueue(existing)
        await self.session.execute(update(SuggestionORM).values(status='rejected'))
        await self.session.commit()
        result = await ApprovalQueueService(self.session).enqueue(existing, automation_limit=20)
        self.assertIsNone(result)
        self.assertFalse(self.session.in_transaction())
        collision = existing.model_copy(update={'document_id': 99})
        result = await ApprovalQueueService(self.session).enqueue(collision, automation_limit=20)
        self.assertEqual(result.status, 'rejected')
        self.assertFalse(self.session.in_transaction())
        async with self.sessions() as other:
            await asyncio.wait_for(ApprovalQueueService(other).enqueue(suggestion(9), automation_limit=20), 2)
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 2)

    async def test_failed_automatic_enqueue_releases_sqlite_writer(self):
        import backend.approval_queue as queue_module
        with patch.object(queue_module, '_pydantic_to_orm', side_effect=RuntimeError('fixture conversion failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixture conversion failure'):
                await ApprovalQueueService(self.session).enqueue(suggestion(8), automation_limit=20)
        self.assertFalse(self.session.in_transaction())
        async with self.sessions() as other:
            await asyncio.wait_for(ApprovalQueueService(other).enqueue(suggestion(9), automation_limit=20), 2)

    async def test_full_historical_population_is_sequential_and_capped(self):
        self.fetch.return_value = list(range(1, 2655))
        self.assertEqual(await self.scheduler(batch_size=5).run_batch(), [[2654, 2653, 2652, 2651, 2650]])
        self.assertEqual(len(self.calls), 5)
        # Even an accidentally enormous batch cannot exceed the global ceiling.
        await self.scheduler(batch_size=2654).run_batch()
        self.assertEqual(len(self.calls), 20)
        await self.scheduler(batch_size=2654).run_batch()
        self.assertEqual(len(self.calls), 20)

    async def test_legacy_human_dispositions_without_tracking_stamp_are_preserved(self):
        for identifier, status in ((8, 'rejected'), (7, 'approved')):
            await ApprovalQueueService(self.session).enqueue(suggestion(identifier))
            await self.session.execute(update(SuggestionORM).where(
                SuggestionORM.document_id == identifier).values(status=status))
        await self.session.commit()
        self.assertEqual(await self.scheduler(batch_size=1).run_batch(), [[6]])
        self.assertEqual(self.calls, [6])
        # Another producer's terminal disposition during inference also defers.
        self.assertIsNone(await ApprovalQueueService(self.session).enqueue(suggestion(8), automation_limit=20))
        self.assertEqual(await self.session.scalar(select(func.count()).select_from(SuggestionORM)), 3)

    async def test_daily_document_failure_budget_skips_without_blocking_others(self):
        for _ in range(3):
            self.session.add(AuditLogORM(document_id=8, field_name='analysis',
                action_type='analysis_failed', change_source='automation',
                changed_at=datetime.now(UTC) - timedelta(hours=1)))
        await self.session.commit()
        self.assertEqual(await self.scheduler(batch_size=1).run_batch(), [[7]])
        self.assertEqual(self.calls, [7])

    async def test_resource_pressure_between_documents_stops_current_run(self):
        checks = iter([True, True, False])
        scheduler = Scheduler(self.session, self.fetch, self.submit, 5,
            resource_check=lambda: next(checks))
        self.assertEqual(await scheduler.run_batch(), [[8]])
        self.assertEqual(self.calls, [8])

    async def test_structured_ollama_has_bounded_sampling_options(self):
        with patch.dict(os.environ, {key: '' for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')}):
            from backend.providers.ollama_provider import OllamaProvider
        provider = OllamaProvider('http://unused-fixture', 'fixture')
        client = type('Client', (), {'chat': AsyncMock(return_value={'message': {'content': '{}'}})})()
        provider._client_instance = client
        await provider.complete('fixture', 32, output_schema={'type': 'object'})
        self.assertEqual(client.chat.call_args.kwargs['options'], {'num_predict': 32, 'temperature': 0.0, 'seed': 42})


class SourceBuildTests(unittest.TestCase):
    def test_rejects_unknown_preimage_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backend').mkdir()
            (root / 'backend/main.py').write_text('unexpected source')
            with self.assertRaisesRegex(ValueError, 'SOURCE_PREIMAGE_MISMATCH'):
                build_sources(root, root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_existing_output_is_never_overwritten(self):
        source_path = os.environ.get('IQ_UPSTREAM_SOURCE') or globals().get('source')
        if source_path is None:
            self.skipTest('native image test has no upstream fixture')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'preserved'
            marker.write_text('fixture')
            with self.assertRaises(FileExistsError):
                build_sources(source_path, root)
            self.assertEqual(marker.read_text(), 'fixture')


if __name__ == '__main__':
    unittest.main(verbosity=2)
