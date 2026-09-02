# Three-repository authority split

Status: accepted

## Decision

LifeOS separates desired state, durable engineering history and observed live
state into `lifeos-platform`, `lifeos-jobs` and `lifeos-snapshots` respectively.
Only `lifeos-platform` has deployment authority. Pi5 is the canonical Git writer
and exports only sanitised records to the evidence repositories.

This supersedes the earlier two-repository design in which
`lifeos-pi-control` was described as both an execution relay and a store for
captured output. A legacy local relay may remain during migration, but it is not
part of the target repository authority model and raw runtime output is not a
permitted Git artifact.

## Rationale

Separating job history from observed state gives each independently validated
schema a single purpose and prevents backups, logs or runtime observations from
becoming deployment inputs. Keeping live queue state and raw evidence local also
preserves the cloud-safe repository boundary.

## Trust boundary

- Pi5 owns publication and runtime orchestration.
- Watchman gates runtime execution.
- Cloud builders may process only cloud-safe repository content.
- Secrets, private documents, personal data, raw Home Assistant history and
  arbitrary runtime logs remain outside repository exports.

## Rollback

If either evidence exporter is unhealthy, stop that export and retain the
sanitised records locally on Pi5 until repaired. Do not restore the superseded
captured-output relay model, and do not promote evidence into desired state.
