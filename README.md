# WEIPING_COUNCIL

![WEIPING_COUNCIL banner](banner.png)

Honest multi-model deliberation for local and OpenAI-compatible runtimes.

WEIPING_COUNCIL is the repository identity for Weiping Council. It asks several configured council members to reason through a question, then preserves the route, model evidence, dissent, timings, warnings, and degraded runtime state. The goal is not to make a chatbot look more confident. The goal is to make deliberation inspectable enough that you can tell when it worked, when it was partial, and why.

Compatibility note: this project was previously published as Vipin Council (`vipin-council`). The legacy `vc.py` CLI and `vc` console script remain supported while the public repository identity moves to `WEIPING_COUNCIL`.

Agents maintaining this repository should read `AGENTS.md`, this README, `CLAUDE.md`, and `.codex/skills/weiping-council/SKILL.md` before non-trivial work.

## What Changed in v2.4.1

v2.4.1 is the release-hardening update for the v2.4 protocol runtime:

- every real protocol result now satisfies the persisted session schema, including
  structured council peer-review records;
- the browser and verbose CLI expose protocol-specific stage evidence instead of hiding
  debate, red-team, specialist, tournament, and council fields;
- default OpenRouter model IDs use provider-qualified slugs while an empty
  `OPENROUTER_MODEL` keeps the role-specific defaults;
- the public release guard covers common provider tokens, private credential files, and
  alternative frontend lockfiles that could override the audited npm lock.

## What Changed in v2.4

v2.4 is the protocol-fidelity and resilient-runtime release:

- named protocols now execute exactly as selected; smart routing can no longer silently
  replace `debate`, `redteam`, `consensus`, `specialist`, `tournament`, or `council`;
- the new `auto` mode owns cost-aware fast/standard/full-council routing and optional
  task decomposition;
- every result stores a separate, redacted `routing` record with the requested protocol,
  selected path, assigned members, reason, and difficulty;
- provider retries are bounded and error-aware: transient failures retry, while
  authentication, invalid-request, and schema failures stop immediately;
- recalled context is passed as untrusted user-level reference material instead of being
  appended to model system instructions;
- session JSON uses atomic replacement, malformed artifacts are skipped safely, request
  sizes are bounded, and liveness is separated from strict readiness.

v2.3 established the honest-runtime foundation that v2.4 retains:

- provider credentials are environment-only, loaded from the process environment or the
  exact project-root `.env` (parent directories are never searched);
- council member identity is separate from provider model identity, so six roles no longer collapse into one map key;
- each query gets session-scoped model traces, including concurrent requests;
- `/api/health`, CLI status, and the React UI expose redacted readiness instead of raw provider endpoints;
- missing provider config, provider errors, and unavailable agentmemory recall are explicit degraded states;
- default CORS is local-first through `VC_CORS_ORIGINS`, not wildcard;
- the project includes a Codex skill at `.codex/skills/weiping-council/SKILL.md` for future reproduction, maintenance, monitoring, releases, and upgrade passes.

## Why It Exists

Single-model answers often hide the uncertainty that matters most. Weiping Council gives you several structured ways to ask for disagreement, review, synthesis, and verification:

| Protocol | Best For | Shape |
| --- | --- | --- |
| `auto` | cost-aware general use | inspectable routing to one model, decomposition, or council |
| `council` | open-ended questions, research, design review | first opinions, peer review, chairman synthesis |
| `debate` | trade-offs and contentious choices | pro, con, rebuttal, judge verdict |
| `redteam` | finding weaknesses | defenders, attacker critique, improved answer |
| `consensus` | alignment and policy choices | repeated rounds until enough members agree |
| `specialist` | domain routing | classify, specialist answer, verifier checks |
| `tournament` | choosing the strongest answer | bracketed comparisons and winner |

## Architecture

```text
React UI / vc CLI / REST API
        |
FastAPI backend
        |
Orchestrator
  - optional agentmemory context recall
  - smart routing
  - task decomposition
  - protocol execution
  - self-refine
  - metrics, warnings, degraded state
        |
ModelRouter
  - OpenAI-compatible or Anthropic-format providers
  - per-session model call traces
  - redacted provider readiness
```

Core files:

