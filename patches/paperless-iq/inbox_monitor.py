"""Bounded native IQ automation; upstream PolyForm Noncommercial licence applies."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from backend.orm_models import AuditLogORM, DocumentTrackingORM, SuggestionORM

logger = logging.getLogger(__name__)


def resources_available() -> bool:
    """Read-only Pi budget; never control another service."""
    try:
        memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        available = int(memory['MemAvailable'].split()[0]) * 1024
        temperature = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())
        disk = os.statvfs('/data')
        return (os.getloadavg()[0] < 3 and available >= 2 * 1024**3
                and 0 < temperature < 75000
                and disk.f_bavail * disk.f_frsize >= max(10 * 1024**3, disk.f_blocks * disk.f_frsize // 10)
                and disk.f_favail >= max(50000, disk.f_files // 10))
    except (OSError, ValueError, KeyError, IndexError):
        return False


class Scheduler:
    """One finite run, serialized by the existing application's run lock."""
    def __init__(self, session, fetch_inbox_docs, submit_for_analysis,
                 batch_size=10, pending_limit=20, resource_check=None):
        self._session = session
        self._fetch_inbox_docs = fetch_inbox_docs
        self._submit = submit_for_analysis
        self._batch_size = max(1, int(batch_size))
        self._pending_limit = max(1, min(20, int(pending_limit)))
        self._resource_check = resource_check or resources_available

    async def _pending(self):
        return int(await self._session.scalar(select(func.count()).select_from(SuggestionORM).where(
            SuggestionORM.status == 'pending')) or 0)

    async def _recent_failures(self, since, document_id=None):
        statement = select(func.count()).select_from(AuditLogORM).where(
            AuditLogORM.action_type == 'analysis_failed', AuditLogORM.change_source == 'automation',
            AuditLogORM.changed_at >= since)
        if document_id is not None:
            statement = statement.where(AuditLogORM.document_id == document_id)
        return int(await self._session.scalar(statement) or 0)

    async def run_batch(self):
        now = datetime.now(UTC)
        pending = await self._pending()
        if pending >= self._pending_limit:
            logger.info('AUTOMATION_DEFERRED=REVIEW_QUEUE_FULL pending=%d limit=%d', pending, self._pending_limit)
            return []
        if not self._resource_check():
            logger.info('AUTOMATION_DEFERRED=RESOURCE_BUDGET')
            return []
        if await self._recent_failures(now - timedelta(minutes=15)) >= 3:
            logger.warning('AUTOMATION_DEFERRED=FAILURE_BACKOFF')
            return []
        identifiers = sorted(set(await self._fetch_inbox_docs()), reverse=True)
        tracked = {}
        for offset in range(0, len(identifiers), 500):
            rows = await self._session.scalars(select(DocumentTrackingORM).where(
                DocumentTrackingORM.document_id.in_(identifiers[offset:offset + 500])).execution_options(populate_existing=True))
            tracked.update({row.document_id: row for row in rows.all()})
        excluded_ids = set((await self._session.scalars(select(SuggestionORM.document_id).where(
            SuggestionORM.status.in_(['pending', 'approved', 'rejected'])))).all())
        eligible = [identifier for identifier in identifiers if identifier not in excluded_ids
                    and (identifier not in tracked or tracked[identifier].last_analyzed_at is None)]
        completed, attempted = [], 0
        limit = min(self._batch_size, self._pending_limit - pending)
        for identifier in eligible:
            if attempted >= limit or await self._pending() >= self._pending_limit:
                break
            if not self._resource_check() or await self._recent_failures(datetime.now(UTC) - timedelta(minutes=15)) >= 3:
                break
            if await self._recent_failures(datetime.now(UTC) - timedelta(hours=24), identifier) >= 3:
                continue
            attempted += 1
            try:
                result = await self._submit(identifier)
                if result is None:
                    continue
                persisted = await self._session.scalar(select(SuggestionORM.id).where(
                    SuggestionORM.document_id == identifier, SuggestionORM.status == 'pending').limit(1))
                if persisted is None:
                    raise RuntimeError('suggestion_not_persisted')
                stamp = datetime.now(UTC)
                await self._session.execute(insert(DocumentTrackingORM).values(
                    document_id=identifier, first_seen_at=now, last_analyzed_at=stamp
                ).on_conflict_do_update(index_elements=['document_id'],
                    set_={'last_analyzed_at': stamp}))
                self._session.add(AuditLogORM(document_id=identifier, field_name='analysis',
                    action_type='analysis_triggered', change_source='automation',
                    new_value='pending suggestion persisted'))
                await self._session.commit()
                completed.append(identifier)
            except Exception:
                await self._session.rollback()
                self._session.add(AuditLogORM(document_id=identifier, field_name='analysis',
                    action_type='analysis_failed', change_source='automation',
                    new_value='automatic analysis failed; bounded retry applies'))
                await self._session.commit()
                logger.exception('AUTOMATION_ANALYSIS_FAILED document=%d', identifier)
        logger.info('AUTOMATION_RUN attempted=%d pending_created=%d limit=%d', attempted, len(completed), limit)
        return [completed] if completed else []


class InboxMonitor(Scheduler):
    """Embedding tracking is not successful metadata analysis."""
    async def poll(self):
        return [identifier for batch in await self.run_batch() for identifier in batch]

    async def mark_analyzed(self, document_id):
        row = await self._session.get(DocumentTrackingORM, document_id)
        if row:
            row.last_analyzed_at = datetime.now(UTC)
            await self._session.commit()


async def begin_automatic_enqueue(session, document_id, pending_limit):
    """Reserve the SQLite writer while checking cap/dedup and inserting pending.

    The automatic caller has only read from this session. Its enqueue method
    must commit or roll back before returning, as the native service already does.
    """
    from sqlalchemy import text
    await session.rollback()
    await session.execute(text('BEGIN IMMEDIATE'))
    count = int(await session.scalar(select(func.count()).select_from(SuggestionORM).where(
        SuggestionORM.status == 'pending')) or 0)
    existing = await session.scalar(select(SuggestionORM.id).where(
        SuggestionORM.document_id == document_id,
        SuggestionORM.status.in_(['pending', 'approved', 'rejected'])).limit(1))
    if count >= max(1, min(20, int(pending_limit))) or existing is not None:
        await session.rollback()
        return False
    return True
