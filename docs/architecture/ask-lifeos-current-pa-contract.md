# Ask LifeOS: current PA attention contract

## Discovery

The existing Home Assistant PA path already publishes a bounded
`lifeos_tasks_v3` view. The task reconciler is its sole publisher;
`governor/pa_user_state.py` applies user-owned annotations and derives the
`lifeos_attention_projection_v1` buckets. The existing assistant bridge reads
the local published view, rejects missing, stale, or unsupported state, and
answers supported attention questions without calling an LLM. Personal
interpretation remains on the local assistant boundary.

The installed LifeOS Assistant UI calls the existing `/assist` interface. A
live PA checkpoint is recorded in issue #1498 (run 39308703366): reconciliation
and the Home Assistant attention projection passed, as did the existing PA
assistant retrieval cases. No new database, task publisher, document service,
or agent is needed for this slice.

## Deterministic request/answer contract

1. **Question:** accept the existing `/assist` message shape and recognize a
   bounded request for current open attention, including ordinary wording such
   as “What do I need to deal with?”. Unsupported or ambiguous requests must
   not be presented as current task facts.
2. **Retrieval:** read the current `lifeos_tasks_v3` projection, apply the
   existing user-owned status, snooze, severity, due-date, and comment state,
   then select the matching attention rows. Do not query email or documents
   again for this deterministic question.
3. **Freshness and privacy:** require the existing schema and freshness guard;
   fail closed when the view is unavailable or stale. Keep question and answer
   processing local. Do not emit private task, email, or document content in
   acceptance logs.
4. **Answer:** return a short bounded list derived only from the selected rows,
   preserving status, severity, and due date when present. Include each
   obligation's stable task ID and source kind so a user can match the answer to
   the Home Assistant PA card. Keep source message references and Paperless
   document IDs available as provenance; never imply that structured retrieval
   proves facts beyond the stored projection.
5. **Machine provenance:** retain the existing structured provider marker,
   `lifeos_tasks_v3` source schema, local-only privacy marker, structured-state
   confidence, and matched obligation IDs in the `/assist` response.

Deterministic retrieval and formatting must not invoke an LLM. Local inference
is reserved for questions that genuinely need semantic interpretation beyond
the structured projection.

## Isolated acceptance

After the shared PA deployment owner is available, add deterministic tests for
the natural-language attention request, freshness failure, bounded output,
and task/source provenance. Then use the existing governed Pi runtime path to
issue the same question against the current published projection. Compare the
returned obligation IDs with the current open attention rows and verify each
ID/source kind resolves through the existing Home Assistant PA card. Log only
route, schema, provider, privacy, result count, and pass/fail booleans. Do not
seed, mutate, or print household task content for this acceptance.

Acceptance requires the actual `/assist` answer to match the current source
projection and expose enough task/source identity to verify the result. Unit
tests and CI alone are insufficient.

## Lane boundary

The smallest product change is in `governor/assistant_bridge.py`, which is
shared with the active PA matter/timeline work. Its normal production workflow,
`.github/workflows/lifeos-pa-deploy.yml`, deploys both the assistant and the
task reconciler and runs state-mutating Gate H acceptance under the single PA
deployment queue. Do not land or deploy an Ask change while Lane B owns that
shared promotion path. Resume this contract when the PA deployment owner is
available; no Lane B timeline/reconciler change is proposed here.
