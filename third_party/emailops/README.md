# EmailOps headless integration

Authority: issue [#1498](https://github.com/joshant20-ops/lifeos-platform/issues/1498),
EmailOps-first decision of 22 October 2026. Gmail remains the message authority,
Paperless the evidence authority, and the existing reconciler the only task
projection publisher.

`config/emailops-upstream.json` pins official EmailOps 0.6.16 source at an exact
commit. Builds verify the Git tree, `git archive` SHA-256 and upstream lockfile
before applying the separately checksummed patch. There was no release asset
in the inspected upstream release listing. These are source integrity checks;
no publisher signature is claimed. Upstream is Apache-2.0.

## Gaps at the pinned revision

| Gap | Classification | Local change |
| --- | --- | --- |
| JSON account-add requires a password in argv | UPSTREAM_GENERIC | Private `--password-file`, with synthetic permission tests |
| Local AI cannot be configured through the CLI | UPSTREAM_GENERIC | `config local-ai` over existing AI config service |
| No structured task preview command | UPSTREAM_GENERIC | `analyze ID` over existing task extraction; creates no task rows |
| Provider Junk exists only in the desktop command boundary | UPSTREAM_GENERIC | Confirmed CLI operation over native provider services, with Message-ID and mailbox read-back |
| Cross-system document choices and task closure | LIFEOS_ADAPTER | Existing confirmed request coordinates Paperless only after provider verification |
| Lifecycle/completion is absent from the extracted payload | UPSTREAM_GENERIC | Remains UNKNOWN; blocks classifier promotion |
| Full historical corpus and user-visible acceptance | LIFEOS_ADAPTER | Pending private shadow comparison; three initial samples are a smoke test, not full acceptance |

Upstream contribution guidance and open work were inspected before creating the
patch. No private fixtures, mailbox data or credentials are included. Larger
task/lifecycle API changes must be proposed upstream before a contribution PR.
The checked-in patch is temporary integration work, not a forked email engine.

## Runtime and trust boundaries

The public ARM build uses no private data. Its artifact manifest binds the
binary checksum to this platform commit, pinned upstream source and patch.
The fixed `deploy-emailops-shadow` gateway operation verifies the artifact,
installs a root-owned binary, adds the native Linux Secret Service dependency,
and starts an isolated oneshot service as `joshan` with bounded CPU/memory/time.
No desktop, compiler or model is installed on Pi5.

The profile is `/home/joshan/.local/share/lifeos/emailops-shadow` (0700). An
isolated D-Bus/gnome-keyring session uses a separate encrypted keyring. Existing
governed Gmail credentials arrive through systemd `LoadCredential`; they never
appear in argv/logs/source. The generated keyring-unlock credential protects
that cache; `/etc/lifeos/secrets/gmail-*` remains the credential authority.

AI is explicitly Ollama through the existing local broker URL/model. A public
AI URL is rejected. Initial sync is limited to a 30-day account floor, a
five-minute sync timeout, and three analyzed messages from at most 200 listed
messages. Only exact RFC Message-IDs link samples to existing tasks.

Private results remain on Pi5. Matched samples appear as **EmailOps preview**
inside the existing authenticated Task Review. Public Actions output contains
fixed status codes and counts only. The sample verifies that task and user
state hashes stay unchanged. It never promotes proposals or infers completion.

## Junk transition

While policy is `shadow`, the legacy Junk processor holds requests, preserving
the selected document IDs. New requests leave the path-triggered inbox so they
cannot cause a service restart loop. Existing failed requests stay recoverable.
Mailbox actions are disabled in the shadow adapter.

The future confirmed action runs through a separate fixed user service, sharing
the isolated keyring. It requires source policy acceptance and a matching
installed build. All sources must resolve uniquely before any mutation; a local
spam flag, a missing provider message or a successful move request alone cannot
produce a verified proof. Only verified proof for the current request permits
the existing coordinator to delete selected Paperless documents and dismiss
the task. Automatic classification remains a separate migration gate.

## Recovery and rollback

Installation retains the previous binary, manifest and unit under
`/opt/lifeos/emailops-shadow/backups`. A failed sample restores existing program
files; profile, selected requests and evidence are retained. No timer is added.
The shadow service can be rerun after a restart; native account/keyring state is
reused, and private reports are written atomically.

Rollback disables the shadow integration and restores the previous program/unit
through a reviewed deployment. Do not delete the profile or pending/held user
requests. Do not enable the legacy mailbox writer just to clear a card.

## Structured extraction candidate

The temporary native patch now routes task extraction through the existing JsonShape provider support and adds nullable fields so unknown due dates remain null. It bounds task count and text fields without changing the model, extraction prompt or task authority. Native schema/grammar and extractor tests run on the ARM builder. This is an UPSTREAM_GENERIC candidate; live shadow/corpus acceptance is still required. Discuss the nullable shape API with the maintainer before opening an upstream API-change PR.
