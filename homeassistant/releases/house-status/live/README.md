# House Status Live releases

`approved-release.json` is the only production release pointer. It currently approves the frozen v28 artifact and SHA-256. v29 is retained as an inert, unapproved historical candidate; the Live workflow cannot select it.

New application behavior is edited only in `homeassistant/www/house-status-dev/`. The DEV workflow deterministically packages that source for a versioned Live candidate, records the candidate hashes and accepted source identity, and validates the browser-served DEV implementation. A separate reviewed manifest change is required to approve that exact accepted candidate. The manual Live workflow then requires the matching release ID and artifact SHA-256 and revalidates the DEV run evidence before deploying.

Candidate creation or merge is not production approval. Production promotion requires separate explicit user approval. See [`docs/house-status-release-model.md`](../../../../docs/house-status-release-model.md) for the audit, promotion, and rollback procedures.
