"""Fixed in-container aggregate inventory; called only by the governed audit.

No document identifiers, taxonomy labels, paths, endpoint URLs or OCR are emitted.
All database queries run in a read-only PostgreSQL transaction with timeouts.
"""
import json
import re
import signal


def inspect():
    from django.apps import apps
    from django.conf import settings
    from django.db import connection, transaction
    from django.utils import timezone
    from datetime import timedelta
    from documents.models import Document
    from paperless.version import __full_version_str__

    def stop(*_):
        raise TimeoutError()
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(25)
    out = {}
    version = str(__full_version_str__)
    out['VERSION'] = version if re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', version) else 'UNKNOWN'
    if connection.vendor != 'postgresql':
        return {'RESULT': 'DATABASE_UNSUPPORTED'}
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute("SET LOCAL statement_timeout = '3000ms'")
            cursor.execute("SET LOCAL lock_timeout = '1000ms'")
        docs = Document.objects.filter(root_document__isnull=True)
        out['DOCUMENTS'] = docs.count()
        out['MISSING_CORRESPONDENT'] = docs.filter(correspondent__isnull=True).count()
        out['MISSING_TYPE'] = docs.filter(document_type__isnull=True).count()
        out['UNTAGGED'] = docs.filter(tags__isnull=True).distinct().count()
        out['EMPTY_OCR'] = docs.filter(content='').count()
        out['ADDED_LAST_30_DAYS'] = docs.filter(added__gte=timezone.now()-timedelta(days=30)).count()
        for name in ('ProcessedMail', 'PaperlessTask', 'Workflow', 'MailRule', 'SavedView'):
            models = [m for m in apps.get_models() if m.__name__ == name]
            out[name.upper() + '_COUNT'] = models[0].objects.count() if len(models) == 1 else 'UNKNOWN'
        for name in ('Workflow', 'MailRule'):
            models = [m for m in apps.get_models() if m.__name__ == name]
            if len(models) == 1 and 'enabled' in {f.name for f in models[0]._meta.fields}:
                out[name.upper() + '_ENABLED'] = models[0].objects.filter(enabled=True).count()
            else:
                out[name.upper() + '_ENABLED'] = 'UNKNOWN'
        Task = apps.get_model('documents', 'PaperlessTask')
        out['TASKS_FAILED_UNACKNOWLEDGED'] = Task.objects.filter(status='failure', acknowledged=False).count()
        out['TASKS_PENDING'] = Task.objects.filter(status='pending').count()
        out['TASKS_STARTED'] = Task.objects.filter(status='started').count()
        Mail = apps.get_model('paperless_mail', 'ProcessedMail')
        out['MAIL_SUCCESS_LAST_30_DAYS'] = Mail.objects.filter(status='SUCCESS', processed__gte=timezone.now()-timedelta(days=30)).count()
        out['MAIL_FAILED_COUNT'] = Mail.objects.filter(status='FAILED').count()
        for name, setting in (('TASK_WORKERS', 'TASK_WORKERS'), ('THREADS_PER_WORKER', 'THREADS_PER_WORKER'), ('CONSUMER_POLLING', 'CONSUMER_POLLING_INTERVAL')):
            value = getattr(settings, setting, None)
            if isinstance(value, str) and re.fullmatch(r'[0-9]{1,5}', value):
                value = int(value)
            if type(value) is float and value.is_integer():
                value = int(value)
            out[name] = value if type(value) is int and 0 <= value <= 10000 else 'UNKNOWN'
        for name in ('AUDIT_LOG_ENABLED', 'TIKA_ENABLED', 'CONSUMER_DELETE_DUPLICATES'):
            value = getattr(settings, name, None)
            out[name] = str(value).upper() if type(value) is bool else 'UNKNOWN'
    out['RESULT'] = 'READ_ONLY_COMPLETE'
    return out


try:
    result = inspect()
except Exception:
    result = {'RESULT': 'UNAVAILABLE'}
finally:
    signal.alarm(0)
print('PAPERLESS_NATIVE_JSON=' + json.dumps(result, sort_keys=True))
