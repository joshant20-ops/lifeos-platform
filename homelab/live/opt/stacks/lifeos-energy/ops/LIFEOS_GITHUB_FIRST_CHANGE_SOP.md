# LifeOS GitHub-First Change SOP

Status: ACTIVE  
Scope: LifeOS homelab scripts, services, configuration, collectors,
controllers, automation workers and other managed runtime code.

## Core rule

Before proposing or applying a modification to an existing managed
LifeOS component, inspect the current authoritative GitHub version first.

Do not reconstruct an existing managed script from conversational memory
when its source already exists in GitHub.

## Required pre-change sequence

1. Identify the runtime file or component being changed.
2. Identify its managed GitHub counterpart.
3. Refresh Git metadata from origin.
4. Prove the local repository is aligned with GitHub:
   - correct branch
   - local HEAD equals origin/main
   - clean worktree
5. Inspect the current managed implementation.
6. Compare:
   - GitHub/current managed source
   - known runtime behaviour
   - proposed change
7. Only then build the patch or installer.

If GitHub and the local clone disagree, stop and investigate before
changing runtime code.

## Existing-code rule

When a current implementation exists, patches should be derived from the
actual implementation rather than recreated from memory.

This specifically includes:

- command-line contracts
- secret-wrapper calling conventions
- systemd unit behaviour
- entity names
- filesystem permissions
- existing helper functions
- GitHub sync scope
- environment-variable contracts

## Runtime / GitHub three-way check

For changes to an existing component, establish where practical:

    GitHub managed source
             ↕
       runtime source
             ↕
       proposed patch

Unexpected differences must be explained before installation.

## Temporary diagnostic scripts

Temporary /tmp diagnostics do not need permanent GitHub storage.

However, they must still be designed against the current managed source
when inspecting or modifying an existing LifeOS component.

A temporary diagnostic must not assume an interface contract that can be
read directly from current code.

## GitHub publishing rule

The existing LifeOS nightly GitHub sync remains the single normal
publisher for runtime-managed files.

Installers and diagnostics must not create an independent GitHub pusher.

Unless explicitly authorised for a repository-management task:

- no git commit during an installer
- no git push during an installer
- no second scheduled GitHub publisher

## Post-change validation

After a managed change:

1. validate syntax
2. validate runtime health
3. validate the changed behaviour
4. verify the runtime file is inside nightly GitHub sync scope
5. preserve rollback evidence
6. allow the existing nightly sync to publish the managed state
7. on subsequent review, compare the published GitHub copy with runtime

## Fail-safe rule

Stop rather than patch when:

- GitHub cannot be refreshed
- local and remote HEAD differ unexpectedly
- worktree is dirty unexpectedly
- the authoritative source cannot be identified
- a required interface contract remains unknown

## Secret handling

GitHub-first inspection does not override LifeOS secret policy.

Never export:

- API keys
- passwords
- bearer tokens
- raw secret stores
- unredacted credential files

Inspect interfaces and contracts, not credential values.

## ChatGPT / operator workflow

When requesting a LifeOS code change from ChatGPT, the expected workflow is:

    inspect GitHub/current managed implementation
                    ↓
          understand runtime evidence
                    ↓
              generate patch
                    ↓
          staged local validation
                    ↓
        existing nightly GitHub sync

This SOP is mandatory for future LifeOS managed-code changes.
