
# ADR-0001: Open-source dependency selection

## Status

Accepted.

## Context

LifeOS Energy should avoid rebuilding mature protocol and infrastructure
libraries when a suitable maintained open-source project exists.

Curated catalogues such as `awesome-python` may be used to discover
candidate projects. Inclusion in a catalogue is not sufficient approval.

## Decision

Each external dependency must be evaluated for:

1. Direct relevance to the required capability.
2. Active maintenance and release history.
3. Compatible licence.
4. Supported Python versions.
5. Security and credential-handling design.
6. Test coverage and documentation.
7. Runtime footprint.
8. Ability to isolate the dependency behind a LifeOS adapter.
9. Validation against the actual target hardware.
10. A pinned, reproducible package version.

Dependencies are installed through the Python package manager and pinned in
`requirements.txt`. Whole catalogue repositories are not copied into the
application.

## Current decision

`pyenphase==3.0.1` is accepted for local Enphase Gateway communication.

LifeOS retains ownership of:

- public API contracts;
- history;
- dashboards;
- tariff calculations;
- optimisation;
- governance and safety boundaries.

`pyenphase` owns:

- Gateway communication;
- authentication;
- firmware-specific dataset discovery;
- Enphase response models.

## Repository policy

GitHub contains source, tests and documentation.

GitHub must not contain:

- credentials;
- tokens;
- private raw Gateway responses;
- runtime databases;
- operational logs.
