# Personal Assistant OTS authority map

Status: canonical architecture decision, 2026-09-29.

## Principle

LifeOS coordinates mature products and adds only cross-system semantics/orchestration that those products do not own. It must not become a second email archive, document manager, calendar server, home-automation platform, password manager or infrastructure monitor.

## Current deployed authority

| Concern | Authority | LifeOS custom boundary |
|---|---|---|
| Email/messages | Gmail | Read-only obligation/progress extraction and stable message references. Do not copy mailbox content into LifeOS. |
| Documents/evidence | Paperless-ngx | Query stable document references and propose cross-system relationships. Native Paperless mail, ingestion, OCR, metadata, workflows, search and duplicate handling remain authoritative. |
| Calendar | Radicale (CalDAV) | Adapter/orchestration only; do not implement a calendar store. |
| Home automation/UI | Home Assistant | Publish derived PA status and invoke approved HA actions; do not duplicate HA state. |
| Secrets | Vaultwarden for user secrets; governed runtime credential files for service credentials | LifeOS consumes only explicitly provisioned runtime credentials. |
| Availability/monitoring | Uptime Kuma / existing observability stack | Consume health signals; do not create a parallel monitor. |
| Local semantic inference | Governor + Tower Ollama | Schema-constrained proposals only; never an authority. |
| Personal tasks/obligations | No dedicated OTS task manager currently deployed | LifeOS may retain a minimal derived task/progress index until an OTS task authority is deliberately selected. It must store references/provenance, not source email/document content. |

## Retirement / consolidation decisions

1. **Paperless native mail is the production email-to-document ingestion path.** The historical `lifeos_email_paperless_selective.py` remains acceptance/reference evidence only and must not become a continuous production importer.
2. **The PA task reconciler does not ingest documents.** It reads Gmail for obligation/progress semantics and queries Paperless for evidence already managed by Paperless.
3. **Paperless relationships remain proposals/review metadata.** LifeOS may infer cross-system or cross-document candidates, but Paperless remains document authority.
4. **Radicale remains calendar authority.** `lifeos_calendar_adapter.py` is a bounded client/adapter, not a calendar implementation.
5. **Home Assistant remains presentation/automation authority.** PA JSON is a derived read model, not a new UI database.
6. **Do not add a new task product merely to remove a small amount of glue.** Revisit Vikunja/Nextcloud Tasks/other OTS only if the derived LifeOS task index grows into task-management features such as manual projects, assignments, recurrence, comments, collaboration or rich task editing.

## Custom code that remains justified

- local-only semantic extraction of obligations/progress from Gmail;
- correlation of Gmail obligations with Paperless evidence and calendar events;
- bounded cross-document/cross-system relationship proposals;
- Governor privacy/routing and Tower lifecycle orchestration;
- thin HA read-model/adapters.

## PA task review window

The task review window is a user-invoked view over existing Gmail and Paperless authorities. It shows bounded Paperless OCR text in a scrollable review panel (with a direct Paperless link to the original), followed by a local AI analysis, suggested next actions, and an optional response draft. The draft is advisory and is never sent automatically.

When the user opens a review, the reconciler fetches a bounded set of source messages and linked Paperless OCR, passes the evidence only through Governor's `privacy="local-only"`, forced Ollama route, and verifies the returned provider. The review queue and generated result use private per-owner state directories. Raw OCR is held in a private, owner-only preview cache for at most one hour and is served only through an authenticated Home Assistant endpoint while the review window is open; the UI deletes it when the window closes. Raw email and OCR are not added to task or dashboard state, recorder history, or logs. Only the bounded generated analysis is projected to the task card.

If the review feature must be rolled back, remove the Review control and result projection, stop accepting review queue files, and remove only the `review-requests`, `task-reviews`, and `task-previews` runtime directories and the preview API integration after preserving any required audit evidence. Gmail and Paperless remain authoritative and are not changed by analysis.

Everything else should preferentially use the OTS owner above.
