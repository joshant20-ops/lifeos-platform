#!/usr/bin/env python3
"""Read-only Pi-local event-status audit. Emit aggregate enums/counts only."""
import json
import re
from email.utils import parseaddr, parsedate_to_datetime
from datetime import date
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from governor.pa_source_disposition import task_quality_category


def validate_payload(payload,now=None):
    now=time.time() if now is None else now
    if not isinstance(payload,dict) or payload.get('schema')!='lifeos_tasks_v3':raise ValueError('invalid_projection')
    generated=payload.get('generated_time')
    if isinstance(generated,bool) or not isinstance(generated,(int,float)) or not 0<=now-generated<=7*3600:raise ValueError('projection_not_fresh')
    if not all(isinstance(payload.get(bucket),list) for bucket in ('tasks','resolved','informational')):raise ValueError('invalid_projection_buckets')
    return payload


def event_counts(payload,today=None):
    today=today or date.today()
    counts={key:0 for key in ('CANDIDATES','REVIEW_QUESTIONS','PAST_EVENT_QUESTIONS','SOURCE_REVIEW_QUESTIONS','PAST_EVENT_RESPONSE_WARNINGS','UNVERIFIED_PAST_ACTIONS','RESPONSE_GUARDED_PAST_ACTIONS','SCHEDULED_SOURCE_DATE_MATCHED_ACTIONS','SCHEDULED_SOURCE_DATE_MISMATCH_ACTIONS','ACTION_DEADLINE_SOURCE_ACTIONS','NOTICE_VERIFIED_PAST_ACTIONS')}
    for bucket in ('tasks','resolved','informational'):
        for row in payload.get(bucket) or []:
            if not isinstance(row,dict) or row.get('status') not in {'OPEN','WAITING'} or row.get('obligation_suppressed') or task_quality_category(row)!='scheduled_event':
                continue
            counts['CANDIDATES']+=1
            flag=row.get('confirmation_required')
            if flag:
                counts['REVIEW_QUESTIONS']+=1
                if flag=='past_event_status':counts['PAST_EVENT_QUESTIONS']+=1
                if flag=='source_unavailable':counts['SOURCE_REVIEW_QUESTIONS']+=1
                if flag=='past_event_status' and row.get('source_response_required'):counts['PAST_EVENT_RESPONSE_WARNINGS']+=1
                continue
            try:past=date.fromisoformat(str(row.get('due_date')))<today
            except (TypeError,ValueError):past=False
            if not past or row.get('due_date_source') in {'user','paperless_policy'} or row.get('user_tracking') or row.get('status_source')=='user':continue
            counts['UNVERIFIED_PAST_ACTIONS']+=1
            checks=row.get('source_disposition_checks') or {}
            if (checks.get('reason_counts') or {}).get('mandatory_request'):counts['RESPONSE_GUARDED_PAST_ACTIONS']+=1
            if checks.get('event_schedules',0)==checks.get('sources',0) and checks.get('sources',0)>0:
                if checks.get('event_date_matches',0)==checks.get('sources',0):counts['SCHEDULED_SOURCE_DATE_MATCHED_ACTIONS']+=1
                else:counts['SCHEDULED_SOURCE_DATE_MISMATCH_ACTIONS']+=1
            if checks.get('event_action_deadlines',0)>0:counts['ACTION_DEADLINE_SOURCE_ACTIONS']+=1
            if checks.get('sources',0)>0 and checks.get('event_notices')==checks.get('sources'):counts['NOTICE_VERIFIED_PAST_ACTIONS']+=1
    return counts


