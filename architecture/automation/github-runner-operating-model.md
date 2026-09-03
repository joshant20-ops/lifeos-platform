# LifeOS GitHub Runner Operating Model

Status: active

## Purpose

The dedicated self-hosted GitHub Actions runner `lifeos-pi5` is the default remote execution path for safe LifeOS automation on the Pi.

## Trust boundaries

- GitHub Actions runs as the unprivileged `joshan` account.
- Root access is available only through `/usr/local/sbin/lifeos-deploy-gateway`.
- The gateway accepts a fixed allow-list of named operations and rejects arbitrary commands, paths and shell fragments.
- The canonical `/home/joshan/lifeos-platform` checkout must be clean and equal to `origin/main` before any gateway operation executes.
- Existing privileged LifeOS boundaries such as `lifeos-root-broker.socket` remain separate and are not replaced by the GitHub runner.

## Evidence

Automation health runs publish machine-readable evidence to GitHub issue #29 and upload the same evidence as a workflow artifact.

## Automatic health loop

`.github/workflows/lifeos-pi-auto-smoke.yml` runs:

- after relevant automation changes on `main`;
- when a narrowly named health-trigger issue is opened; and
- every six hours.

The health operation is read-only and validates repository identity, retirement of obsolete dispatcher artifacts, Semaphore availability, protected LifeOS services, queue state and the GitHub runner service.

## Change policy

New privileged operations must not be smuggled through an existing allow-list name. They require an explicit gateway allow-list change and a reviewed bootstrap/update of the installed root-owned gateway.
