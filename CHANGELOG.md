# Changelog

## 2.5.0

- `--demo` / `VC_DEMO=1`: canned replies instead of model calls, for trying the UI and
  CLI without a key.
- `vc serve` runs the API and the built UI on one port on any OS; `start.cmd` is gone.
- Council members are named after their roles (Architect, Reviewer, ...) rather than
  commercial model names.
- agentmemory recall is off unless `AGENTMEMORY_URL` is set.
- `eval/run_eval.py`: GSM8K comparison of one member against the protocols.

## 2.4

- Named protocols run exactly as selected; cost-aware routing only under `auto`, with
  the routing decision stored in each session.
- Retries only for transient provider errors; atomic session writes; `/api/live`,
  `/api/health` and `/api/ready`.

## 2.3

- Provider keys come only from the environment or the project `.env`.
- Per-call traces, provider readiness and a `degraded` flag in every result.
