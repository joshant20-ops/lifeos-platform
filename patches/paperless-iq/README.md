# Native IQ automation repair

Target: Paperless IQ 1.2.0, upstream revision
`9739f470ca04fb7e4c219e0541fe27e811484ebf`. Upstream terms are retained in
[LICENSE.upstream](LICENSE.upstream). This is a native application patch, not a
replacement scheduler or a new LifeOS runtime dependency.

Status: tested source candidate; live automatic classification is not accepted
until the guarded deployment and real pending-suggestion checks pass.

The 19 November read-only Pi audit (run 44481278999) matched all four inspected
source hashes. Paperless and local Ollama were healthy. All 2,654 tracked records
had no analysis timestamp; ten pending suggestions covered five documents.
The existing poller skips tracked rows, the cron field is empty, and direct SQL
settings changes do not reload the running application. Upstream batch size
partitions the whole backlog rather than limiting a run.

`governor/paperless_iq_patch.py` rejects unknown source preimages before generating
six modified native files. The native poller and cron share one bounded run
policy. Embedding-only tracking stays eligible; pending and previously analysed
documents are excluded. Runs are capped by batch size and a review-queue ceiling
of at most 20 pending rows. Newest IDs take priority. Existing suggestions and
embedding fields are preserved.

The final pending check and insert hold the SQLite writer reservation, protecting
automatic deduplication and queue capacity against other producers. Automatic
and common manual analysis paths share an application lock. Failed analysis or
failed persistence never receives a success timestamp. Existing IQ audit rows
provide three-attempt daily document budgets and a three-failure/15-minute global
backoff. No additional table, database or scheduler is introduced.

Automatic work defers at host load 3, available memory below 2 GiB, temperature 75 C,
or data-volume byte/inode reserve failure. These are safety thresholds, not a
measurement of application quality. Unknown resource evidence also defers work.

Structured Ollama requests use temperature 0 and seed 42. This reduces sampling
variation; it does not guarantee identical outputs or factual accuracy. Preserve
human review and `auto_apply=false`. No automatic Paperless metadata writes are
authorised by this patch.

Focused tests use the real pinned IQ ORM and queue service with isolated SQLite
databases. They cover tracked-document eligibility, finite runs, pending and
rejected-document exclusion, backpressure, failure/recovery, concurrent producers,
and structured sampling options. Runtime tests must repeat these contracts in
the exact derived image without production mounts or network.

Deployment must back up and verify configuration/database/key material, identify
the existing Compose service, quiesce only IQ, and preserve unrelated decoded
settings. A governed native `SettingsService` maintenance integration can persist
validated settings without a browser password; it is an internal Python API,
not a documented upstream admin CLI. Recreate only IQ through existing Compose,
retain rollback, and verify an automatic five-document canary before promotion.
Do not enable an unrestricted cron, reset tracking, reindex, apply suggestions,
modify intake, or restart AdGuard/HA/Predbat.

Stage 1 deliberately does not deploy, update live settings, start background work
or grant a new privileged operation. See [DEPLOYMENT.md](DEPLOYMENT.md) for the
ordered deployment, acceptance and rollback procedure and outstanding preflights.

Stage 1 verification: 31 local tests passed (the existing 18 plus 13 targeted
regressions). Independent source review regenerated and examined all six output
files and independently passed the same suite. Regressions cover 2,654 candidate
IDs with a five-document run cap, the 20-pending ceiling, competing writers,
legacy human decisions without tracking timestamps, actual generated callback
locks, queued resource/configuration changes, persistence failure, cooperative
inference timeout and SQLite transaction release. Automatic callbacks never call
approval/application; an unexpected `auto_apply=True` stops automatic inference.
Hosted CI and live/full-image acceptance are separate evidence.

Stage 2A: the additional full-native-ASGI synthetic rehearsal passed; fresh Pi
read-only resource/dependency checks passed. Production pilot remains NO-GO
pending exact-image and deployment/capacity gates. See [STAGE2A.md](STAGE2A.md).
