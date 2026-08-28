# Vipin Council v2.3 Honest Runtime Observability Implementation Plan

> **Status:** Implemented and verified for v2.3 under the former Vipin Council name. Future workers should treat this as the execution record for the release, then use `.codex/skills/weiping-council/SKILL.md` for the continuing maintenance and upgrade workflow.

**Goal:** Turn Vipin Council from a demo-like multi-model runner into an honest, inspectable runtime that refuses hidden credentials, reports degraded providers, records structured run metrics, and documents the current agentmemory-based operating model.

**Architecture:** Add typed runtime settings, provider routing, and trace primitives behind the existing protocol interfaces so protocols keep working while calls become auditable. Replace retired local coordination reads with optional agentmemory context loading and expose redacted health/readiness details through API and CLI. Add hermetic backend tests that use fake routers or explicit env maps so correctness does not require live LLM credentials.

**Tech Stack:** Python 3.11, FastAPI, httpx, pydantic, pytest, React/Vite.

---

### Task 1: Runtime Settings And Provider Safety

**Files:**
- Create: `backend/runtime.py`
- Modify: `backend/config.py`
- Modify: `backend/providers/router.py`
- Test: `tests/test_runtime_config.py`

- [x] **Step 1: Write failing tests**

Create `tests/test_runtime_config.py` with tests that:
- clear provider env vars and assert no hard-coded API key is available;
- set role-specific env vars and assert routing resolves model/base URL/API format from env;
- assert missing credentials produce a typed degraded provider result instead of a fake successful model answer.

Run: `python -m pytest tests/test_runtime_config.py -q`
Expected: FAIL because `backend.runtime` does not exist and router still embeds credentials.

- [x] **Step 2: Implement runtime settings**

Add `backend/runtime.py` with dataclasses for `ProviderEndpoint`, `ProviderStatus`, `ModelCallTrace`, and `RuntimeSettings`. Read:
- `VC_PROVIDER_<ROLE>_MODEL`
- `VC_PROVIDER_<ROLE>_BASE_URL`
- `VC_PROVIDER_<ROLE>_API_KEY`
- `VC_PROVIDER_<ROLE>_FORMAT`
- fallback `OPENROUTER_BASE_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`
- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`
- `AGENTMEMORY_URL`

Do not include any secret literal. Provider status must redact keys and report missing credentials.

- [x] **Step 3: Update router**

Modify `backend/providers/router.py` so provider configuration is environment-driven and council member identity stays separate from provider model identity. `ModelRouter.query()` should return explicit degraded text for unavailable providers and append a session-scoped `ModelCallTrace` with model, role, redacted provider_status, latency_ms, attempts, and error_kind.

- [x] **Step 4: Verify**

Run: `python -m pytest tests/test_runtime_config.py -q`
Expected: PASS.

### Task 2: Structured Session Metrics And Readiness API

**Files:**
- Modify: `backend/council/session.py`
- Modify: `backend/council/orchestrator.py`
- Modify: `backend/main.py`
- Test: `tests/test_session_observability.py`

- [x] **Step 1: Write failing tests**

Create tests that instantiate an `Orchestrator` with a fake router path and assert:
- every `SessionResult.to_dict()` includes `metrics`, `provider_health`, and `degraded`;
- routing/decomposition/refine durations are present when the orchestrator runs;
- `/api/health` reports version, configured models, provider readiness, agentmemory availability, and no secrets.

Run: `python -m pytest tests/test_session_observability.py -q`
Expected: FAIL because these fields/endpoints are absent.

- [x] **Step 2: Extend session model**

Add fields to `SessionResult`: `metrics: dict`, `provider_health: list[dict]`, `degraded: bool`, `warnings: list[str]`. Include them in `to_dict()`.

- [x] **Step 3: Instrument orchestrator**

Remove the duplicate v2.0 class from `backend/council/orchestrator.py`. Add monotonic timing around routing, decomposition, protocol, refine, and total runtime. Copy router traces/status into `SessionResult`.

- [x] **Step 4: Upgrade health API**

Add readiness helpers to `backend/main.py`: health should include `status`, `version`, `models`, `providers`, `agentmemory`, `warnings`, and `degraded`. Return `status: degraded` when any provider or agentmemory dependency is unavailable, while keeping raw endpoints and secrets out of the public payload.

- [x] **Step 5: Verify**

Run: `python -m pytest tests/test_session_observability.py -q`
Expected: PASS.

### Task 3: Agentmemory Context Loader And CLI Honesty

**Files:**
- Modify: `backend/memory/shared_memory.py`
- Modify: `vc.py`
- Modify: `CLAUDE.md`
- Test: `tests/test_agentmemory_context.py`

- [x] **Step 1: Write failing tests**

Create tests that monkeypatch agentmemory HTTP responses and assert:
- context is loaded from `/agentmemory/smart-search` or `/agentmemory/context` when available;
- unavailable agentmemory returns an empty context with a warning, not a crash;
- no code path references retired local coordination paths or the old memory index.

Run: `python -m pytest tests/test_agentmemory_context.py -q`
Expected: FAIL because current code reads retired local files.

- [x] **Step 2: Implement agentmemory loader**

Replace retired mailbox/local memory reads with `AgentMemoryClient` using `httpx` and short timeouts. Surface warnings and mark the affected session degraded when context recall is unavailable.

- [x] **Step 3: Update CLI startup/status**

Modify `vc.py` so header/status display provider readiness and agentmemory state. Remove mailbox mutation behavior. Keep commands `/projects` and `/context`, but make them report active agentmemory context.

- [x] **Step 4: Update project instructions**

Rewrite `CLAUDE.md` startup instructions to use active agentmemory and explicitly forbid Agent Hub/old markdown memory dependencies.

- [x] **Step 5: Verify**

Run: `python -m pytest tests/test_agentmemory_context.py -q`
Expected: PASS.

### Task 4: Frontend Trust Surface

**Files:**
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/ResultView.jsx`
- Modify: `frontend/src/components/ResultView.css`
- Test: frontend build

- [x] **Step 1: Add trust data display**

Display session `degraded`, `warnings`, provider health, and timing metrics in the result view. Keep the UI dense and operational; do not create a marketing hero.

- [x] **Step 2: Add API health awareness**

Fetch `/api/health` at app load and show a compact degraded/ready status near controls.

- [x] **Step 3: Verify**

Run: `npm run build` from `frontend`
Expected: PASS.

### Task 5: Documentation, Release Notes, And Full Gate

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `docs/releases/v2.3-honest-runtime-observability.md`
- Test: full verification

- [x] **Step 1: Update docs**

Document v2.3, env configuration, health/readiness semantics, no hard-coded credentials, agentmemory dependency, and degraded-mode behavior.

- [x] **Step 2: Version bump**

Bump package/app version to `2.3.0`. Ignore `*.egg-info/`.

- [x] **Step 3: Full verification**

Run:
- `python -m pytest -q`
- `python -m ruff check .`
- `npm run build` in `frontend`
- `python scripts/release_scan.py`

Expected: tests/build/lint pass; secret/retired-memory scan returns no unsafe hits except documented `.env.example` placeholders without real key material.

- [ ] **Step 4: Strict 10/10 review**

Ask a fresh reviewer to score security, honesty, usability, observability, maintainability, tests, docs, release readiness, project fit, and top-open-source trajectory. If any dimension is below 10/10, fix and re-run the review.
