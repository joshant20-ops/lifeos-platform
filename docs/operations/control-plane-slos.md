# Control-plane service objectives

These are operating objectives and alert thresholds, not claims about historical
performance. Maintenance explicitly declared before work is excluded; undeclared
loss of service is not.

| Surface | Objective | Measurement | Recovery objective |
|---|---|---|---|
| Pi5 Governor health and queue admission | 99.5% monthly availability | Successful local health probe and ability to persist a bounded request | Alert after 5 minutes; restore admission within 30 minutes |
| Root-broker socket | 99.9% monthly availability | Socket active plus a non-mutating allowlist/status probe | Alert after 2 minutes; restore within 15 minutes |
| Transaction rollback watchdog | 100% for every armed transaction | Durable manifest plus enabled persistent timer before any mutation | Mutation fails closed if arming is unproven; overdue work rolls back at the durable deadline |
| Evidence publication | 99% within 15 minutes of terminal execution | Terminal local record linked to its immutable revision; remote publication may retry | Local evidence is authoritative during connector outage; publish within 24 hours |

The privileged boundary is now the root broker, protected transaction controller
and independent rollback service. “Watchman” is a historical compatibility name,
not a separate SLO target. Availability never overrides fail-closed policy: a
down broker delays mutation rather than permitting an alternate root path.
