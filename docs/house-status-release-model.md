# House Status release and promotion model

## Current audit

Before this change, DEV (`homeassistant/www/house-status-dev/`) and the proposed v29 bundle were separate JavaScript implementations. They shared most chart code but had drifted in behavior, loader code, Doorbell namespace, labels, styling, and fetch timing. v28 is a frozen production release, not a copy of current DEV. The older `homeassistant/www/house-status/` files are compatibility/test sources and are not installed by either governed deploy workflow.

The DEV loader registers the isolated `/house-status-dev` panel from `/local/house-status-dev/`. The Live panel is registered in `homelab/live/opt/stacks/homeassistant/config/configuration.yaml` at `/house-status`, from `/local/house-status/`; the Live workflow and deployer previously named v28 directly. `scripts/lifeos-deploy-house-status-dev-dashboard.sh` installs only DEV files and verifies that production dashboard/storage/assets and the v28 panel stanza remain byte-identical. The Live deployer has backup/restore-on-failure behavior. DEV and Live have separate verification scripts and workflow jobs.

PR #1731 changed the production-facing workflow, deployer, verifier and tracked registration to target v29. Because the manual Live workflow checked out `main` and ran those changed files, a later dispatch would have installed v29. A manual trigger did not protect the target: the target itself had been changed in a normal merge. PR #1732 restored v28.

## Architecture after this change

- `homeassistant/www/house-status-dev/lifeos-house-status-dev.js` is the only editable application source for new behavior.
- `homeassistant/build-house-status-release.py` produces a versioned Live bundle from that DEV source. It allows only listed environment substitutions and verifies that reverse-normalizing the result reproduces the DEV source byte for byte. It packages the companion Doorbell module the same way.
- Each DEV deploy builds the `next_candidate_release` from that exact source commit (currently v30; the pointer advances only in a reviewed release approval) and emits both source and packaged SHA-256 identities into the successful DEV job log. The DEV job still deploys only to `/house-status-dev` and checks the browser-served DEV bytes.
- `homeassistant/releases/house-status/live/lifeos-house-status-v28.js` and its companion remain immutable as the approved Live rollback release. v29 remains in Git as an inert historical/unapproved artifact; it is not an eligible promotion input and is absent from the approved manifest and Live workflow.
- `homeassistant/releases/house-status/live/approved-release.json` is the production release pointer. It currently pins v28 plus its exact SHA-256 and existing successful Live baseline evidence. A normal app merge does not update this file or select a new Live target.
- The Live workflow is manual only and requires both the selected release and full artifact SHA-256. It checks that they exactly match the reviewed manifest. A future candidate is rebuilt from the accepted DEV commit recorded in the manifest, and the rebuilt artifact must match the approved digest. Its named DEV workflow run, attempt, source commit, successful deploy job, served DEV hash, rolling-period/Year regression markers, and build attestation are verified before deployment.
- v28 remains the only approved production target now. A later promotion requires a separate reviewed change to `approved-release.json` after DEV acceptance; merging normal application code cannot arm it. The separate Live workflow dispatch must explicitly repeat the release identity and hash.

### Deterministic substitutions

The packager currently changes only environment identity and presentation markers: DEV loader URL to a versioned sibling Doorbell import; DEV custom element/editor and module namespace to the release identity; DEV labels to release labels; DEV-only purple outline/accent to the existing Live styling; and DEV-specific warning text. It does not alter chart/window calculations, data retrieval, event history, or view interactions. The packager fails if any expected substitution count changes, if DEV URLs/names remain in the Live output, or if the output cannot be reversed exactly to the input source.

Environment-specific values that remain explicit are the `/house-status-dev` versus `/house-status` panel route, `/local/house-status-dev/` versus `/local/house-status/` asset path, custom-element and Doorbell module names, admin requirement, cache-busting module URL, release label, and Live asset destination. Both environments use the same energy API path and application behavior source for releases built by this packager.

## Promotion procedure

1. Change application behavior only in `homeassistant/www/house-status-dev/` and merge the ordinary DEV change. This is candidate creation, not Live approval.
2. Wait for the main-branch **House Status Development Deploy** run. It deploys DEV, compares the cache-busted browser-served file to source, runs the regression, and logs the accepted source commit, packager commit, and candidate asset digests.
3. For a release to be considered, prepare a separate reviewed promotion PR that sets `approved_production` to the release and exact app digest; records the source commit, packager commit/version, companion asset digest, and exact successful DEV run ID/attempt. The DEV job log is the evidence. Candidate creation or merge alone is not approval.
4. Only after explicit user approval of that promotion may the manifest change be merged. Then manually dispatch **House Status Live Deploy** on `main`, entering the same release ID and full app digest from the manifest. It fails closed on missing selection, pointer mismatch, invalid/missing DEV acceptance, source/build hash drift, DEV URL leakage, or missing workflow evidence.
5. Live validation fetches the browser-served versioned app and Doorbell asset and byte-compares each against the artifact that was built from the accepted source commit.

## Rollback

The previous release remains immutable and installed under its versioned asset name. To roll back, use the prior approved manifest record from Git history and restore its `approved_production` identity and artifact SHA-256; keep the old release as `previous_production_release`, then explicitly dispatch Live Deploy with that release and hash. For the current approved v28 baseline, this selects the frozen v28 bundle and its recorded successful Live baseline evidence. If deployment itself fails after mutation, the deploy script restores the saved configuration and any overwritten release assets and restarts Home Assistant; the workflow then fails. No rollback relies on rebuilding code from current DEV.

## Current approved state

`approved-release.json` is v28, with `lifeos-house-status-v28.js` SHA-256 `213e00ad65d5b3e45fdcc598b8691718e1230893dbe2af5ba3f90fddc98d0ade`. v29 is not approved. No Live workflow was dispatched as part of this audit or implementation.
