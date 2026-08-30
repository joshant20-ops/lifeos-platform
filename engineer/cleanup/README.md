# Engineer VM cleanup policy

Cleanup is evidence-led and fail-closed. The sanitized inventory dated 2026-08-30 is the initial evidence source; `audit.sh` refreshes read-only facts without deleting, pruning, vacuuming, installing, or changing services.

Every candidate must be classified:

- `KEEP`: known useful operational material.
- `REVIEW`: plausible stale material that needs an owner or content review.
- `SAFE_TO_REMOVE`: an exact, evidence-backed disposable path. This is the only category the gated tool can apply.
- `DO_NOT_TOUCH`: credentials, current agent state, model storage, source checkouts, or other protected material.

Initial classifications live in `cleanup-plan.json`. Old bootstrap backups and OpenHands repair backups are surfaced, but only specific backup paths may be proposed; current OpenHands, Ollama, Codex, SSH, GitHub CLI, and repository state are never candidates. The apt autoremove simulation identifies an old kernel package, but package removal remains `REVIEW` and this phase does not run apt. Docker prune and journal vacuum are prohibited in this phase.

## Workflow

```sh
engineer/cleanup/audit.sh
python3 engineer/cleanup/cleanup.py --plan engineer/cleanup/cleanup-plan.json
```

Both commands are non-mutating by default. A later, separately approved session may use `--apply --confirm APPLY_SAFE_TO_REMOVE`; each target is resolved and checked against protected paths first. Review the fresh audit, plan, ownership, backups, and active-process references immediately before any apply. This bootstrap task does not apply cleanup.

The report is deliberately local machine evidence and may contain paths, so store it outside Git (the default is under `/tmp`). Do not copy credentials or file contents into reports.
