# lifeos-pi-control

Private execution relay between ChatGPT/GitHub and the LifeOS Raspberry Pi.

This repository is **not** a source-of-truth implementation repository. Authoritative code lives in `joshant20-ops/lifeos-platform`.

The relay contains only:

- pending execution manifests
- thin wrappers that identify immutable `lifeos-platform` artifacts
- completed/archive manifests
- structured Pi results and captured output
- runner/broker state and control-plane code

Post-migration jobs must reference an exact `lifeos-platform` commit SHA and verify the canonical script hash before execution.

See `CONTROL_PROTOCOL.md`.
