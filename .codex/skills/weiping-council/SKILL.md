---
name: weiping-council
description: Use this skill for reproducing, maintaining, monitoring, releasing, or upgrading the WEIPING_COUNCIL project. It enforces the full lifecycle path from planning through design, development, testing, release, maintenance, monitoring, and continuous upgrade against real open-source quality bars.
---

# WEIPING_COUNCIL Project Skill

Use this skill whenever work touches `WEIPING_COUNCIL` behavior, configuration, docs, release process, tests, UI, CLI, provider routing, memory integration, or project quality. Legacy references to `vipin-council` or Vipin Council are compatibility aliases unless the surrounding text is historical release context.

## Mission

Weiping Council is an honest multi-model deliberation runtime. It must be useful when fully configured and truthful when degraded. It must never fake model success, hide provider assumptions, leak credentials, expose private endpoints in public health surfaces, or depend on retired local coordination paths.

## Lifecycle Workflow

1. Plan
   - Read `AGENTS.md`, `README.md`, `CLAUDE.md`, `pyproject.toml`, `backend/config.py`, `backend/runtime.py`, and the latest file under `docs/releases/`.
   - Define a version-level change. Do not spend a release on small isolated fixes.
   - Write or update a plan under `docs/superpowers/plans/` before broad changes.

2. Design
   - Keep provider identity separate from council member identity.
   - Prefer OpenAI-compatible provider support by default, with Anthropic format as an explicit per-role option.
   - Health and runtime evidence may expose readiness, source labels, missing field names, attempts, latency, and error classes. They must not expose API keys, raw provider URLs, local private endpoints, prompts from private memory, or raw exception messages containing secrets.
   - Treat `agentmemory` as optional but observable. If recall is unavailable for a run, the run is degraded.
   - CORS must be explicit and local-first by default, never wildcard by default.
   - Keep cross-project links low-coupling: route maps, optional context variables, validation commands, and artifact formats are acceptable; private `.env` files, local DBs, caches, generated reports, and active services are not.

3. Develop
   - Backend source of truth:
     - `backend/runtime.py` for env and `.env` loading, provider readiness, CORS origins, and trace primitives.
     - `backend/providers/router.py` for provider calls and per-run traces.
     - `backend/council/orchestrator.py` for routing, context injection, protocol execution, refinement, metrics, warnings, and degraded state.
     - `backend/session_store.py` for atomic session persistence and corruption-tolerant reads.
     - `backend/main.py` for FastAPI contracts.
   - CLI source of truth: `vc.py`.
   - UI source of truth: `frontend/src/components/ChatPane.jsx` and `frontend/src/components/ResultView.jsx`.
   - Use `.env.example` for safe examples only. Never place real-looking `sk-...` values in source or docs.

4. Test
   - Tests must be hermetic. Use explicit `env={}` or an explicit temporary `dotenv_path`; never let ambient machine credentials decide test results. Runtime loading must never search parent directories for another project's `.env`.
   - Cover missing credentials, transient and permanent provider failures, redaction, agentmemory unavailable behavior, explicit protocol fidelity, auto routing, atomic session storage, malformed artifacts, unique member IDs, per-session traces, concurrent session isolation, CLI status formatting, and frontend build.
   - Required local gate:
     ```powershell
     .\.venv\Scripts\python.exe -m pytest -q
     .\.venv\Scripts\python.exe -m ruff check .
     .\.venv\Scripts\python.exe scripts\release_scan.py
     Push-Location frontend
     npm run build
     npm audit --audit-level=low --registry=https://registry.npmjs.org
     Pop-Location
     ```
   - The release scan must return no real secrets, operator-specific private paths, or
     retired active-coordination dependencies.

5. Release
   - Bump `APP_VERSION`, `pyproject.toml`, and `frontend/package*.json` together.
   - Add release notes under `docs/releases/`.
   - Update `README.md` with current configuration, health semantics, verification, monitoring, and troubleshooting.
   - Keep `LICENSE` and `.github/workflows/ci.yml` aligned with the local gate.
   - Commit and push the project repo after a passing gate and review score of 10/10.

6. Maintain
   - Keep docs, `.env.example`, tests, and UI aligned with actual runtime behavior.
   - Remove compatibility shims when they become misleading.
   - Protect existing user changes and generated local files. Do not stage `.venv`, `node_modules`, `dist`, session data, or egg-info artifacts.

7. Monitor
   - Level 1: `GET /api/health` returns backend availability plus redacted provider and agentmemory readiness.
   - Level 2: `GET /api/models` confirms member identity and configured provider model names.
   - Level 3: a deterministic `/api/query` smoke prompt validates routing, provider call, trace capture, and persisted session JSON.
   - Degraded is a real state, not a connection failure.
   - If `/api/query` returns `fast_path` or `standard_path`, that is a routing decision and must be reflected honestly in the API response and saved session JSON.

8. Upgrade Iteration
   - Before major upgrades, compare current behavior with active open-source agent/runtime projects such as CrewAI, LangGraph, Open WebUI, LiteLLM, AutoGen/Microsoft Agent Framework, and OpenAI-compatible UI/proxy projects.
   - Import patterns only when they fit this project: provider abstraction, monitoring clarity, real examples, reproducible install, plugin surfaces, telemetry transparency, or safer local defaults.
   - Prefer original modules that make Weiping Council better at deliberation honesty: per-call evidence, dissent preservation, reviewer scoring, protocol traces, and reproducible quality gates.

## Neighbor Project Boundaries

- `deepseek-cli` is a terminal-first DeepSeek client and may be used as an optional provider source, but Weiping Council must work with any OpenAI-compatible provider.
- `WEIPING_LAB` is the broader workbench/lab layer. Weiping Council can export inspectable session JSON for it, but should not import lab-specific state into the core runtime.
- `WEIPING_WIKI` is the public route map and durable operating context, not a runtime dependency.
- Council handoff artifacts are `data/sessions/<uuid>.json` files with `id`, `query`, `protocol`, `created_at`, `stages`, `final_answer`, `confidence`, `dissent`, `audit_trail`, `routing`, `metrics`, `provider_health`, `model_call_traces`, `degraded`, and `warnings`.
- Shared memory is `agentmemory`; do not revive retired local mailbox or markdown memory dependencies.

## Review Gate

After a complete version-level batch is implemented and locally verified, use independent review agents for strict scoring. Required dimensions:

- honesty and safety
- architecture and concurrency
- provider compatibility and degraded behavior
- CLI/UI usability
- documentation and onboarding
- tests and release reproducibility
- monitoring and maintenance story
- relationship to `deepseek-cli` and `WEIPING_LAB`

Do not request a score while still actively editing the batch. If any reviewer returns less than 10/10, treat every blocker as mandatory and iterate.
