# IQ scheduler candidate: deployment and rollback

Stage 1 only, 19 November 2026 GMT. Nothing in this change dispatches Pi work,
changes a live database, enables automation or rebuilds a running container.
Do not interpret this runbook as deployment authorisation.

## Authority and prerequisites

GitHub source is canonical; #2122 owns classification acceptance. Production
execution must use the existing serialised Watchman/gateway boundary. No general
root shell, arbitrary gateway argument, project-wide Compose operation, Docker
restart or new scheduler is permitted. A fixed IQ-only mutation operation has
**not** been added by Stage 1; Stage 2 must identify an already-authorised operation
or separately review/install its narrow implementation before deployment.

Known baseline: IQ 1.2.0 / upstream revision
`9739f470ca04fb7e4c219e0541fe27e811484ebf`; audited local image ID
`sha256:f21a82ccaf03a71193aa8d32473332ed458c388097c5b42ffb9c1940eb534736`.
An image ID is not a registry RepoDigest. Do not substitute it for one or pull a
moving latest tag. All six source preimages must pass the builder's SHA-256 gate;
only four were inspected by the previous live audit. Drift stops deployment.

Before any mutation, privately record and validate the actual Compose project,
service, working directory, ordered Compose files/overrides, image, command,
container UID/GID, mounts, restart policy and credential-key source. Do not guess
paths from this document. The audit supports sanitised metadata, but those new
fields have not yet been collected live. Worker flags are declarations, not
process evidence; mount type and key-file permissions do not prove usability. Verify exactly one ASGI worker and one
IQ instance; process-local inference locks do not coordinate separate workers.
Do not publish raw inspect/config output, credentials or document data.

Verify Tier 0 UDP/TCP DNS, independent-IP connectivity, GitHub, SSH/recovery,
AdGuard runtime and disk/inode reserve with the existing health gate. Confirm
Home Assistant, Predbat and intake health. Acquire the shared deployment lock;
abort if another storage/recovery mutation owns it. Verify at least the ordinary
storage reserve plus the measured backup/image/staging requirement, not an
invented fixed capacity. Unknown evidence fails closed.

## Reproducible source and isolated checks

On an isolated engineering machine, using only pinned public upstream source:

```sh
python3 -m governor.paperless_iq_patch \
  --source /absolute/path/to/pinned-upstream \
  --target /absolute/path/to/new-generated-directory
IQ_UPSTREAM_SOURCE=/absolute/path/to/pinned-upstream \
  python3 -m unittest discover -s tests -p 'test_paperless_iq_*.py' -v
```

The target must not exist. The builder emits the six postimage hashes and
compiles every generated Python file. Preserve these hashes with the candidate
commit. Tests need SQLAlchemy[asyncio] 2.1.9 (including greenlet), aiosqlite 0.22.1, ollama 0.6.3,
pydantic 2.14.3 and httpx 0.28.1 in an isolated dependency environment. Hosted CI
fetches eight hash-pinned public fixture files; it never connects to the homelab.

Create an immutable derived image from the verified installed base, copying only
the six generated files to their corresponding existing backend paths. Preserve
the base entrypoint, command, dependencies, user, permissions and upstream licence.
Do not build on or mount live `/data`. Record the derived image ID and postimage
hashes. Run tests in that exact image with `IQ_NATIVE_BACKEND_ROOT` pointing at its
application root, an empty isolated SQLite database, no production mounts, no
network, and no application startup tasks. All native dependencies must import;
repeat cap/dedup/failure tests. Confirm `/health` and authentication contracts in
an isolated app rehearsal before touching production. Stage 1 tests execute
actual generated callback definitions, not a full FastAPI/image startup.

## Ordered IQ-only rollout (Stage 2, after authorisation)

1. Preserve the original recovery checkpoint unchanged. Make a new private
   SQLite online backup of the IQ configuration DB and an independent validated
   copy of the credential key (either usable `SECRET_KEY` or `/data/.secret_key`).
   Include Compose files/overrides, image identity and data/mount metadata in the
   private rollback bundle. Use owner-only access. Verify the extracted database
   with `PRAGMA integrity_check`, verify checksum/readback, and demonstrate that
   the same key decrypts credential fields without printing values. Missing or
   incompatible key is a stop, never permission to generate a replacement.
2. Prevalidate the stored JSON, model and credentials before calling native
   `SettingsService.load_from_db`: upstream can reseed malformed settings from
   environment. Test the operation first against the private restored DB. Assert
   there is one authoritative settings row and every unrelated decoded field is
   preserved. Never update raw `config_json` as the deployment shortcut.
3. Quiesce **only IQ** using the validated Compose service identity. Revalidate
   the current settings JSON, key and fresh pending count P after quiescing;
   require the expected preimage or repeat backup/rehearsal for changed state. The governed
   operation must bind its Compose arguments to the verified files/project and
   use only `stop SERVICE`, then `up -d --no-deps --pull never SERVICE` after
   changing the IQ image reference. Never run `down`, `up` on the whole project,
   remove volumes, or operate on Paperless/PostgreSQL/Redis/other services.
