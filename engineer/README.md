# OpenHands Engineer integration

This directory is the provider-independent boundary between OpenHands and the
LifeOS governor. `provider_router.py` applies the zero-spend policy in
`governor/policy.json`; the canonical Governor/OpenHands adapter supplies the authorized broker endpoint and bounded capability to OpenHands. Provider-specific runtime configuration
belongs on Engineer, not in Git.

The worker defaults to dry-run and requires a non-main branch. Execution needs
an explicit `--execute`, invokes OpenHands headlessly with a compact task
packet, and proves that the local `main` ref did not change concurrently. It
does not publish or merge a branch and has no SSH/deployment path. Publication
must use the normal GitHub branch/PR flow; Pi runtime work continues through
`lifeos-pi-control`.

Runtime credentials may be supplied only by an external regular, non-symlink
file with exact mode `0600`, conventionally
`/home/joshan/.openhands/provider-secrets.env`. Missing credentials are emitted
as `CREDENTIAL_REQUIRED`; routing continues to the next eligible free provider.
Values are passed only to the selected child process and are never placed in
evidence. Paid fallback is forbidden by policy. Each provider is bounded to two
attempts; an exhausted provider receives a machine-readable 900-second cooldown
marker and the worker moves to the next eligible free provider.

Example dry-run on Engineer (normally exercised by Pi5 automation):

OpenHands engineering is launched through the canonical governed builder path; this directory no longer contains a second standalone worker.

Repository review, cleanup reasoning, and engineering inspection now belong to the canonical OpenHands engineering session. Deterministic safety and acceptance checks remain outside OpenHands. Candidate
backups remain `REVIEW_REQUIRED`; `SAFE_TO_REMOVE` is deliberately empty and
automatic deletion remains disabled pending separate evidence and approval.

The governed runtime launcher staged under `/var/lib/lifeos-agent/runtime_jobs` is the live Pi5
entry point for this iteration. It verifies OpenHands/workspace availability,
credential-file permissions, and cleanup dry-run behavior without printing
credentials, installing packages, deleting files, or mutating either host.
