# Fixed read-only storage requests from Work

Status: proposed source only. No merge, installation, activation or live audit is
implied. Independent security review and owner approval are required first.

## What exists and what is actually verified

At base `10e8ca441561df9cddf62d256b887402c4bea42a`:

- [Runner operating model](../../architecture/automation/github-runner-operating-model.md)
  defines a dedicated Pi runner and the fixed deployment gateway. More than a
  declaration exists: [run 45196170650](https://github.com/joshant20-ops/lifeos-platform/actions/runs/45196170650)
  completed a job on `lifeos-pi5` at 14:37 GMT on 23 November. That is historical
  execution evidence, not proof it is online now. The connector could not list
  runners; registration/current permissions remain unverified.
- `governor/systemd/lifeos-autonomous-agent.service`, the control-job submission
  bridge and the root broker exist in source. Their current runtime status is
  not established here. The general control runner accepts diagnostic scripts;
  that is unsuitable as a new audit-only authority. Do not submit arbitrary
  scripts, manufacture deployment approvals or replace the root broker.
- The observed-state snapshot exporter has an existing daily timer and already
  publishes aggregate storage health. Keep that mechanism. It does not establish
  backup lifecycle holds or historical image deletion eligibility.
- The old Pi auto-smoke workflow mentioned by AGENTS and the operating-model doc
  is **archived** on current main, not an active workflow at the documented path.
  Its old schedule must not be treated as evidence of a working current loop.
- The backup inventory profile workflow refreshes the installed gateway for its
  privileged allocation route. Predbat observation calls `docker pull`. Neither
  is used as a read-only shortcut.
- [PR #2147](https://github.com/joshant20-ops/lifeos-platform/pull/2147) remains
  unmerged. Its bounded private recovery review remains useful for detailed
  reference classification. This transport reads the existing collector format
  and does not duplicate its archive investigation or silently deploy that PR.

## Smallest proposed route

Work requests the exact `/storage-audit-summary` comment on existing issue #2072,
or dispatches `storage-readonly-summary.yml` on main. The comment route uses a
capability available to the connected GitHub app; a dispatch tool is not assumed.
The owner-only, initially disabled workflow has no inputs. It shares `lifeos-pi5-control` concurrency with
existing host operations. Its single privileged request is:

```text
sudo -n /usr/local/sbin/lifeos-deploy-gateway storage-audit-summary
```

The explicit new allow-list entry runs only installed, root-owned audit code.
Unlike the legacy deployment path, this operation does not fetch/merge/check out
Git, refresh the gateway or execute a repository script as root. Extra arguments
are rejected. Installed library ownership/mode and the fixed executable are
checked. The existing root broker, agents, recovery and backup systems remain.

The audit runs in one on-demand systemd oneshot, not a scheduler, task database,
agent, inbound port or public SSH tunnel. The unit is read-only except its private
state directory, has no IP networking, limits CPU to 20% of one core and memory
to 384 MiB, uses low CPU/idle I/O priority, and has a 110-second timeout with
control-group termination. Missing telemetry, high load, low available memory or
high temperature defers collection. A reserve breach permits bounded metadata
only, skipping the larger inventory parsers. The reserve remains ten percent.

Only the installed worker connects to the local Docker socket. Its code accepts
specific GET endpoints for all-container listings, exact image inspection and
protected-container inspection. No runner socket permission, group membership,
HTTP proxy, Docker CLI endpoint parameter or Docker mutation is added. Protected
container identity/image/start time/restart count and running health are compared
before and after. This does not independently test household UDP/TCP DNS; that
remains part of live acceptance, not a reason to reconfigure DNS.

The worker reuses the existing retention and backup-profile parsers against a
cached local TSV. It reads existing private Predbat inventory, including KEEP
holds, and current all-state container references. No repeated full-disk or
million-file queue scan occurs. Stale metadata is labelled STALE, not discarded
or presented as current; stale unique-size estimates are withheld. Requests
reuse a five-minute public-result cache to avoid repeated expensive processing.
Neither source age nor filenames prove deletion eligibility.

Priority outputs cover backup logical bytes/groups, repair-snapshot logical
bytes/files, current untagged/unreferenced Predbat counts and fresh-enough cached
unique-size estimates. They are potential inspection capacity, not safe reclaim.
All recovery dependencies, terminal lifecycle state and restore requirements
remain separate gates. Guaranteed approved deletion bytes is always zero.

## Publication boundary

Only exact-schema integers, booleans and fixed status enums leave the Pi. Unknown
fields, paths, IDs, names, strings, oversized values and nonzero deletion authority
are rejected. Failures emit a fixed code, never exception text or raw daemon
responses. The workflow validates the result again before publishing its summary.
No raw artifacts are uploaded. Private configuration and evidence remain local.

The generic existing runner is not thereby a sandbox. Its broader permissions
are not proven safe by a passing audit. The installer refuses socket write access
or broad shell/Python/Docker sudo grants. Repository/runner-group policy must also
exclude untrusted PR and arbitrary workflow jobs from this host. If the existing
identity cannot satisfy that boundary, **do not enable this workflow**. A separately
approved restricted runner identity/runner-group change is required; this change
does not revoke the owner's permissions, register a runner or alter other jobs.
The new operation has no deletion authority, but it does not remove unrelated
existing gateway operations. Do not represent it as universal hardening of the
existing deployment account.

## One-time setup — only after review and explicit owner approval

First establish working independent LAN recovery and protected-service/DNS
health. Review the complete commit, permissions and rollback. Nothing below has
been executed by Work.

Prepare a root-owned mode-0600 private JSON file **outside Git** with exactly:

```json
{
  "storage_root": "/ABSOLUTE/LOCAL/STORAGE",
  "automation_root": "/ABSOLUTE/LOCAL/AUTOMATION",
  "inventory_tsv": "/ABSOLUTE/EXISTING/INVENTORY.tsv",
  "predbat_report": "/ABSOLUTE/EXISTING/PRIVATE-REPORT.json",
  "protected_container_names": ["LOCAL_DNS_NAME", "LOCAL_HA_NAME", "LOCAL_BROKER_NAME"],
  "max_cache_age_seconds": 86400
}
```

Use durable paths visible under the unit's read-only home protection, not private
temporary mounts. KEEP/HOLD identity roles in the existing collector report must
be correct; no identities are committed here. If evidence is currently on a phone,
move it privately to the Pi once. Future requests and processing stay on the Pi.

From a clean approved checkout at the exact reviewed commit, the setup command is:

```bash
sudo bash scripts/audits/storage/install.sh APPROVED_COMMIT_SHA /ABSOLUTE/PRIVATE-CONFIG.json EXISTING_RUNNER_ACCOUNT
```

This copies **only Git blobs at that approved commit** into root-owned installed
code, validates private configuration, preserves the old gateway, adds the fixed
oneshot and reloads systemd definitions. It changes neither sudoers nor runner
registration, creates no timer, starts no service and does not activate GitHub.
The current installed gateway must match the known reviewed baseline; otherwise
setup stops for inspection rather than overwriting an unknown version. A failed
setup may retain new inactive files and private staging for diagnosis; do not
blindly rerun or remove them. No production data is modified.

After boundary checks and approval of the installed scope, owner activation is:

```bash
gh variable set STORAGE_READONLY_AUDIT_ENABLED --repo joshant20-ops/lifeos-platform --body true
```

Workflow availability on main still requires a separately authorised merge.
Work can then request, poll and read the sanitised result through GitHub without
routine Termux commands. The primary Work route is the exact fixed comment
`/storage-audit-summary` on issue #2072, authored by the repository owner. No
new issue, arbitrary comment command, PR comment, path or edited-comment trigger
is accepted. Work reads the workflow's filtered log/summary; it does not need a
new SSH key or a workflow-dispatch connector. Do not post that trigger until
activation is separately approved. An optional CLI equivalent is:

```bash
gh workflow run storage-readonly-summary.yml --repo joshant20-ops/lifeos-platform --ref main
```

Live acceptance must prove freshness/STALE handling, no unexpected fields, fixed
operation rejection, Docker read-only behaviour, reserve/inode reporting, unchanged
protected containers and DNS UDP/TCP, and bounded resource use. Source tests do
not establish that acceptance. No cleanup is authorised by activation.

## Rollback

Set the activation variable to false. Let any bounded read-only run finish; no
production service needs a restart. The installer retains `gateway.before` under
its private setup directory. The owner can restore that exact saved gateway with
`sudo install -o root -g root -m 0755 /ABSOLUTE/SETUP/gateway.before /usr/local/sbin/lifeos-deploy-gateway`.
Leave audit evidence, original inputs, backups, snapshots and recovery systems
intact. No automatic removal or legacy gateway reinstall is included.

## Tests

The focused suite is stdlib-only with synthetic data and mocked Docker/systemd:

```bash
python3 -B -m unittest discover -s tests -p test_storage_remote_summary.py -v
bash -n scripts/audits/storage/install.sh
```

Existing backup/retention tests and gateway parsing regressions are also checked
locally. PR tests run on a GitHub-hosted runner; production execution is disabled.
No live installation or audit is required to test this proposal.
