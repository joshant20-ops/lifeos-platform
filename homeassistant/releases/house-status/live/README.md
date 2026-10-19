# House Status Live releases

The production pointer approves immutable release `v34` with SHA-256 `9ec4c52ddc7d102a157f368d17992a11b534b190690beadac1843dd418eded6b`. Previous production remains `v32` with SHA-256 `81c1280c015d8ea06fb12f0e70123f613c6d157a43ecba4905a25f8e7bfb5d57` for rollback.

The v34 Doorbell module is isolated in its own versioned module and custom element with Shadow DOM. Its card markup and styles live inside the shadow root; its Lovelace bootstrap, native camera-card lifecycle, and Home Assistant state updates remain local to the Doorbell module. The shared House Status app dispatches Doorbell mode before reading Energy state, loading Energy history, or rendering other cards. Doorbell registration and camera failures are contained within that card.

New application behavior is edited only in `homeassistant/www/house-status-dev/`. The DEV workflow deterministically packages that source for an immutable versioned Live candidate, records the candidate hashes and accepted source identity, and validates the browser-served DEV implementation. Promotion requires the accepted DEV run, exact source and artifact hashes, a separate reviewed manifest change, and the manual Live workflow. The manual Live workflow revalidates the DEV run evidence before deploying.

Candidate creation or merge does not deploy to production. The previous production release stays available for rollback. See [`docs/house-status-release-model.md`](../../../../docs/house-status-release-model.md) for the audit, promotion, and rollback procedures.
