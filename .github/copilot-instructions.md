# Copilot instructions for LifeOS

- Treat this repository as the canonical source of truth.
- Keep Pi5 as the always-on control plane and Watchman as the sole runtime
  execution gatekeeper.
- Never add secrets, private document content, personal information, private
  addresses or invented hardware specifications.
- Prefer maintained open-source components over bespoke implementations.
- Keep Engineer, Auditor and Personal Assistant concerns separate. Do not create
  direct imports, process calls or runtime coupling between workers.
- Use files, explicit queues and repository state for worker communication.
- Mark unresolved design decisions as `TODO` and link relevant decision records.
- Make changes reviewable and include focused validation. Do not publish or
  execute runtime changes from a cloud editing session.