4. While IQ is stopped, use the derived image's native `SettingsService` against
   the same validated IQ data volume/key/user, without starting FastAPI or any
   worker. Call `update_and_persist` with **only**:
   `automation_enabled=False`, `auto_apply=False`, `batch_size=2`,
   `automation_pending_limit=P+2`, `schedule_cron=None`.
   Here P is the fresh pending-row count; require P <= 18 or defer for human
   review. Initial audit P=10 is historical, not a deployment constant. Preserve
   all other settings and assert a decoded before/after comparison. This internal
   Python API is not an upstream admin CLI; it requires a separately reviewed,
   fixed maintenance operation, not a forged login token or disabled auth.
5. Point only the validated IQ service to the immutable derived image and start
   that service with the command in step 3. Verify expected image/postimage hashes,
   `/health`, authenticated settings, unchanged mounts/key, single worker,
   `automation_enabled=False`, `auto_apply=False`, cron unset and normal ingestion.
   Recreate IQ once while still disabled to prove persisted settings survive.
6. Confirm resource sensors work **inside IQ**: available RAM >= 2 GiB, load < 3,
   temperature between 0 and 75 C, data-volume free bytes >= max(10 GiB, 10%),
   free inodes >= max(50,000, 10%). Unknown values must defer work. Confirm the
   configured Paperless and Ollama routes remain local and use the existing
   inference queue/governor. Verify no concurrent recovery/storage mutation.
7. Through the authenticated native `PUT /api/settings`, or the approved native
   maintenance operation followed by an IQ-only recreation, enable **only**
   `automation_enabled=True`. Keep batch 2, queue cap P+2, auto-apply false and
   cron unset. Do not edit live SQLite behind the running cache. Settings PUT
   rewires providers; verify they remain healthy. Poll interval changes require
   disabling/re-enabling the poller or IQ recreation because its interval is
   captured at task creation; do not assume the saved value changed the task.
8. Wait for an automatic poll: require two previously eligible documents to gain
   pending suggestions and successful analysis timestamps, with no duplicate
   pending rows, no metadata PATCH/application, no loss of embeddings and no
   intake interruption. Do not manually trigger analysis as proof of automation.
   During this canary, require no approvals, rejections or other suggestion
   dispositions by users or other producers; otherwise abort the canary and
   disable automation. P+2 caps current pending rows, not lifetime analyses.
   With that precondition, the cap stops subsequent automatic work. Disable
   automation through authenticated native settings after the two successes;
   require terminal disabled-state verification before ending the observation. Preserve all ten
   original suggestions. Check resource/queue deferral logs and the three-failure
   global/per-document retry budgets; use isolated provider-failure injection,
   never disrupt the live Ollama service to test recovery.
9. Record aggregate counts, image/commit/hash evidence, restart persistence,
   intake/protected-service checks, elapsed time and failure/recovery evidence in
   #2122. Raw suggestions, OCR, prompts and logs stay local. Do not enlarge the
   queue, batch, cron or historical processing scope automatically. Stage 1
   acceptance is not classification accuracy or production sign-off.

Automatic inference uses the configured timeout clamped to 1–300 seconds; unset
or zero uses 120 seconds. Timeout creates a retryable failure, not success.
Client cancellation does not prove that Ollama stopped remote computation;
verify local queue/provider behaviour in Stage 2. Resource gates precede each
inference, including after queue waits; they cannot preempt an already running
model call or guarantee household service availability under unrelated load.

## Rollback triggers and exact order

Trigger rollback for source/image drift, credential failures, unavailable health,
unexpected auto-apply/metadata writes, duplicate automatic pending entries,
queue-cap violation, unsafe resources, or intake/protected-service regression.

1. Disable automation through authenticated settings if healthy. Then, whether
   disabling succeeded or failed, stop **only IQ** with the same validated
   Compose identity before any offline update or image switch. Preserve a fresh private
   online backup of post-change IQ state and the last report. Do not delete new
   suggestions, reset tracking, restore an old whole DB, or touch documents.
2. Restore the saved IQ image reference and IQ Compose changes only. Keep the
   current IQ database and embeddings; this patch adds no tables or schema
   migration. Using the native old-image SettingsService while IQ is stopped,
   persist `automation_enabled=False`, `auto_apply=False`, `schedule_cron=None`
   and the saved pre-change batch size. The old model ignores the new pending
   limit field; verify that behaviour on the restored copy before rollout.
   Compare unrelated decoded settings and preserve all new suggestion/audit rows.
3. Start only IQ with `up -d --no-deps --pull never SERVICE` using the saved
   immutable original image. Verify disabled automation, auth, document/index
   access, native health, intake and all protected-service checks. Do **not**
   restore the previously stored true automation flag: old scheduler behaviour
   is unsafe. Rollback ends with classification disabled and evidence preserved.
4. If the current DB/key is corrupt or rollback settings cannot be validated,
   keep IQ stopped and request owner intervention. Restoring the pre-change DB
   would discard post-checkpoint IQ state and needs separate explicit approval.
   Preserve both copies and the original recovery archive.

## Remaining acceptance gaps

Exact-image/full-app tests, actual Compose/key/worker/resource preflights,
gateway mutation coverage, hosted CI result and production canary are not proven
by local tests. Model seed/temperature reduce sampling variance but do not prove
repeatability or tagging accuracy. Newest-first scheduling may defer old records;
a separate measured backlog/classification-quality task owns that policy.
