"""Pinned native IQ repair build; no production data or execution here."""
from pathlib import Path
import hashlib
import textwrap

UPSTREAM_REVISION = '9739f470ca04fb7e4c219e0541fe27e811484ebf'
EXPECTED = {'backend/main.py': '111c011754d2d361dc016c28417ac91283c6a09f882eead54e0ba489d492ca49', 'backend/models.py': '2491ee021a303d74f08c317031be6b731330ade43f4689e61ebab1c72c5cf922', 'backend/settings_service.py': '59a1b06b681913937c4d23e0b2c33692de8bc2ae9d4686366400fc207e18ac4c', 'backend/providers/ollama_provider.py': '0b0cb2d46c887130b9c532d91ea5e6397cd2f1e35a9b816075dd54d1e78bc4c5', 'backend/approval_queue.py': '19403ec5c667d62970ed8b6853eb0dc2a2f1a44194a00aa618ad69dcc3912510', 'backend/inbox_monitor.py': '193e38a15fa761b0979ea3b2ad8c0bcc5daf30c39f5d2708606c684a57adfa07'}


def build_sources(source_dir, target_dir):
    source_dir, target_dir = Path(source_dir), Path(target_dir)
    originals = {}
    for name, expected in EXPECTED.items():
        path = source_dir / name
        if path.is_symlink() or path.stat().st_size > 2 * 1024**2:
            raise ValueError('SOURCE_REJECTED')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('SOURCE_PREIMAGE_MISMATCH')
        originals[name] = raw
    target_dir.mkdir(mode=0o700)
    for name, raw in originals.items():
        path = target_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    p=Path(target_dir) / Path('backend/main.py')
    s=p.read_text()
    a=s.index('def _make_analysis_callbacks(');b=s.index('async def _automation_loop',a)
    s=s[:a]+'''def _iq_lock(app, name):
    lock = getattr(app.state, name, None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(app.state, name, lock)
    return lock


def _make_analysis_callbacks(app: FastAPI, session: AsyncSession, label: str):
    from backend.inbox_monitor import resources_available
    config = _settings_svc.config
    paperless_client = app.state.paperless_client
    manual_svc = app.state.manual_analysis_svc

    async def fetch_inbox_docs():
        return await _fetch_all_inbox_doc_ids(paperless_client, config.inbox_tag_id)

    async def submit_for_analysis(doc_id):
        async with _iq_lock(app, 'classification_lock'):
            if not _settings_svc.config.automation_enabled or _settings_svc.config.auto_apply:
                logger.warning('AUTOMATION_DEFERRED=NOT_SUGGESTION_ONLY')
                return None
            if not resources_available():
                logger.info('AUTOMATION_DEFERRED=RESOURCE_BUDGET')
                return None
            total = int(await session.scalar(select(func.count()).select_from(SuggestionORM).where(
                SuggestionORM.status == 'pending')) or 0)
            if total >= _settings_svc.config.automation_pending_limit:
                return None
            pending = await session.scalar(select(SuggestionORM.id).where(
                SuggestionORM.document_id == doc_id,
                SuggestionORM.status.in_(['pending', 'approved', 'rejected'])).limit(1))
            if pending is not None:
                return None
            await session.rollback()
            try:
                async def guarded_analysis():
                    if (not _settings_svc.config.automation_enabled
                            or _settings_svc.config.auto_apply or not resources_available()):
                        logger.info('AUTOMATION_DEFERRED=EXECUTION_GATE')
                        return None
                    timeout = max(1, min(300, int(getattr(
                        _settings_svc.config, 'llm_timeout_seconds', 120) or 120)))
                    return await asyncio.wait_for(manual_svc.analyze(doc_id), timeout=timeout)
                queue = getattr(app.state, 'ollama_queue', None)
                if queue:
                    suggestion = await queue.submit(Priority.ANALYSIS,
                        guarded_analysis, label=f'Auto-analyzing doc {doc_id}')
                else:
                    suggestion = await guarded_analysis()
                if suggestion is None:
                    return None
                if not _settings_svc.config.automation_enabled or _settings_svc.config.auto_apply:
                    return None
                enqueued = await ApprovalQueueService(session).enqueue(suggestion,
                    automation_limit=_settings_svc.config.automation_pending_limit)
                if enqueued is None:
                    logger.info('AUTOMATION_DEFERRED=QUEUE_CHANGED')
                    return None
                logger.info('%s enqueued suggestion for doc %d.', label, doc_id)
                return enqueued
            except Exception:
                logger.exception('%s analysis failed for doc %d', label, doc_id)
                raise

    return fetch_inbox_docs, submit_for_analysis


''' +s[b:]
    # Serialize automatic selection/run as well as each per-document classification.
    a=s.index('async def _automation_loop');start=s.index('            async with AsyncSessionLocal()',a);end=s.index('        except asyncio.CancelledError:',start)
    s=s[:start]+"            async with _iq_lock(app, 'automation_run_lock'):\n"+textwrap.indent(s[start:end],'    ')+s[end:]
    s=s.replace('monitor = InboxMonitor(session, fetch_inbox_docs, submit_for_analysis)', 'monitor = InboxMonitor(session, fetch_inbox_docs, submit_for_analysis,\n                        _settings_svc.config.batch_size, _settings_svc.config.automation_pending_limit)')
    a=s.index('async def _run_scheduler_batch');start=s.index('    async with AsyncSessionLocal()',a);end=s.index('# ── Cron-driven',start)
    s=s[:start]+"    async with _iq_lock(app, 'automation_run_lock'):\n"+textwrap.indent(s[start:end],'    ')+s[end:]
    s=s.replace('scheduler = Scheduler(session, fetch_inbox_docs, submit_for_analysis, batch_size)', 'scheduler = Scheduler(session, fetch_inbox_docs, submit_for_analysis, batch_size,\n                _settings_svc.config.automation_pending_limit)')
    for name, body in [('manual_analyze','AnalyzeBody'), ('vision_analyze','VisionAnalyzeBody')]:
        header=f'async def {name}(body: {body}, request: Request) -> dict:\n'
        if s.count(header) != 1:
            raise ValueError('SOURCE_FUNCTION_LAYOUT_MISMATCH')
        s=s.replace(header, header+"    async with _iq_lock(request.app, 'classification_lock'):\n"+f'        return await _{name}_locked(body, request)\n\n\nasync def _{name}_locked(body: {body}, request: Request) -> dict:\n')
    # A manual enqueue failure is not a successful persisted result either.
    s=s.replace('        logger.warning("Failed to auto-enqueue suggestion for doc %d", body.document_id, exc_info=True)', '        logger.warning("Failed to auto-enqueue suggestion for doc %d", body.document_id, exc_info=True)\n        raise HTTPException(status_code=503, detail="Suggestion persistence failed; no completed analysis recorded.")')
    p.write_text(s)
    p=Path(target_dir) / Path('backend/models.py');s=p.read_text().replace('    batch_size: int = 10\n', '    batch_size: int = 10\n    automation_pending_limit: int = 20\n')
    anchor='    @field_validator("batch_size")'
    s=s.replace(anchor, '''    @field_validator("automation_pending_limit")
    @classmethod
    def validate_automation_pending_limit(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("automation_pending_limit must be between 1 and 20")
        return value

'''+anchor)
    p.write_text(s)
    p=Path(target_dir) / Path('backend/settings_service.py');s=p.read_text().replace('    "batch_size":', '    "automation_pending_limit":      ("PIQ_AUTOMATION_PENDING_LIMIT", int),\n    "batch_size":');p.write_text(s)
    p=Path(target_dir) / Path('backend/providers/ollama_provider.py');s=p.read_text().replace('        if output_schema:\n            kwargs["format"]', '        if output_schema:\n            kwargs["options"].update({"temperature": 0.0, "seed": 42})\n            kwargs["format"]');p.write_text(s)

    p=Path(target_dir) / Path('backend/approval_queue.py');s=p.read_text()
    s=s.replace('    async def enqueue(self, suggestion: MetadataSuggestion) -> MetadataSuggestion:', '''    async def enqueue(self, suggestion: MetadataSuggestion, *, automation_limit: int | None = None) -> MetadataSuggestion | None:
        if automation_limit is None:
            return await self._enqueue_native(suggestion)
        from backend.inbox_monitor import begin_automatic_enqueue
        try:
            if not await begin_automatic_enqueue(self._session, suggestion.document_id, automation_limit):
                return None
            return await self._enqueue_native(suggestion)
        finally:
            # Also releases the writer reservation on UUID-idempotent returns,
            # exceptions and cancellation. Native enqueue commits insertion.
            await self._session.rollback()

    async def _enqueue_native(self, suggestion: MetadataSuggestion) -> MetadataSuggestion:''')
    p.write_text(s)

    policy = Path(__file__).resolve().parents[1] / 'patches/paperless-iq/inbox_monitor.py'
    (target_dir / 'backend/inbox_monitor.py').write_bytes(policy.read_bytes())
    result = {}
    for name in EXPECTED:
        path = target_dir / name
        compile(path.read_text(), name, 'exec')
        path.chmod(0o644)
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    print(json.dumps(build_sources(args.source, args.target), sort_keys=True))
