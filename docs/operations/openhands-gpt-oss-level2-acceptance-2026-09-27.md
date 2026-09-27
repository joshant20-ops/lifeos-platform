# OpenHands GPT-OSS Level 2 acceptance — 2026-09-27

Status: **VERIFIED_COMPLETE investigation; Level 2 stopped at a genuine model capability failure.**

## Accepted architecture held constant

- Stock Agent Canvas 1.23.0 on Pi5
- active named profile `gpt-oss-20b`
- effective model `openai/gpt-oss:20b`
- native tool calling enabled
- SwitchLLM disabled
- Tower inference through the existing lifecycle gateway
- existing persistence and rollback topology
- deployment owns desired state; audit remains read-only

## Failed run reconstructed

Conversation `3ca801e5b31941e38bf1b7611f3ac44d` persisted seven events.
The full #935 instruction was present. The system event advertised Terminal,
File Editor, Task Tracker, browser, Finish, Think, Invoke Skill, and other stock
tools. The GitHub keyword skill was activated. The persistent repository existed
and was readable/writable at `/projects/lifeos-platform`, while Canvas assigned
the conversation an isolated per-conversation working directory.

The model made zero action calls. Its only assistant turn invented a CHANGELOG
workflow and supplied a shell script for the user to run. Therefore the failure
was not caused by missing tools, a missing prompt, context truncation, SwitchLLM,
or a different effective model. GitHub skill activation added API guidance but
did not ground the repository or compel tool use.

Bounded diagnostics:

- PR #1326 / run 36351250173
- PR #1329 / run 36351553519

## Durable correction

PR #1332, merge `75b9c8fa30c16325f9f28ac990e7151e7f5cdc02`, added an idempotent
deployment-owned system suffix to the stock Canvas agent. For explicit
repository engineering tasks it requires the first post-user turn to invoke the
native terminal, directs LifeOS discovery to the existing persistent checkout,
and forbids invented substitute tasks or user-run-script responses.

Regression tests assert the action-first, repository-specific contract and its
persistence after a full Canvas service restart. The deployed runtime verified:

- `OPENHANDS_DEPLOY_REPOSITORY_TASK_GROUNDING=PASS`
- `OPENHANDS_DEPLOY_REPOSITORY_TASK_GROUNDING_PERSISTENCE=PASS`
- `OPENHANDS_DEPLOY_GPT_OSS_PROFILE_PERSISTENCE=PASS`

Deploy run: 36351814985 (success).

## Clean Level 2 retest

Acceptance workflow PRs #1333 and #1334 launched clean conversation
`0c1e5acf80984e64b7001c08f5c6ed57` against #935 without providing its
solution. The workspace was the real persistent repository and a
workflow-scoped GitHub credential was exposed only as a conversation secret.

The grounding regression passed:

- first post-user agent event: `ActionEvent / TerminalAction`
- 38 persisted events
- four terminal actions and one file-editor action
- no invented CHANGELOG response

The run then exposed a separate genuine capability boundary. GPT-OSS repeated
`ls -la` three times, listed the repository, viewed only `README.md`, never
read issue #935, never diagnosed the inventory-status defect, and produced six
empty assistant turns. Stock Canvas supplied its normal “use a tool” recovery
messages and eventually entered `stuck`. The repository remained on `main`
with no changes, commit, branch, or PR.

Evidence:

- acceptance run 36352313634
- deterministic result runs 36352892807 and 36353012962
- inspection PRs #1335–#1337
- persisted terminal state: `stuck`
- Level 2: **FAIL — genuine GPT-OSS task-following/capability failure**
- Level 3 / #961: **not started**, per the staged ladder rule

This result distinguishes the corrected infrastructure/grounding defect from the
remaining model capability limit. No accepted architectural component was
replaced or redesigned.
