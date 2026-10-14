# House Status development panel

This directory is the isolated development panel served at `/house-status-dev`.

- Edit new application behavior only in this directory.
- The DEV deploy installs only these files under Home Assistant's `www/house-status-dev` and manages only `lifeos-house-status-dev`.
- The loader imports the development bundle with a cache-busting URL. DEV deployment does not restart Home Assistant unless the DEV panel registration must be added or upgraded.
- Each main-branch DEV acceptance run also builds a versioned Live candidate from the accepted DEV source. The build applies only the checked-in environment substitutions and logs exact source and artifact hashes.
- Building, merging, or accepting a candidate does not approve or deploy it to Live. A separate reviewed production-pointer change and a separately selected manual Live deployment are required.

See [`docs/house-status-release-model.md`](../../../../docs/house-status-release-model.md) for the current v28 pointer and future promotion/rollback procedure.
