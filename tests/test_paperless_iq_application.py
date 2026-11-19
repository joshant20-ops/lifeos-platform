"""Full native ASGI lifecycle with synthetic HTTP transports and temporary data.

Explicit opt-in: IQ_APP_SOURCE must name a complete patched public IQ source tree.
No production credentials, mounts, network services or document data are used.
"""
import os
import unittest
if not os.environ.get('IQ_APP_SOURCE'):
    raise unittest.SkipTest('full IQ application fixture not requested')

import asyncio
import atexit
from contextlib import AsyncExitStack
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

DATA = tempfile.TemporaryDirectory(prefix='iq-stage2a-synthetic-')
atexit.register(DATA.cleanup)
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///' + DATA.name + '/fixture.db',
    SECRET_KEY='stage2a-synthetic-key', PAPERLESS_URL='http://paperless.synthetic',
    PAPERLESS_TOKEN='fixture-token', PIQ_OLLAMA_URL='http://ollama.synthetic',
    PIQ_LLM_MODEL='fixture-model', PIQ_AUTOMATION_ENABLED='false',
    PIQ_AUTO_APPLY='false', PIQ_SMART_ENTITY_SELECTION='false',
    PIQ_BATCH_SIZE='5', PIQ_POLL_INTERVAL_SECONDS='60', ANONYMIZED_TELEMETRY='False')
for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(os.environ['IQ_APP_SOURCE']).resolve()))

import httpx
from datetime import UTC, datetime, timedelta
from sqlalchemy import func, select, update as sa_update
from backend import main as native
from backend.database import AsyncSessionLocal, engine
from backend.orm_models import DocumentTrackingORM, SuggestionORM, AuditLogORM
from backend.settings_service import SettingsService


class FullApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_start_poll_disable_reload_and_restart(self):
        requests, analyses, provider_attempts, polls = [], [], [], []
        provider_fails = False
        metadata_writes = []

        def transport(request):
            requests.append((request.method, request.url.host, request.url.path))
            host, path = request.url.host, request.url.path
            if host == 'paperless.synthetic':
                if path == '/api/token/' and request.method == 'POST':
                    if json.loads(request.content) != {'username': 'fixture', 'password': 'fixture'}:
                        return httpx.Response(400, json={'detail': 'synthetic invalid credentials'})
                    return httpx.Response(200, json={'token': 'fixture-user-token'})
                if request.method != 'GET':
                    metadata_writes.append((request.method, path))
                    raise AssertionError('synthetic Paperless metadata mutation forbidden')
                if path == '/api/users/':
                    return httpx.Response(200, json={'results': [{'username': 'fixture', 'is_superuser': True}]})
                if path == '/api/documents/':
                    return httpx.Response(200, json={'count': 2654, 'next': None,
                        'results': [{'id': i} for i in range(1, 2655)]})
                if path.startswith('/api/documents/'):
                    identifier = int(path.strip('/').split('/')[2])
                    return httpx.Response(200, json={'id': identifier, 'title': 'Synthetic fixture',
                        'content': 'Synthetic invoice fixture. No personal data.',
                        'tags': [], 'custom_fields': [], 'document_type': None, 'correspondent': None})
                if path in ('/api/tags/', '/api/correspondents/', '/api/document_types/',
                            '/api/storage_paths/', '/api/custom_fields/'):
                    return httpx.Response(200, json={'count': 0, 'next': None, 'results': []})
                if path == '/api/':
                    return httpx.Response(200, json={'version': 'fixture'})
            if host == 'ollama.synthetic':
                if path == '/api/chat':
                    provider_attempts.append(1)
                    if provider_fails:
                        return httpx.Response(503, json={'error': 'synthetic provider outage'})
                    body = json.loads(request.content)
                    self.assertEqual(body['options']['temperature'], 0.0)
                    self.assertEqual(body['options']['seed'], 42)
                    analyses.append(body['model'])
                    return httpx.Response(200, json={'model': 'fixture-model', 'done': True,
                        'message': {'role': 'assistant', 'content': json.dumps({
                            'title': 'Synthetic pending proposal', 'tags': [], 'custom_fields': {}})}})
                if path == '/api/tags':
                    return httpx.Response(200, json={'models': [{'model': 'fixture-model', 'name': 'fixture-model'}]})
            raise AssertionError('unexpected synthetic request: ' + request.method + ' ' + str(request.url))

        original_init = httpx.AsyncClient.__init__
        def isolated_client(client, *args, **kwargs):
            if 'transport' not in kwargs:
                kwargs['transport'] = httpx.MockTransport(transport)
            kwargs['trust_env'] = False
            original_init(client, *args, **kwargs)

        async def pending():
            async with AsyncSessionLocal() as session:
                return int(await session.scalar(select(func.count()).select_from(SuggestionORM)) or 0)

        async def wait_for_pending(count):
            async with asyncio.timeout(10):
                while await pending() < count:
                    await asyncio.sleep(0.01)

        original_poll = native.InboxMonitor.poll
        async def recorded_poll(monitor):
            try:
                return await original_poll(monitor)
            finally:
                polls.append(1)

        async def wait_for_poll_after(before):
            async with asyncio.timeout(10):
                while len(polls) <= before:
                    await asyncio.sleep(0.01)

        async with AsyncExitStack() as stack:
            stack.enter_context(patch.object(native.InboxMonitor, 'poll', recorded_poll))
            stack.enter_context(patch.object(httpx.AsyncClient, '__init__', isolated_client))
            stack.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('network disabled')))
            stack.enter_context(patch.object(socket.socket, 'connect_ex', side_effect=AssertionError('network disabled')))
            # Vector/index acceptance is separate; prevent optional store side effects.
            stack.enter_context(patch.object(native, 'make_vector_store', return_value=None))
            stack.enter_context(patch.object(native, 'make_memory_store', return_value=None))
            budget = stack.enter_context(patch('backend.inbox_monitor.resources_available', return_value=True))

            async with native.lifespan(native.app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url='http://iq.synthetic') as api:
                    self.assertEqual((await api.get('/health')).status_code, 200)
                    self.assertEqual((await api.get('/api/settings')).status_code, 401)
                    invalid = await api.post('/api/auth/login', json={'username': 'fixture', 'password': 'wrong'})
                    self.assertEqual(invalid.status_code, 401)
                    login = await api.post('/api/auth/login', json={'username': 'fixture', 'password': 'fixture'})
                    self.assertEqual(login.status_code, 200, login.text)
                    api.headers['Authorization'] = 'Bearer ' + login.json()['token']
                    self.assertIsNone(native.app.state.inbox_task)
                    update = await api.put('/api/settings', json={'automation_enabled': True,
                        'auto_apply': False, 'batch_size': 5, 'automation_pending_limit': 20,
                        'poll_interval_seconds': 60, 'schedule_cron': None,
                        'smart_entity_selection': False})
                    self.assertEqual(update.status_code, 200, update.text)
                    await wait_for_pending(5)
                    # The review cap has room for 20: it cannot mask a broken
                    # five-document run limit. Wait for the actual run to finish.
                    async with native._iq_lock(native.app, 'automation_run_lock'):
                        self.assertEqual(len(analyses), 5)
                    await api.put('/api/settings', json={'automation_pending_limit': 5})
                    await native._run_scheduler_batch(native.app)
                    self.assertEqual(len(analyses), 5)
                    async with AsyncSessionLocal() as session:
                        rows = (await session.scalars(select(SuggestionORM))).all()
                        self.assertEqual(len({row.document_id for row in rows}), 5)
                        self.assertTrue(all(row.status == 'pending' for row in rows))
                        self.assertEqual(await session.scalar(select(func.count()).select_from(DocumentTrackingORM).where(DocumentTrackingORM.last_analyzed_at.is_not(None))), 5)
                    old_task = native.app.state.inbox_task
                    result = await api.put('/api/settings', json={'poll_interval_seconds': 1})
                    self.assertEqual(result.status_code, 200)
                    self.assertIs(native.app.state.inbox_task, old_task)
                    result = await api.put('/api/settings', json={'automation_enabled': False,
                        'poll_interval_seconds': 60})
                    self.assertEqual(result.status_code, 200)
                    await asyncio.sleep(0)
                    self.assertTrue(old_task.done())
                    self.assertIsNone(native.app.state.inbox_task)
                    # Resource pressure defers the actual poller before inference.
                    budget.return_value = False
                    before = len(provider_attempts)
                    before_poll = len(polls)
                    before_budget = budget.call_count
                    result = await api.put('/api/settings', json={'automation_enabled': True,
                        'automation_pending_limit': 10})
                    self.assertEqual(result.status_code, 200)
                    await wait_for_poll_after(before_poll)
                    self.assertGreater(budget.call_count, before_budget)
                    self.assertEqual(len(provider_attempts), before)
                    await api.put('/api/settings', json={'automation_enabled': False})
                    await asyncio.sleep(0)
                    budget.return_value = True

                    # Real native provider/queue failures get bounded accounting.
                    provider_fails = True
                    await api.put('/api/settings', json={'automation_enabled': True})
                    async with asyncio.timeout(10):
                        while True:
                            async with AsyncSessionLocal() as session:
                                failed = await session.scalar(select(func.count()).select_from(AuditLogORM).where(
                                    AuditLogORM.action_type == 'analysis_failed'))
                            if failed == 3:
                                break
                            await asyncio.sleep(0.01)
                    await native._run_scheduler_batch(native.app)
                    self.assertEqual(len(provider_attempts) - before, 3)
                    self.assertEqual(await pending(), 5)
                    await api.put('/api/settings', json={'automation_enabled': False})
                    await asyncio.sleep(0)
                    provider_fails = False
                    # Advance only the synthetic audit clock, never production.
                    async with AsyncSessionLocal() as session:
                        await session.execute(sa_update(AuditLogORM).where(AuditLogORM.action_type == 'analysis_failed').values(
                            changed_at=datetime.now(UTC) - timedelta(minutes=16)))
                        await session.commit()
                    await api.put('/api/settings', json={'automation_enabled': True})
                    await wait_for_pending(10)
                    self.assertEqual(len(analyses), 10)
                    await api.put('/api/settings', json={'automation_enabled': False})
                    await asyncio.sleep(0)
                    persisted = SettingsService()
                    await persisted.load_from_db()
                    self.assertFalse(persisted.config.automation_enabled)
                    self.assertFalse(persisted.config.auto_apply)
                    self.assertEqual(persisted.config.batch_size, 5)
                    self.assertEqual(persisted.config.automation_pending_limit, 10)
                    # An independent native settings writer persists state but
                    # cannot update the running application's cached config/task.
                    await persisted.update_and_persist({'automation_enabled': True})
                    self.assertFalse(native._settings_svc.config.automation_enabled)
                    self.assertIsNone(native.app.state.inbox_task)
                    auth_header = api.headers['Authorization']

            # Restart real lifespan, retaining only isolated persisted state/key.
            native._settings_svc = SettingsService()
            before_restart_poll = len(polls)
            async with native.lifespan(native.app):
                self.assertTrue(native._settings_svc.config.automation_enabled)
                self.assertIsNotNone(native.app.state.inbox_task)
                await wait_for_poll_after(before_restart_poll)
                self.assertEqual(await pending(), 10)
                self.assertEqual(len(analyses), 10)
                self.assertFalse(native._settings_svc.config.auto_apply)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app),
                        base_url='http://iq.synthetic', headers={'Authorization': auth_header}) as api:
                    result = await api.put('/api/settings', json={'automation_enabled': False})
                    self.assertEqual(result.status_code, 200)

            self.assertEqual(metadata_writes, [])
            await engine.dispose()
            await asyncio.sleep(0)
            active = [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
            self.assertEqual(active, [], 'isolated background tasks leaked')
        print('IQ_APPLICATION_STARTUP_AUTH_POLL_5_RELOAD_RESTART=PASS')
        print('IQ_APPLICATION_RESOURCE_DEFER_FAILURE_BACKOFF_RECOVERY=PASS')
        print('IQ_SYNTHETIC_PAPERLESS_METADATA_WRITES=0')
        print('IQ_TEST_BACKGROUND_TASKS=0')


if __name__ == '__main__':
    unittest.main(verbosity=2)
