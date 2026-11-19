# Paperless IQ Stage 2A evidence — 19 November 2026 GMT

**Decision: NO-GO for a Stage 2B production pilot. No deployment performed.**
Candidate scheduler/builder code remains unchanged from reviewed Stage 1 commit
`f2fc9a0d3007bb39ea4ee2cd7496cc28467ce1f6`. Work is preserved on
`fix/paperless-iq-bounded-classification-stage1`, draft PR #2144; #2122 remains
classification acceptance owner. This is a stage checkpoint, not product sign-off.

## Application compatibility

Fresh [Pi read-only preflight](https://github.com/joshant20-ops/lifeos-platform/actions/runs/44606910916)
at 20:16 GMT verified IQ **1.2.0**, unchanged local image ID
`sha256:f21a82ccaf03a71193aa8d32473332ed458c388097c5b42ffb9c1940eb534736`,
and upstream revision `9739f470ca04fb7e4c219e0541fe27e811484ebf`.
The canonical audit ran from `4baebd7d954a87e8e9eb1707f80ca4e7e454baad`;
the installed gateway hash is recorded in that run. No gateway installation,
checkout update, settings mutation or service restart was used.

Four live source fingerprints (main, monitor, settings and Ollama provider)
match the Stage 1 preimages. All six candidate preimages and compilation passed
against the complete pinned public source. Its 39 fetched source/configuration
files were checked against the public Git blob identities. This establishes
pinned-source compatibility, **not complete installed-image acceptance**: live
models/approval-queue fingerprints, source overlays, dependency versions, image
RepoDigest, actual worker count and key/mount configuration remain unverified.
Public Dockerfile declares Python 3.12, `/app/backend`, `/data` and uvicorn;
these are build-source facts, not independently verified live process metadata.

## Isolated execution

- Stage 1 contracts: 31 passing tests (23 automation/build and 8 privacy/audit).
- New standalone full-native-ASGI rehearsal: 1 passing integration test,
  independently repeated. Final test failures: zero.
- Additional original-model rollback compatibility check passed: the old config
  model ignores the new pending-limit field and accepts disabled automation,
  auto-apply false, no cron and the existing provider/model fields.
- One test-harness iteration shadowed SQLAlchemy `update` with an HTTP response;
  corrected the fixture alias and reran successfully. No native scheduler defect
  was discovered. Initial protected-endpoint preflights failed on an incorrect
  HTTP 200 expectation at Predbat root; see below.

The new test imports the complete patched native application, runs its lifespan
and Alembic migrations, and exercises auth, settings API, poller, analyzer,
provider, native Ollama queue, SQLite persistence and shutdown. It uses 2,654
synthetic IDs and synthetic OCR/provider responses. Real network connects are
rejected; HTTP fixtures are in-process. Vector/memory factories return None,
so Chroma, embeddings, frontend and real model quality are **not** accepted.
The environment is an isolated Python 3.12 venv on x86_64, with dependencies
resolved from pinned upstream pyproject requirements, not the deployed ARM image.

Verified outcomes:

1. Startup/auth: health 200, protected settings 401, rejected synthetic password 401,
   accepted synthetic login and authenticated native settings update.
2. Automatic poll: exactly **five** analyses from 2,654 eligible IDs, with room
   for 20 pending rows, after waiting for the actual run to finish. Thus the queue
   ceiling cannot mask a broken batch limit. Five distinct pending proposals,
   five analysis stamps, temperature 0 / seed 42 and no Paperless metadata writes.
3. Lowering the pending ceiling to 5 prevents further inference. Resource failure
   defers an observed real poll without inference. Existing source contracts
   cover competing writers, human decisions and daily retry budgets.
4. Injected native provider outage produces exactly 3 automatic failures, then
   global backoff. Advancing only synthetic audit timestamps 16 minutes and
   restoring the fixture provider permits the next five-document run.
5. Native PUT false cancels the poller. Independent SettingsService persistence
   does not change the running cached instance. Restart loads persisted true and
   starts the poller; a full pending queue prevents reprocessing. Final native
   PUT disables automation again.
6. Changing poll interval while already enabled leaves the same task running;
   disable/re-enable or an IQ-only recreation is needed to capture a new interval.
7. Zero remaining async tasks and zero temporary test processes at completion.
   Controlled stop/restart and timeout cancellation are covered; abrupt kill,
   host power loss and remote Ollama computation cancellation are not proven.

Run the full-application test in a **separate process**, not shared discovery with
other backend fixtures. With a public upstream checkout at the exact revision:

```sh
python3 -m venv /tmp/iq-stage2a-venv
/tmp/iq-stage2a-venv/bin/pip install /absolute/path/to/pinned-upstream
python3 -m governor.paperless_iq_patch \
  --source /absolute/path/to/pinned-upstream \
  --target /absolute/path/to/new-generated-directory
```

Copy the public upstream tree into a new isolated application directory, then
copy the six generated backend files over the corresponding isolated paths.
Never use production data/mounts. Run:

```sh
IQ_APP_SOURCE=/absolute/path/to/isolated-patched-application \
  /tmp/iq-stage2a-venv/bin/python tests/test_paperless_iq_application.py
```

The test uses temporary SQLite state and synthetic credential values, denies
network sockets and shuts down its application tasks. No real model is called.
Hosted CI covers the 31 source/audit tests; the full application rehearsal is
separate local evidence. No private document contents were processed in cloud.

## Production read-only preflight

At 20:16 GMT, terminal audit evidence (not merely workflow success) showed:

| Check | Actual result |
|---|---|
| IQ / Paperless / local Ollama | HTTP 200; expected local model available |
| Settings access protection | Unauthenticated 401 |
| Tracking/suggestions | 2,654 tracked, all unanalysed; original 10 pending across 5 documents unchanged |
| Paperless corpus / stack | 2,784 documents; 5 containers running, 3 healthy, 2 without healthcheck, 0 unhealthy |
| Original retrieval / NAS | Authenticated document list and sample original download PASS; mounts consistent |
| Local DNS | UDP and TCP answers from loopback 53, valid global A records |
| Internet / GitHub | Independent-IP verified TLS and GitHub HTTPS 200 |
| Protected HTTP routes | Home Assistant root 200; Predbat `/dash` 200 |
| SSH | ssh.service active; fresh LAN login/offline physical recovery not demonstrated |
| CPU / RAM / temperature | 1-minute load 2.221; available 9,991 MiB; 60.05 C |
| HDD free / reserve | 15,841,054,720 bytes / 15,639,126,835 bytes |
| Headroom above reserve | 201,927,885 bytes, approximately 192.6 MiB |
| Inodes | 6,520,122 free; 977,305 required |

The broad native inventory also reported 2 failed mail tasks. No imports were
retried, disabled or modified, and a point-in-time health check does not establish
sustained ingestion acceptance.

Predbat diagnosis: [status capture](https://github.com/joshant20-ops/lifeos-platform/actions/runs/44606666293)
returned 302 with a same-origin redirect. [Upstream web.py](https://github.com/springfall2008/batpred/blob/main/apps/predbat/web.py)
registers `/dash` and deliberately redirects its root. Direct `/dash` returned 200
in the final preflight, with redirects still disabled. This was a faulty probe
expectation, not evidence that Predbat needed repair. No Predbat changes occurred.
DNS/HTTP checks do not replace AdGuard container/process inspection or prove all
Home Assistant/Predbat functions. Those remain production mutation gates.

## Deployment and rollback readiness

[Runbook](DEPLOYMENT.md) now consistently describes a five-document pilot:
batch 5, initial pending ceiling P+5 with P <= 15, auto-apply false, no cron, no queue
dispositions during observation, then disable after five verified successes.
With current P=10 the proposed ceiling would be 15; remeasure P before any change.
No settings were applied. Preserve current IQ state during rollback; never
restore an old whole DB or erase newly generated suggestions as routine rollback.

Remaining Stage 2B blockers:

- Obtain an isolated rehearsal using the actual immutable deployed image and
  dependencies, including the remaining two live source fingerprints.
- Privately verify actual Compose files/service, data mounts, credential-key
  usability and backup/restore, a single worker/instance, in-container resource
  sensor visibility and limits. No bootstrap login credentials were available
  to the read-only audit; use authorised native access/maintenance, never bypass auth.
- Measure peak additional backup/image/test footprint and require that it fits
  **above** the disk reserve. Approximately 193 MiB of headroom is not a staging
  budget or permission to delete data. No cleanup/staging was attempted on Pi.
- Identify an existing authorised IQ-only mutation operation, or separately
  review/install its narrow gateway integration. Stage 2A added no privileged
  operation and does not authorise Stage 2B deployment.
- Recheck Tier 0 /protected-service health, recovery access, new/eligible-document
  selection and production model/quality expectations before the five-doc pilot.

Exact next action: obtain the missing read-only image/source/Compose/key/worker
and capacity evidence through the governed boundary, then execute an isolated
exact-image rehearsal. Do not enable production automation or merge/deploy this
candidate to work around missing evidence.

Work usage percentage is not exposed in this environment; the 10% threshold could
not be monitored. Work proceeded through recoverable branch commits. No production
configuration is partially applied. Stage 2A ends here pending the owner's next instruction.