- `backend/runtime.py` - `.env`/environment loading, provider readiness, CORS origins, trace dataclasses.
- `backend/providers/router.py` - provider calls, retry/degraded handling, context-local trace collection.
- `backend/council/orchestrator.py` - run pipeline, timings, context recall, degraded semantics.
- `backend/main.py` - FastAPI API, health, models, session persistence.
- `backend/session_store.py` - atomic session writes and corruption-tolerant indexes.
- `vc.py` - terminal interface.
- `frontend/src/components/ResultView.jsx` - runtime evidence in the UI.

## Installation

Prerequisites:

- Python 3.11+
- Node.js 22.18+
- an OpenAI-compatible provider key such as OpenRouter, or role-specific provider credentials

```powershell
git clone https://github.com/appleweiping/WEIPING_COUNCIL.git
cd WEIPING_COUNCIL

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2.1" "setuptools>=84.0.0"
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

copy .env.example .env
# edit .env and add provider keys

cd frontend
npm ci
cd ..
```

Run everything:

```powershell
start.cmd
```

`start.cmd` resolves every path from the checkout, uses the project's `.venv`, and fails
with installation guidance when the virtual environment, npm, or `frontend/node_modules`
is missing. Set `VC_START_DRY_RUN=1` to inspect the resolved commands without copying
`.env` or opening terminal windows.

Manual run:

```powershell
# terminal 1
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000

# terminal 2
cd frontend
npm run dev

# terminal 3
.\.venv\Scripts\python.exe vc.py
```

The CLI keeps the active terminal encoding and escapes only glyphs that encoding cannot
represent. This prevents `UnicodeEncodeError` crashes on legacy Windows code pages such as
GBK while preserving full Unicode output in UTF-8 terminals. Model, session, health, and
memory text is stripped of ANSI/OSC and unsafe control characters before terminal rendering.

## Configuration

Minimal `.env`:

```bash
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=
OPENROUTER_API_FORMAT=openai

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_API_FORMAT=openai

AGENTMEMORY_URL=http://localhost:3111
VC_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

VC_PROVIDER_TIMEOUT_SECONDS=120
VC_PROVIDER_MAX_ATTEMPTS=3
VC_PROVIDER_BACKOFF_BASE_SECONDS=0.5
VC_PROVIDER_BACKOFF_MAX_SECONDS=8
VC_PROVIDER_MAX_CONCURRENCY=8
```

Only `OPENROUTER_API_KEY` is required for the default six-role council. The bulk-worker
inherits the shared OpenRouter endpoint unless a non-empty `DEEPSEEK_API_KEY` enables the
optional DeepSeek override. A partial `VC_PROVIDER_<ROLE>_*` block overrides only its
non-empty fields and inherits the remaining shared endpoint fields.

Per-role overrides use this pattern:

```bash
VC_PROVIDER_ARCHITECT_MODEL=claude-opus-4-7
VC_PROVIDER_ARCHITECT_BASE_URL=http://127.0.0.1:8990/v1
VC_PROVIDER_ARCHITECT_API_KEY=
VC_PROVIDER_ARCHITECT_FORMAT=anthropic
```

Replace `ARCHITECT` with `COORDINATOR`, `IMPLEMENTER`, `REVIEWER`, `SPEEDSTER`, or `BULK_WORKER` for other council roles.

Public health and session evidence intentionally do not expose raw provider URLs or API keys. They expose only source labels, configured/missing fields, provider model names, attempts, latency, and error classes.

Named protocols are authoritative. Choose `auto` only when you want the runtime to select
a single-model, decomposition, or full-council path based on query complexity.
Set `AGENTMEMORY_URL=` explicitly to disable optional recall; a disabled memory service is
reported as not configured and does not by itself degrade a run.

## Relationship to Neighbor Projects

`WEIPING_COUNCIL`, `deepseek-cli`, `WEIPING_LAB`, `WEIPING_WIKI`, `AGENT_RESOURCE`, and `AGENTIC_SCIENCE` should complement each other without becoming tightly coupled:

- `WEIPING_COUNCIL` is the deliberation runtime. It owns protocols, routing evidence, degraded-state semantics, saved session JSON, and the React/CLI interface for council-style reasoning.
- `deepseek-cli` is a terminal-first DeepSeek client. It can provide a convenient way to test DeepSeek credentials and workflows, but Weiping Council must remain provider-agnostic through OpenAI-compatible and per-role provider settings.
- `WEIPING_LAB` is the broader lab/workbench layer. It can consume Weiping Council session artifacts, but lab-specific state should not be required to run this repository.
- `WEIPING_WIKI` is the public route map and durable operating context, not a runtime dependency.
- `AGENT_RESOURCE` provides shared skills and workflow references; do not copy its caches, local clones, or private notes into this repo.
- `AGENTIC_SCIENCE` provides optional audit methods such as UUPF for workflow upgrades. Generated UUPF reports are planning evidence only and must stay in ignored work areas unless deliberately released.

