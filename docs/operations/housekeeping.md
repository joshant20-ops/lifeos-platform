# LifeOS platform housekeeping

LifeOS housekeeping is a standing Production Operations maintenance policy. It uses the tools already present in the platform: Git, GitHub Actions on the Pi5 self-hosted runner, SSH to Engineer, and standard Linux utilities. It does not add a daemon, container, monitoring product, package, or privileged execution path.

## Schedule

The canonical workflow is `.github/workflows/lifeos-housekeeping.yml`.

- Daily lightweight hygiene: `03:17 UTC`.
- Weekly deeper Git maintenance: Sunday `03:47 UTC`.
- Manual execution remains available with `daily` or `weekly` depth.

GitHub scheduled workflows use UTC, so the local UK wall-clock time moves by one hour when British Summer Time starts or ends.

## Safety contract

Housekeeping is prevention and bounded cleanup, not an automatic repair authority.

It may:

- run native `git worktree prune` to remove metadata for worktrees whose directories are already gone;
- run native `git gc --auto` during the weekly pass;
- remove only exact, known LifeOS temporary artifacts after they are at least three hours old;
- remove the known Engineer AI smoke worktree directory only when Git no longer registers it as an active worktree, it is not a symlink, and it is owned by the Engineer user;
- remove the known Codex smoke output only when it is an ordinary, user-owned, stale file;
- report repository state and storage evidence.

It must not:

- use `git clean`;
- use hard reset as a cleanup mechanism;
- delete unknown untracked files or tracked modifications;
- follow or delete an unexpected symlink;
- remove files owned by another user;
- install software;
- create a second scheduler, monitor, supervisor, or update system;
- wake Engineer solely to perform housekeeping;
- bypass Watchman or any existing privileged execution boundary.

Unknown repository dirt is preserved and the run fails closed with the exact Git status in the workflow log. That turns unexplained residue into an actionable defect instead of hiding it.

## Host coverage

### Pi5

The Pi5 is the always-on control plane and runs the scheduled workflow. The canonical `/home/joshan/lifeos-platform` repository is checked for exact `HEAD == origin/main` before housekeeping. Native Git metadata maintenance is then performed, followed by cleanup of only the explicitly listed stale AI smoke temporary files.

### Engineer

If Engineer is already SSH-reachable, its `/home/joshan/workspace/lifeos-platform` repository receives the same native Git metadata maintenance. Known smoke residue under `~/.local/share/lifeos-agent/` is cleaned only under the safety predicates above. If Engineer is offline, the run records `SKIP_OFFLINE`; housekeeping does not wake it merely to clean temporary state.

### Tower

No general-purpose file-management or SSH cleanup path is assumed for Tower. The production Ollama endpoint is an application interface, not authority to manipulate the host filesystem. Tower filesystem housekeeping therefore remains out of scope until an existing governed host-management path is explicitly documented. This avoids inventing access or adding a new service merely for cleanup.

## Prevention rule

Every LifeOS test, audit and deployment workflow should place disposable output in runner temporary storage, `/tmp`, or a dedicated runtime/state directory outside a Git worktree unless that output is intentionally source-controlled. Any newly discovered recurring residue should first be fixed at its source. A new automatic deletion target may be added only when the path has a unique LifeOS responsibility, its lifecycle is understood, and a focused regression test protects the safety boundary.

## Evidence

Each run writes a GitHub Actions summary containing the selected depth and Pi5/Engineer outcomes. Logs record exact stale artifacts removed and any unknown dirt that caused a fail-closed result. No secret or personal payload content should be copied into housekeeping evidence.
