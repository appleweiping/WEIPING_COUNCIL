# WEIPING_COUNCIL v2.4 Protocol Fidelity and Resilience Plan

Date: 2026-08-23

## Problem

The v2.3 router can replace an explicitly selected protocol with a single-model or
task decomposition path. A user who selects `debate`, `redteam`, or another named
protocol therefore cannot rely on that protocol being executed. Session files also use
non-atomic writes, malformed artifacts can break listing, provider retry behavior treats
schema/authentication failures like transient failures, and the public request contract
does not bound query/context size.

## Release Goal

Ship v2.4 as a protocol-fidelity and resilient-runtime release:

- named protocols always execute exactly as selected;
- a new `auto` mode owns cost-aware routing and optional decomposition;
- every result records a redacted, structured routing decision separately from the
  requested protocol;
- provider retries are bounded, status-aware, jittered, and observable without exposing
  response bodies, endpoints, or credentials;
- session artifacts are written atomically and malformed artifacts cannot break the
  session index;
- API inputs are normalized and bounded;
- CLI and UI expose route evidence and the `auto` choice honestly.

## Design References

No upstream source will be vendored or copied. The implementation is original and uses
only compatible architectural ideas from:

- LangGraph checkpointers: explicit durability modes and checkpoint interfaces motivate
  a small atomic `SessionStore` boundary rather than route-level file writes.
- OpenAI Agents SDK tracing: run-scoped context variables and trace/span separation
  motivate keeping routing evidence distinct from provider-call traces.
- Microsoft AutoGen / Agent Framework: explicit team selection, termination bounds, and
  cancellation-aware workflows motivate protocol fidelity and bounded execution.
- LiteLLM Router: error-class-aware retry/cooldown concepts motivate retrying only
  transient transport/status failures.
- Open WebUI: distinct availability/readiness semantics motivate preserving degraded as
  a usable runtime state.

## Implementation

1. Add `routing` to the session artifact and API response contract.
2. Refactor `Orchestrator.run` into explicit-protocol and `auto` paths.
3. Add safe auto-route audit records without pseudo-protocol names.
4. Add bounded provider policy settings and trace fields for final HTTP status/retry
   timing while keeping public evidence redacted.
5. Add an atomic, corruption-tolerant session repository and use it from API and CLI.
6. Add Pydantic request limits, update frontend/CLI/docs/configuration, and bump all
   package versions to 2.4.0.

## Verification

- Hermetic tests for explicit protocol fidelity, auto routing, trace isolation, transient
  vs permanent retry behavior, request validation, atomic storage, malformed artifacts,
  secret redaction, and version drift.
- Ruff, release scan, frontend production build, secret/retired-path scan, and
  `git diff --check`.
- Browser smoke verification of protocol selection and route/runtime evidence when local
  frontend startup is useful and dependencies are available.
