# Superseded dashboard deployment owners

Archived during Gate I from the exact-main audit at `b7fe28913d664898ab21a719c81e6082f63a31cc`.

- `three-dashboard-role-deploy.yml` and `deploy-three-dashboard-roles.py` were a second writer for Homelab, LifeOS, and LifeOS Control. The workflow's last recorded live attempt (#36766922239) failed because its expected `lovelace.lifeos_control` storage file was absent. The helper also assumes Documents/Ask LifeOS/Important Information views that are absent from the current repository-native LifeOS source. Its sole active workflow reference was this workflow.
- `homelab-dashboard-deploy.yml` and `deploy-homelab-default-view.py` use a six-view `path=homelab` contract. The active Homelab V2 deployment is the current owner of `lovelace.dashboard_homelab` and expects the three populated Sections views `overview`, `network`, and `tower`. The older default-view operation conflicts with that deployed contract; its sole active workflow reference was this workflow.

The current Homelab V2 deployer/workflow, LifeOS personal dashboard deployer, and governed LifeOS Control bridge remain active as separate owners. Archive copies retain history and rollback provenance; active workflows no longer invoke these scripts.
