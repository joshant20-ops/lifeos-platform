# Bootstrap boundary

This directory is reserved for reviewed bootstrap documentation and artifacts.
It intentionally contains no executable bootstrap or deployment content as part
of the repository-foundation work.

Any future bootstrap design must:

- preserve Pi5 as the control plane and Watchman as the execution gate;
- be non-interactive, repeatable, timeout-aware and independently auditable;
- keep secrets and host-specific values outside version control;
- prefer established open-source provisioning components; and
- include explicit validation and rollback instructions.

TODO: Select a bootstrap approach through a reviewed architecture decision before
adding executable artifacts.
