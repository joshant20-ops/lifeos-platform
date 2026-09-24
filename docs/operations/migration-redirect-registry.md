# LifeOS Migration Redirect Registry

This file is the canonical register for compatibility redirects created when LifeOS
moves a path, interface, configuration authority, service, or other discoverable
resource.

## Migration rule

**Move -> register -> redirect -> update consumers -> verify -> retire redirect.**

A migration is not complete merely because the new location works. Existing
consumers must either be updated or deliberately supported by a compatibility
redirect until they are migrated.

## Required fields

| Field | Meaning |
|---|---|
| ID | Stable migration identifier |
| Old location | Historical path/name/interface consumers may still use |
| Canonical location | Current authoritative destination |
| Redirect | Symlink, stub, alias, wrapper, documentation pointer, or other mechanism |
| Consumers remaining | Known consumers that still use the old location |
| Moved | Date the authority changed |
| Last verified | Most recent redirect/consumer audit |
| State | planned, active, ready-to-retire, retired |
| Retirement evidence | Evidence that no supported consumer still needs the redirect |

## Registry

| ID | Old location | Canonical location | Redirect | Consumers remaining | Moved | Last verified | State | Retirement evidence |
|---|---|---|---|---|---|---|---|---|
| MIG-001 | Engineer VM OpenHands / Agent Canvas runtime | Pi5 OpenHands / Agent Canvas at 192.168.0.203:8443 | Documentation pointer; do not recreate the retired Engineer runtime | Legacy Governor/Engineer references still being audited | 2026-09-24 | 2026-09-24 | active | Pending Governor-to-OpenHands consumer migration |
| MIG-002 | Governor continuation job fields (`continuation_enabled`, `continuation_depth`, `continuation_reason`, `continuation_request`) and automatic child-job strategy loop | OpenHands engineering session | Governor `/jobs` returns `410 governor_continuation_retired` with `canonical_owner=openhands` when a legacy field is submitted | No repository producer found; live callers still require deployment-time audit | 2026-09-24 | 2026-09-24 | active | Repository-wide consumer search found only retired implementation and tests; retire rejection after live request audit confirms no external caller |

## Redirect requirements

1. Redirects must never contain credentials or duplicate secret values.
2. Prefer a filesystem symlink only when the target resolves correctly from every
   environment that consumes the old path.
3. Across container/host boundaries, prefer a small explicit stub or configuration
   alias that names the canonical destination.
4. A redirect must not silently restore a retired service or duplicate authority.
5. New code must use the canonical location directly; redirects are compatibility
   aids for existing consumers only.
6. Retirement requires a repository/runtime search or equivalent evidence showing
   that supported consumers have moved.
7. When a redirect is retired, keep its registry row and mark it `retired`; the
   registry is also the historical map for future agents.

## OpenHands migration policy

During the Governor -> OpenHands migration, OpenHands should consult this registry
before concluding that a historical resource is missing. If it encounters an old
location, it should follow the registered canonical destination and update the
consumer when that is safe and in scope. It must not remove an active redirect
without retirement evidence.