Historical compatibility: older local checkouts, session artifacts, or notes may still mention `vipin-council`, `vipin-lab`, or Vipin Council. Treat those names as legacy aliases unless a document explicitly describes historical release context.

The only shared memory dependency in this repo is optional `agentmemory` recall via
`AGENTMEMORY_URL`. When the service requires authentication, set `AGENTMEMORY_SECRET`;
the credential is sent as Bearer auth only to HTTPS or loopback URLs and is never
included in public health/session output. Anonymous agentmemory instances remain supported.

## What Good Looks Like

After setup:

```powershell
.\.venv\Scripts\python.exe vc.py status
```

Healthy output means:

- backend reachable;
- at least the configured providers are ready;
- agentmemory is reachable if `AGENTMEMORY_URL` is set;
- `status` is `ok`.

Degraded output is still useful. It means the backend is alive but one subsystem is partial. Common examples:

- no provider key: queries return explicit unavailable text rather than fake model answers;
- agentmemory down: answers run without recalled context and mark the session degraded;
- provider schema or HTTP failure: the answer includes a provider failure marker and the trace stores the error class.

## REST API

Submit a query:

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What architecture should I use for this feature?", "protocol": "council"}'
```

Response shape:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "query": "What architecture should I use for this feature?",
  "protocol": "council",
  "created_at": "2026-06-01T12:00:00",
  "stages": [],
  "final_answer": "...",
  "confidence": 0.82,
  "dissent": [],
  "audit_trail": [],
  "routing": {
    "mode": "explicit",
    "requested_protocol": "council",
    "selected_protocol": "council",
    "tier": "protocol",
    "assigned_models": ["architect", "coordinator"],
    "reason": "Explicit protocol selection is authoritative."
  },
  "metrics": {"protocol_ms": 2200.1, "total_ms": 2314.8},
  "provider_health": [
    {
      "role": "architect",
      "name": "Opus",
      "model_id": "openai/gpt-5.5",
      "endpoint_configured": true,
      "ready": true,
      "has_api_key": true,
      "missing": []
    }
  ],
  "model_call_traces": [
    {
      "role": "architect",
      "model_name": "Opus",
      "model_id": "openai/gpt-5.5",
      "attempts": 1,
      "latency_ms": 850.0,
      "error_kind": null,
      "status_code": 200,
      "retry_delay_ms": 0.0,
      "retry_reasons": []
    }
  ],
  "degraded": false,
  "warnings": []
}
```

