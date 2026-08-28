# WEIPING_COUNCIL Agent Instructions

`WEIPING_COUNCIL` is an honest multi-model deliberation runtime. It preserves protocols, model routing evidence, dissent, timings, degraded-state warnings, and session artifacts so users can inspect what happened.

## Source Of Truth

Read `README.md`, `CLAUDE.md`, `pyproject.toml`, `.codex/skills/weiping-council/SKILL.md`, `backend/runtime.py`, `backend/providers/router.py`, `backend/council/orchestrator.py`, `backend/main.py`, and `vc.py` before non-trivial work. The project skill is mandatory for implementation, release, maintenance, monitoring, or upgrade tasks.

## Boundaries

- Never fake model success or hide degraded provider/memory state.
- Provider credentials must stay environment-only and redacted from API, CLI, UI, logs, and docs.
- Keep provider identity separate from council-member identity.
- Tests must be hermetic; do not let ambient machine credentials decide test results.
- Do not revive retired local mailbox/state or markdown memory dependencies.
- Preserve `vipin-council` as a compatibility alias only where historically needed.

## WEIPING Constellation

`WEIPING_WIKI` is the public durable route map, not a runtime dependency. `WEIPING_LAB` is the broader research workbench. Council may export inspectable session JSON for Lab, but Council must not require Lab workspace state, private `.env`, local DBs, caches, or active Lab services to run.

Recurring WEIPING maintenance may inspect entry evidence, health/status commands, docs, and git state. It should not edit saved sessions, runtime outputs, local provider config, frontend build artifacts, or generated files unless the user explicitly scopes Council work.

Saved handoffs live at `data/sessions/<uuid>.json`. Treat that as runtime evidence with a schema contract, not as source to stage during general maintenance. Required fields include `id`, `query`, `protocol`, `created_at`, `stages`, `final_answer`, `confidence`, `dissent`, `audit_trail`, `routing`, `metrics`, `provider_health`, `model_call_traces`, `degraded`, and `warnings`.

## Validation

Before commit or release:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts\release_scan.py
Push-Location frontend
npm run build
Pop-Location
git diff --check
```

`scripts/release_scan.py` owns the public-source secret, retired-dependency, private-path,
version, and handoff-contract checks. Keep that single portable gate aligned with CI.