def outcome_counts(payload, brand):
    """Read-only evidence shape audit; return counts, never source values."""
    rows = [row for bucket in ('tasks', 'resolved', 'informational') for row in payload.get(bucket, []) if isinstance(row, dict)]
    def ids(row):
        return set(row.get('source_message_ids') or []) | ({row['email_message_id']} if row.get('email_message_id') else set())
    def text(row):
        context = row.get('source_context') or {}
        return ' '.join(str(row.get(k) or '') for k in ('title', 'topic', 'counterparty')) + ' ' + str((row.get('user_project') or {}).get('outcome') or '') + (' ' + str(context.get('sender') or '') + ' ' + str(context.get('subject') or '') if context.get('message_id') in ids(row) else '')
    # Locator only, never membership evidence: tolerate doubled letters and
    # punctuation in an owner-supplied search label.
    def locator(value):
        return re.sub(r'(.)\1+', r'\1', re.sub(r'[^a-z0-9]', '', value.casefold()))
    selected = [row for row in rows if locator(brand) in locator(text(row))]
    counts = {key: 0 for key in ('ROWS', 'OPEN', 'WAITING', 'DONE', 'SHARED_SOURCE_PAIRS', 'SAME_ORDER_PAIRS', 'OVERLAPPING_CASE_PAIRS', 'SAME_SENDER_DOMAIN_PAIRS', 'SAME_TOPIC_PAIRS', 'MISSING_ORDER_REFS', 'ORDER_SUBSET_PAIRS')}
    counts['ROWS'] = len(selected)
    for row in selected:
        status = str(row.get('status') or '').upper()
        if status in counts: counts[status] += 1
        if not row.get('verified_order_refs'): counts['MISSING_ORDER_REFS'] += 1
    for i, left in enumerate(selected):
        for right in selected[i+1:]:
            a, b = set(left.get('verified_order_refs') or []), set(right.get('verified_order_refs') or [])
            if ids(left) & ids(right): counts['SHARED_SOURCE_PAIRS'] += 1
            if a and a == b: counts['SAME_ORDER_PAIRS'] += 1
            if a and b and (a < b or b < a): counts['ORDER_SUBSET_PAIRS'] += 1
            if set(left.get('case_reference_ids') or []) & set(right.get('case_reference_ids') or []): counts['OVERLAPPING_CASE_PAIRS'] += 1
            def domain(row):
                context = row.get('source_context') or {}
                return parseaddr(context.get('sender') or '')[1].lower().rpartition('@')[2] if context.get('message_id') in ids(row) else ''
            if domain(left) and domain(left) == domain(right): counts['SAME_SENDER_DOMAIN_PAIRS'] += 1
            if left.get('topic') and left.get('topic') == right.get('topic'): counts['SAME_TOPIC_PAIRS'] += 1
    patterns = {
        'IDENTITY': r'identity.{0,35}(?:verified|complete[ds]?|successful)|(?:verified|completed).{0,25}(?:identity|id check)',
        'SIGNING': r'(?:agreement|contract|documents?).{0,35}(?:signed|executed)|(?:signed|executed).{0,35}(?:agreement|contract|documents?)',
        'APPROVAL': r'(?:finance|application|credit).{0,60}approved|approved.{0,25}(?:finance|application)',
        'PAYMENT': r'(?:payment|deposit).{0,25}(?:received|successful|complete[ds]?)',
        'DELIVERY': r'(?:order|parcel|vehicle).{0,35}(?:delivered|collected)|delivery.{0,15}completed',
    }
    for stage, pattern in patterns.items():
        counts[stage + '_SOURCE_EVENTS'] = 0
        counts[stage + '_LATER_CANDIDATES'] = 0
        evidence = []
        for row in selected:
            context = row.get('source_context') or {}
            history = [event for event in row.get('timeline_events') or [] if isinstance(event, dict) and event.get('message_id') in ids(row)]
            if context.get('message_id') in ids(row):
                history.append({'title': context.get('subject'), 'date': context.get('sent_at'), 'message_id': context.get('message_id')})
            seen = set()
            for event in history:
                if event.get('message_id') in seen or not re.search(pattern, str(event.get('title') or ''), re.I): continue
                seen.add(event['message_id'])
                counts[stage + '_SOURCE_EVENTS'] += 1
                try:
                    date_value = parsedate_to_datetime(str(event.get('date') or ''))
                    timestamp = date_value.timestamp() if date_value.tzinfo else 0
                except (ValueError, TypeError, OverflowError): timestamp = 0
                evidence.append((row, timestamp))
        target = {'IDENTITY':r'identity|id check', 'SIGNING':r'sign|agreement', 'APPROVAL':r'finance|approval', 'PAYMENT':r'pay|deposit', 'DELIVERY':r'deliver|collect'}[stage]
        for row in selected:
            if row.get('status') not in {'OPEN', 'WAITING'} or not re.search(target, str(row.get('title') or '') + ' ' + str(row.get('topic') or ''), re.I): continue
            try:
                date_value = parsedate_to_datetime(str(row.get('updated_from_email') or ''))
                request_time = date_value.timestamp() if date_value.tzinfo else 0
            except (ValueError, TypeError, OverflowError): request_time = 0
            if request_time and any(when > request_time for _, when in evidence): counts[stage + '_LATER_CANDIDATES'] += 1
    return counts


def main():
    path=Path('/home/joshan/automation/state/lifeos_personal_tasks.json')
    try:
        payload=validate_payload(json.loads(path.read_text()))
        counts=event_counts(payload)
        outcomes={brand: outcome_counts(payload, brand.lower()) for brand in ('HOBBIBEAR', 'TESLA')}
    except Exception:
        print('PA_EVENT_AUDIT=UNAVAILABLE')
        return 1
    for key,value in counts.items():print('PA_EVENT_'+key+'='+str(value))
    for brand, values in outcomes.items():
        for key, value in values.items(): print('PA_OUTCOME_AUDIT_' + brand + '_' + key + '=' + str(value))
    print('PA_OUTCOME_AUDIT_READ_ONLY=PASS')
    print('PA_EVENT_VIEW_FRESH=PASS')
    print('PA_EVENT_AUDIT=PASS')
    return 0


if __name__=='__main__':raise SystemExit(main())
