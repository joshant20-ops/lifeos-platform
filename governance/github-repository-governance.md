# GitHub repository governance

## Purpose

GitHub is the canonical source of truth and change-control plane for LifeOS. This
policy keeps that control plane understandable as autonomous agents increase the
number of branches, pull requests, workflows and evidence runs.

The aim is not to enable every GitHub feature. It is to preserve a small,
auditable operating model appropriate for one human owner and governed
automation.

## Main branch policy

The `main` branch represents accepted repository state.

Configure a repository ruleset for `main` with these controls:

- block branch deletion and force pushes;
- require changes through pull requests;
- require the `LifeOS CI / security` and `LifeOS CI / validate` checks;
- require branches to be current before merge when GitHub can do so without
  bypassing a time-critical recovery;
- allow the repository owner to perform an explicitly documented recovery
  bypass;
- do not require a second human reviewer while LifeOS has one human owner.

GitHub App administration permissions are deliberately not granted to the
automation connection. The owner must apply or verify this settings-only rule.

## Pull requests

Substantial changes use a review branch and the pull-request template.

A pull request records:

- intended outcome and scope;
- safety boundaries and private-data impact;
- validation evidence;
- rollback;
- whether runtime deployment is required.

One-shot diagnostic branches may be used, but their durable conclusion belongs
in canonical documentation, an issue, or an artifact. A merged branch is not a
long-term evidence store.

## Branch lifecycle

Enable **Automatically delete head branches** in repository settings.

The repository-hygiene workflow is report-only. It may identify a branch as a
cleanup candidate only when all of the following are true:

- it is not the default branch;
- it is not protected;
- no open pull request uses it;
- a merged pull request used it;
- that pull request merged at least 14 days ago.

Deletion remains a separate, reviewed action. Recovery, migration-evidence and
active-investigation branches must not be inferred safe from their names alone.

## Workflow lifecycle

Permanent workflows provide a reusable capability. Temporary investigations
should prefer `workflow_dispatch` inputs or reusable workflows instead of
adding another nearly identical workflow.

Workflows should:

- use least-privilege `permissions`;
- define `concurrency` when a newer run makes an older run obsolete;
- use path filters only when excluded paths cannot affect the result;
- distinguish expected experimental failure from a broken required check;
- upload bounded, sanitised evidence;
- be removed or archived after their conclusion becomes durable.

A red required check is actionable. Experimental workflows must not make the
default branch appear permanently unhealthy.

## Issues, projects and the task ledger

GitHub Issues and a small Project view are the human-facing roadmap:

- Now
- Blocked
- Next
- Later
- Done

`TASK_LEDGER.md` remains machine-readable historical acceptance state. It must
not be duplicated wholesale into the Project. Project items should represent
current outcomes or blockers and link to detailed ledger evidence when needed.

## Stable checkpoints

Use the **LifeOS Stable Checkpoint** workflow after a known-good operational
milestone. It reruns LifeOS CI and creates a GitHub Release only if validation
passes.

Suggested tag form: `lifeos-YYYY.MM.DD-short-name`.

A release is a recovery landmark, not proof that every historical ledger item is
complete. Release notes must name known limitations and link to operational
evidence.

## Dependency and security handling

Renovate remains the dependency-update authority. Major updates never
auto-merge. Gitleaks remains a required CI check.

Do not enable additional security products merely to increase feature usage.
Enable them only when their findings have a defined owner and response path.

## Features intentionally not required

Wiki, Discussions, Pages, Codespaces, Packages and multi-reviewer approval
chains are not part of the current operating model. They can be reconsidered
when a concrete LifeOS requirement appears.

## Review cadence

Run the repository-hygiene report weekly and review it monthly. Review:

- cleanup-candidate branches;
- open issue and pull-request counts;
- active and disabled workflows;
- repeated failed runs;
- whether temporary workflows have become permanent accidentally;
- the age of the newest stable checkpoint.

The report never deletes branches, closes issues, disables workflows or changes
repository settings.