Other endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/live` | process liveness only |
| `GET` | `/api/health` | redacted backend, provider, and memory readiness |
| `GET` | `/api/ready` | strict readiness; returns 503 when dependencies are degraded |
| `GET` | `/api/models` | council member IDs, roles, and provider model names |
| `GET` | `/api/protocols` | available protocol list |
| `GET` | `/api/sessions` | recent saved sessions |
| `GET` | `/api/sessions/{id}` | saved session JSON |

## Session Artifact Contract

Saved council handoffs live under `data/sessions/<uuid>.json`. The directory is runtime state and should stay out of maintenance commits unless the user explicitly asks to curate a public example.

Each saved session JSON should preserve:

- `id`, `query`, `protocol`, and `created_at`
- `stages`, `final_answer`, `confidence`, `dissent`, and `audit_trail`
- `routing` with the requested protocol and selected execution path
- `metrics` with timing fields
- `provider_health` with redacted readiness only
- `model_call_traces` with role, model name/id, attempts, latency, and error class
- `degraded` and `warnings`

Lab and wiki workflows may point to these files as artifacts, but they should not require Council's `.env`, active backend, frontend build output, local caches, or private provider logs.

## Monitoring

Use four levels, inspired by current open-source AI runtime practice:

1. Basic process check:
   ```bash
   curl http://localhost:8000/api/live
   ```
   The backend process is reachable if this returns `status: ok`.

2. Diagnostic and strict readiness checks:
   ```bash
   curl http://localhost:8000/api/health
   curl --fail http://localhost:8000/api/ready
   ```
   `/api/health` always returns the diagnostic snapshot. `/api/ready` returns 503 when
   that snapshot is degraded.

3. Configuration check:
   ```bash
   curl http://localhost:8000/api/models
   ```
   Confirm member IDs and provider models are what you expect.

4. End-to-end check:
   ```bash
   curl -X POST http://localhost:8000/api/query \
     -H "Content-Type: application/json" \
     -d '{"query": "Respond with the word HEALTHY and explain one risk.", "protocol": "council"}'
   ```
Treat this as passing only when `degraded` is false and at least one trace has `error_kind: null`.

## Troubleshooting

| Symptom | Meaning | Fix |
| --- | --- | --- |
| `Backend not reachable` in the UI | Vite can load, but FastAPI is not responding | Start `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000` |
| `/api/health` returns `status: degraded` | Backend is alive, but a provider or memory dependency is incomplete | Inspect `warnings`, `providers[].missing`, and `agentmemory.status` |
| `/api/ready` returns 503 while `/api/live` returns 200 | The process is alive but dependencies are incomplete | Use `/api/health` for the redacted diagnostic snapshot |
| A named protocol appears expensive | Named protocols deliberately preserve their full workflow | Select `auto` when cost-aware routing is desired |
| Query returns `[Name unavailable: missing provider configuration (...)]` | The selected role has no usable provider endpoint or key | Fill `.env` or the relevant `VC_PROVIDER_<ROLE>_*` variables |
| Query returns `provider call failed (schema_error)` | Provider responded, but not in the expected schema | Check `*_API_FORMAT`, provider compatibility, and provider logs |
| CLI status is degraded but UI works | This is a partial runtime, not downtime | Use the Runtime Evidence panel to see which dependency is partial |
| Tests try to use real keys | A test is not hermetic | Prefer `RuntimeSettings.from_env(config, env={})` or pass an explicit temporary `dotenv_path` in the test |

## Development Gate

The repository includes `.github/workflows/ci.yml` with the same backend test, backend lint, frontend build, and secret/retired-path scan used locally.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts\release_scan.py
cd frontend
npm run build
npm audit --audit-level=low --registry=https://registry.npmjs.org
cd ..
```

On Windows, `powershell -ExecutionPolicy Bypass -File scripts\verify.ps1` runs the same local gate. The final scan should return no real source secrets, retired active-coordination dependencies, mirror registry lockfiles, or version drift.

Python follows a library-style, latest-compatible-resolution CI policy: its declared minimum
ranges are intentionally not an immutable lock. The frontend is reproducibly locked with
lockfile v3, official-registry URLs, and SHA-512 integrity pins.

## Design References

This project does not vendor code from these systems. v2.4 uses original implementation
inspired by compatible architectural patterns from their official repositories:

- LangGraph separates workflow state from checkpoint persistence and documents explicit
  durability modes; Council applies that idea through an atomic session-store boundary.
- OpenAI Agents SDK separates run traces from nested spans using context-local state;
  Council keeps route evidence separate from provider-call traces.
- Microsoft AutoGen uses explicit team participants and bounded termination controls;
  Council treats named protocol selection as authoritative and keeps `auto` opt-in.
- LiteLLM distinguishes retryable routing failures from permanent failures; Council uses
  bounded status-aware retries without importing LiteLLM or its code.
- Open WebUI separates process health and dependency readiness; Council exposes
  `/api/live`, diagnostic `/api/health`, and strict `/api/ready`.

Useful source files:

- [LangGraph checkpointer documentation](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/checkpointers.mdx)
- [OpenAI Agents SDK tracing documentation](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md)
- [Microsoft AutoGen selector group chat](https://github.com/microsoft/autogen/blob/main/python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_selector_group_chat.py)
- [Open WebUI `main.py`](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/main.py)
- [LiteLLM `router.py`](https://github.com/BerriAI/litellm/blob/main/litellm/router.py)

## Release Notes

See:

- [`docs/releases/v2.4.1-release-hardening.md`](docs/releases/v2.4.1-release-hardening.md)
- [`docs/releases/v2.4-protocol-fidelity-resilience.md`](docs/releases/v2.4-protocol-fidelity-resilience.md)
- [`docs/releases/2026-06-04-weiping-council-uupf-upgrade.md`](docs/releases/2026-06-04-weiping-council-uupf-upgrade.md)
- [`docs/releases/v2.3-honest-runtime-observability.md`](docs/releases/v2.3-honest-runtime-observability.md)

## License

MIT
