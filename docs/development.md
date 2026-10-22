# Development notes

## Running with hot reload

`vc serve` runs the API and the built UI from `frontend/dist`. While working on
the UI, run the two halves separately instead:

```bash
uvicorn backend.main:app --reload --port 8000      # terminal 1
cd frontend && npm run dev                          # terminal 2, http://localhost:5173
```

Vite proxies `/api` to port 8000. Add `VC_DEMO=1` to the environment of the first
command to work without provider keys.

## Tests and checks

```bash
python -m pytest -q          # backend, CLI, demo mode, eval harness
python -m ruff check .
cd frontend && npm test && npm run build
```

Tests must not depend on keys in your shell or `.env`: build settings with
`RuntimeSettings.from_env(config, env={...})`, or pass an explicit `dotenv_path`
pointing at a temporary file. CI (`.github/workflows/ci.yml`) runs the same commands
on Ubuntu, plus the CLI encoding tests and a `--demo` query on Windows.

## Where things live

| Path | What it does |
| --- | --- |
| `backend/main.py` | FastAPI app: `/api/query`, health, sessions; serves `frontend/dist` |
| `backend/council/orchestrator.py` | runs a protocol (or `auto` routing), self-refine, metrics, warnings |
| `backend/protocols/` | council, debate, redteam, consensus, specialist, tournament |
| `backend/engine/` | auto routing, task decomposition, self-refine, tree-of-thoughts |
| `backend/providers/router.py` | provider calls, retries, per-call traces; demo replies |
| `backend/runtime.py` | reads `.env`/environment into provider endpoints; redaction helpers |
| `backend/demo.py` | canned replies for `--demo` |
| `backend/session_store.py` | atomic writes of `data/sessions/<id>.json` |
| `backend/memory/shared_memory.py` | optional agentmemory recall |
| `vc.py` | CLI: REPL, one-shot queries, `serve`, `sessions`, `show` |
| `eval/run_eval.py` | GSM8K comparison of one member vs protocols |

## Providers

Every role reads the shared `OPENROUTER_*` settings. Any of these can be overridden
per role with `VC_PROVIDER_<ROLE>_MODEL`, `_BASE_URL`, `_API_KEY` and `_FORMAT`, where
`<ROLE>` is `ARCHITECT`, `COORDINATOR`, `IMPLEMENTER`, `REVIEWER`, `SPEEDSTER` or
`BULK_WORKER`. A partial override only replaces the fields it sets. `_FORMAT` is
`openai` (chat completions) or `anthropic` (messages API). A non-empty
`DEEPSEEK_API_KEY` moves the bulk worker to DeepSeek's API.

Retries: HTTP 408, 409, 425, 429, 500, 502, 503 and 504, timeouts and transport
errors are retried with
exponential backoff (`VC_PROVIDER_MAX_ATTEMPTS`, `VC_PROVIDER_BACKOFF_*`); auth,
invalid-request and response-schema errors are not. A failed call returns a marker
such as `[Architect ERROR: provider call failed (rate_limit)]`, the trace records the
error class, and the session is flagged `degraded`.

Health output and saved sessions never contain base URLs or keys, only the source
(`OPENROUTER_*`, `VC_PROVIDER_ARCHITECT_*`, ...), the model id and which fields are
missing.

## Session files

Each query is saved as `data/sessions/<uuid>.json` (git-ignored) with these fields:
`id`, `query`, `protocol`, `created_at`, `stages`, `final_answer`, `confidence`,
`dissent`, `audit_trail`, `routing`, `metrics`, `provider_health`,
`model_call_traces`, `degraded`, `warnings`. Writes go through a temporary file and
an atomic rename; unreadable files are skipped when listing.

## Health endpoints

| Endpoint | Meaning |
| --- | --- |
| `GET /api/live` | the process is up |
| `GET /api/health` | providers, agentmemory and warnings; always 200 |
| `GET /api/ready` | same body, but 503 when anything is degraded |
| `GET /api/models`, `/api/protocols` | configured members and protocols |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| UI says the backend is not reachable | start `vc serve` (or uvicorn on port 8000) |
| `[Architect unavailable: missing provider configuration (api_key)]` | set `OPENROUTER_API_KEY` or the role's `VC_PROVIDER_*_API_KEY` |
| `provider call failed (schema_error)` | the endpoint does not speak the configured `_FORMAT` |
| a named protocol is slow or expensive | named protocols always run in full; use `auto` for cost-aware routing |
| CLI output breaks on a GBK console | fixed: unsupported glyphs are escaped instead of raising `UnicodeEncodeError` |
