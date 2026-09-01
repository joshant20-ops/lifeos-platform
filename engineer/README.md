# OpenHands Engineer integration

This directory is the provider-independent boundary between OpenHands and the
LifeOS governor. `provider_router.py` applies the zero-spend policy in
`governor/policy.json`; `openhands_worker.py` supplies the selected provider to
OpenHands through `LIFEOS_PROVIDER`. Provider-specific runtime configuration
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
attempts and should enter the recorded 900-second cooldown after exhaustion.

Example dry-run on Engineer (normally exercised by Pi5 automation):

```text
python3 engineer/openhands_worker.py --repo /home/joshan/workspace/lifeos-platform \
  --task /path/to/redacted-task.txt --task-class normal \
  --secrets /home/joshan/.openhands/provider-secrets.env
```

`review_packet.py --repo PATH` creates the daily Codex senior-review packet
from bounded Git metadata, without repository contents. `cleanup_audit.py` is a
read-only dry-run inventory. It always preserves `.codex`, `.config/gh`,
`.ssh`, `.openhands`, Ollama storage, and the canonical workspace. Candidate
backups remain `REVIEW_REQUIRED`; `SAFE_TO_REMOVE` is deliberately empty and
automatic deletion remains disabled pending separate evidence and approval.

The job launcher `governor/runtime_jobs/9eb04949f627.sh` is the sole live Pi5
entry point for this iteration. It verifies OpenHands/workspace availability,
credential-file permissions, and cleanup dry-run behavior without printing
credentials, installing packages, deleting files, or mutating either host.
