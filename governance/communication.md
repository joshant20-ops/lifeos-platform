# Worker communication governance

## Separation

Engineer, Auditor and Personal Assistant are distinct security and responsibility
boundaries. Activating, retiring or replacing one does not transfer its authority
to another. No worker may directly import another worker's code, call its process,
or depend on its in-memory state.

## Permitted channels

Workers communicate only through:

- versioned files in the appropriate repository;
- explicit queue records with documented schemas; and
- immutable repository state and review evidence.

Each record must identify its producer, intended consumer, schema version and
correlation identifier. Inputs are untrusted until validated. Consumers must be
idempotent where retries are possible and must emit a terminal status or a clear
retry state.

## Authority flow

- Engineer concerns may propose changes but cannot approve their own proposals.
- Auditor concerns validate proposals and record evidence but do not silently
  rewrite them.
- Personal Assistant concerns manage user-facing coordination without gaining
  engineering or audit authority.
- Pi5 owns orchestration and canonical Git publication.
- Watchman alone permits or denies runtime execution.

## Data handling

Queue and repository records must contain only the minimum cloud-safe metadata
required for coordination. Secrets, personal information and private document
content must remain in approved local stores and be referenced only by opaque,
non-sensitive identifiers when necessary.

## Failure behavior

Malformed, unauthorized, ambiguous or expired work fails closed. Rejection and
timeout evidence must be recorded without sensitive payloads. A worker outage
must not be bypassed by coupling another worker directly to its internals.

## TODO

- TODO: Standardize schemas, expiry rules and retention policies for each queue.
- TODO: Define the independent audit evidence required for each execution class.
