# Governor AI routing

**Status:** implemented and live-proven 2026-09-06.

LifeOS uses the existing Governor/Engineer job path as the model-routing authority. There is no separate AI-router service and no new system of record.

## Runtime flow

`job -> privacy/task requirements -> Governor provider policy -> selected engineering adapter -> disposable Engineer worktree -> Pi-owned patch/runtime handoff -> local verification -> governed mutation -> evidence`

The provider decision is policy, not authority. A model may propose repository/runtime work, but it does not acquire root access. Privileged changes remain behind the root broker / protected transaction controller / independent rollback boundary.

## Provider policy

`governor/policy.json` is the canonical routing policy. The router chooses the cheapest sufficiently capable provider that is both privacy-allowed and actually runnable. Current roles are:

- deterministic tooling where no model is required;
- local Ollama for local/private and suitable lower-complexity work;
- Gemini, Groq, OpenRouter and Cloudflare through the provider-neutral OpenHands headless adapter when their credentials are available;
- Codex as the scarce/high-capability engineering fallback and escalation route.

Paid generic API fallback is disabled by default. Provider retries are bounded and a failed provider is not retried indefinitely.

## Privacy

`local-only` jobs cannot be routed to cloud providers, including Codex. Cloud jobs receive only the bounded engineering request/context and the builder performs defence-in-depth redaction of obvious credentials/private-key material. Provider credential values are not sent to Pi routing logic, GitHub, job evidence or model-selection logs. The Pi sees only adapter availability and credential names.

Provider secrets, when authorised, live on the Engineer host in:

`~/.config/lifeos/provider-secrets.env`

The file must be a regular non-symlink file with mode `0600`. Only credentials required by the selected provider are injected into that provider subprocess.

## Execution adapter

OpenHands is installed on the Engineer host as a user-level, pinned OTS agent harness. It runs headless with environment override enabled and operates in a disposable worktree. Codex remains available through its existing adapter. Both return bounded patch/runtime handoff artifacts to Pi; neither owns canonical Git publication or production mutation.

## Governance boundary

Watchman proper is retired. Live acceptance on 2026-09-06 proved zero Watchman systemd units and zero Watchman processes. The active privileged boundary is:

`root-broker socket -> transaction controller -> independent rollback`

Historical Home Assistant files or labels containing the word `Watchman` are compatibility/status residue and must be audited before retirement; their names do not mean a Watchman runtime still exists.

## Live evidence

- Governor service and health endpoint: PASS.
- OpenHands headless/environment-override capability on Engineer: PASS.
- Codex regression: PASS.
- Provider-routing focused CI: PASS.
- Provider-aware builder deployed root-owned through a protected LOW-risk transaction with independent hash/service verification: PASS.
- Installed builder hash equals canonical repository source: PASS.
- Privacy fail-closed routing: PASS.
- Watchman runtime retirement: PASS.
- Canonical repository clean after acceptance: PASS.

At implementation time no free-cloud provider credentials were installed on Engineer, so the live normal cloud-builder route correctly selected Codex. Free-provider activation is therefore an account/credential boundary, not an implementation gap.
