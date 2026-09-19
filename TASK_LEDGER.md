# LifeOS active task ledger

This file contains only work that survived the 2026-09-19 #1–#366 live audit.

## Audit evidence
- Live audit workflow: https://github.com/joshant20-ops/lifeos-platform/actions/runs/35443732378
- Live canonical commit audited: `1a4ca5a33596b458e393bfa9e3633c2e6b5a1f2f`
- Runner: `lifeos-pi5`; machine: `Docker`
- `REPO_CLEAN_ALIGNED=PASS`
- `RUNTIME_VISIBLE=PASS`
- Mission phase: `audit_passed`
- Current mission limitation: `PA_SCRIPTED_EXECUTION=INCOMPLETE`; Governor autonomy disabled by design.
- Full #1–#366 disposition/evidence archive: `lifeos-jobs/audits/task-ledger-2026-09-19.json` at commit `3345557e6e9f1222301cb1d1a6d41e142a2d3e25`.

## Retained numbered work
- [ ] #007 — **P1: Prove safe Z97 P106 shared-GPU R580 migration** — RETAIN — open; no current live acceptance. Historical GPU migration assumptions must not mutate drivers/packages.
- [ ] #014 — **Verify privacy-classifier fix end-to-end with fresh Engineer job** — RETAIN — latest issue evidence: focused tests PASS but Pi5 runtime launcher was never proven; current audit does not supply that missing E2E proof.
- [ ] #015 — **Design and build LifeOS Personal Assistant UI in Home Assistant** — RETAIN — open; current live audit does not prove the broader PA UX/navigation acceptance.
- [ ] #016 — **Build user-facing autonomous job interface and management layer** — RETAIN — open; current audit reports Governor autonomy DISABLED_BY_DESIGN and PA scripted execution INCOMPLETE.
- [ ] #017 — **Build LifeOS Finance: personal, rental and business accounting** — RETAIN — open; Finance & Assets remains active/partial.
- [ ] #018 — **Diagnose and stabilise Zemismart Matter smart-curtain integration** — RETAIN — open; Matter server is live but curtain-specific stability acceptance is not proven.
- [ ] #024 — **LifeOS central build list and backlog index** — RETAIN — persistent portfolio index by design.
- [ ] #103 — **Configure household WhatsApp delivery for energy alerts** — RETAIN — external account/recipient authorisation boundary remains.
- [ ] #104 — **Authorize Alexa announcement path for LifeOS energy alerts** — RETAIN — external integration/account authorisation boundary remains.
- [ ] #105 — **Approve cheap-power alert threshold policy** — RETAIN — explicit human policy decision remains.
- [ ] #164 — **Personal Administration delivery — Calendar + Email + Paperless** — RETAIN — current 2026-09-19 mission audit: phase audit_passed, but PA_SCRIPTED_EXECUTION=INCOMPLETE; do not close on historical merge alone.
- [ ] #200 — **LifeOS automation health failure** — RETAIN — current LifeOS CI is failing; automation health is not presently clean.
- [ ] #230 — **Diagnose Tower CPU thermal limit under local 8K inference** — RETAIN — historical 8K remediation exists, but current live audit did not probe Tower thermal acceptance; issue-specific proof is insufficient.

## Newly exposed live defects
- [ ] **CI cleanup regression** — active LifeOS CI fails because an active check still references the archived Wave-A helper. Repair the active CI contract; do not resurrect obsolete Wave-A implementation merely to make CI green.
- [ ] **Restore rehearsal regression** — latest restore rehearsal fails with `repository contract missing`; reconcile it with the three-repository authority model and re-prove non-destructive restore.
- [ ] **Stage-3 HA/Jinja deployment defect** — Python f-string processing collides with Home Assistant Jinja braces while adding Tower controls; repair and live-prove deployment/rollback.
- [ ] **Snapshot exporter stale** — `lifeos-snapshots` lacks current September observed-state evidence; repair the sanitised exporter and prove recurring export.
- [ ] **Runner inventory incomplete** — retained `lifeos-pi5` runner is live (runner 2.337.0), but every stale/offline/duplicate runner registration has not yet been proven removed.

## Disposition rule
Completed/obsolete work is not kept here. Its supporting evidence lives in `lifeos-jobs`. Work remains here whenever current evidence is failed, blocked, incomplete, or insufficient. A historical merge alone never overrides a current regression.
