#!/usr/bin/env python3
"""Read-only Pi-local event-status audit. Emit aggregate enums/counts only."""
import json
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


def main():
    path=Path('/home/joshan/automation/state/lifeos_personal_tasks.json')
    try:
        payload=validate_payload(json.loads(path.read_text()))
        counts=event_counts(payload)
    except Exception:
        print('PA_EVENT_AUDIT=UNAVAILABLE')
        return 1
    for key,value in counts.items():print('PA_EVENT_'+key+'='+str(value))
    print('PA_EVENT_VIEW_FRESH=PASS')
    print('PA_EVENT_AUDIT=PASS')
    return 0


if __name__=='__main__':raise SystemExit(main())
