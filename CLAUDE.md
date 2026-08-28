# CLAUDE.md - WEIPING_COUNCIL

## Session Start (mandatory)

On every session start:

1. Use active `agentmemory` recall for the current task when past context matters.
2. Read the smallest relevant project files for current truth, starting with `AGENTS.md`, `README.md`, and `.codex/skills/weiping-council/SKILL.md`.
3. Check `git status --short --branch` before editing.

Do not read, write, or depend on retired local mailbox/state files or the old repo-local markdown memory tree for active coordination. Durable cross-agent state belongs in `agentmemory`; public-safe stable knowledge belongs in the maintained wiki.

## Agent Identity

- **Name**: vc (Weiping Council)
- **Role**: Multi-LLM deliberation with protocols for council, debate, red-team, consensus, specialist, and tournament workflows.
- **Active memory**: `agentmemory` at `AGENTMEMORY_URL` (default `http://localhost:3111`)

## Multi-Agent Rules

- Follow this repository's `AGENTS.md` and project skill as the standalone source of
  truth. Do not require an operator-specific wiki checkout to work on this project.
- Save durable findings through agentmemory after significant work.
- Do not store secrets, API keys, private account state, or raw private documents in memory.
- For non-trivial tasks, use `.codex/skills/weiping-council/SKILL.md`. An external
  `AGENT_RESOURCE_ROOT` may be consulted only when the user explicitly configures it;
  it is never a startup or runtime dependency.

## Quick Start

```bash
git clone https://github.com/appleweiping/WEIPING_COUNCIL.git
cd WEIPING_COUNCIL
pip install -e .[dev]
copy .env.example .env
# Add provider API keys to .env. The app must not contain hard-coded credentials.

start.cmd
```

Manual startup:

```bash
uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev
python vc.py
```

## Runtime Contract

Weiping Council v2.4.1 is an honest-runtime app:

- Provider credentials are environment-only.
- Missing provider credentials are reported as degraded runtime state.
- `/api/health` reports provider readiness, agentmemory readiness, warnings, and version.
- Query results include metrics, provider health, model call traces, warnings, and a degraded flag.
- Named protocols execute exactly as selected. Cost-aware routing and decomposition run only when `auto` is selected, and the decision is stored in `routing`.
- Session artifacts use atomic replacement and corrupt artifacts are skipped by indexes rather than breaking the API.
- The CLI `/status` mirrors backend readiness instead of assuming the system is healthy.
- Saved handoff artifacts live at `data/sessions/<uuid>.json` and include redacted runtime evidence. Do not stage private saved sessions during general maintenance.

## Neighbor Boundaries

`WEIPING_WIKI` is the public route map and optional operating context, not a runtime dependency. `WEIPING_LAB` may consume Council session JSON artifacts, but Council must not require Lab workspace state, private `.env`, local DBs, caches, or active Lab services. Keep `AGENTS.md`, README, this file, and `.codex/skills/weiping-council/SKILL.md` aligned when behavior changes.

## Architecture

- `backend/runtime.py` - runtime settings, provider readiness, call traces.
- `backend/providers/router.py` - provider calls with explicit degraded behavior.
- `backend/council/orchestrator.py` - route, decompose, protocol, refine, metrics.
- `backend/memory/shared_memory.py` - active agentmemory context loader.
- `backend/protocols/` - six deliberation protocols.
- `frontend/` - React + Vite UI with runtime evidence display.
- `vc.py` - CLI tool.
