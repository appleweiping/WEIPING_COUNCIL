"""Weiping Council orchestrator with honest runtime observability."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable

from ..config import CouncilConfig
from ..council.session import Session, SessionResult
from ..protocols.council_protocol import CouncilProtocol
from ..protocols.debate_protocol import DebateProtocol
from ..protocols.redteam_protocol import RedTeamProtocol
from ..protocols.consensus_protocol import ConsensusProtocol
from ..protocols.specialist_protocol import SpecialistProtocol
from ..protocols.tournament_protocol import TournamentProtocol
from ..providers.router import ModelRouter
from ..providers.router import is_provider_error_result
from ..engine.smart_router import SmartRouter, RoutingDecision
from ..engine.self_refine import SelfRefineEngine
from ..engine.tree_of_thoughts import TreeOfThoughts
from ..engine.task_decomposer import TaskDecomposer
from ..memory.shared_memory import AgentMemoryClient, load_shared_memory, SharedMemoryContext


class Orchestrator:
    """Coordinate routing, protocols, refinement, and run-level observability."""

    def __init__(self, config: CouncilConfig, router: ModelRouter | None = None):
        self.config = config
        self.router = router or ModelRouter(config)
        self.smart_router = SmartRouter(config, self.router)
        self.refiner = SelfRefineEngine(self.router, max_iterations=3, quality_threshold=8.0)
        self.tot = TreeOfThoughts(config, self.router, beam_width=5, max_depth=3, vote_samples=3)
        self.decomposer = TaskDecomposer(config, self.router)

        self.protocols = {
            "council": CouncilProtocol(config, self.router),
            "debate": DebateProtocol(config, self.router),
            "redteam": RedTeamProtocol(config, self.router),
            "consensus": ConsensusProtocol(config, self.router),
            "specialist": SpecialistProtocol(config, self.router),
            "tournament": TournamentProtocol(config, self.router),
        }

    def _time(self, metrics: dict, name: str, started: float) -> None:
        metrics[name] = round((time.perf_counter() - started) * 1000, 2)

    async def _timed(self, metrics: dict, name: str, fn: Callable):
        started = time.perf_counter()
        value = await fn()
        self._time(metrics, name, started)
        return value

    def _get_shared_context(self) -> SharedMemoryContext:
        settings = getattr(self.router, "settings", None)
        if settings is None:
            return load_shared_memory()
        return load_shared_memory(
            client=AgentMemoryClient(
                base_url=settings.agentmemory_url,
                secret=settings.agentmemory_secret,
            ),
        )

    async def _inject_context(
        self,
        session: Session,
        metrics: dict,
        warnings: list[str],
    ) -> None:
        started = time.perf_counter()
        shared = await asyncio.to_thread(self._get_shared_context)
        context_block = shared.as_context_block()
        if context_block and not session.context:
            session.context = context_block
        elif context_block and session.context:
            session.context = f"{context_block}\n\n{session.context}"
        warnings.extend(shared.warnings)
        self._time(metrics, "context_ms", started)

    def _attach_observability(
        self,
        result: SessionResult,
        metrics: dict,
        warnings: list[str],
        total_started: float,
    ) -> SessionResult:
        protocol_degraded = bool(result.degraded)
        warnings.extend(result.warnings)
        metrics["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
        provider_health = (
            self.router.provider_health() if hasattr(self.router, "provider_health") else []
        )
        traces = [
            trace.to_dict() if hasattr(trace, "to_dict") else trace
            for trace in (
                self.router.current_traces()
                if hasattr(self.router, "current_traces")
                else getattr(self.router, "traces", [])
            )
        ]

        provider_degraded = any(not item.get("ready", False) for item in provider_health)
        trace_degraded = any(trace.get("error_kind") for trace in traces)
        successful_calls = sum(not trace.get("error_kind") for trace in traces)
        failed_calls = len(traces) - successful_calls
        context_degraded = any(
            "agentmemory" in warning.lower() or "context" in warning.lower() for warning in warnings
        )
        try:
            confidence = float(result.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence_degraded = not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0
        if not math.isfinite(confidence):
            confidence = 0.0
        result.confidence = max(0.0, min(1.0, confidence))
        if provider_degraded:
            warnings.append("One or more providers are not ready; check environment configuration.")
        if trace_degraded:
            warnings.append("One or more model calls returned an error or degraded response.")
        if context_degraded:
            warnings.append("Context recall is unavailable or degraded for this run.")
        if confidence_degraded:
            warnings.append("Model-reported confidence was invalid and has been clamped.")
        if getattr(getattr(self.router, "settings", None), "demo", False):
            warnings.append("Demo mode: replies are canned and no model was called.")

        result.metrics = metrics
        result.metrics["successful_model_calls"] = successful_calls
        result.metrics["failed_model_calls"] = failed_calls
        result.provider_health = provider_health
        result.model_call_traces = traces
        result.degraded = (
            protocol_degraded
            or provider_degraded
            or trace_degraded
            or context_degraded
            or confidence_degraded
        )
        if traces and trace_degraded:
            result.confidence = min(result.confidence, successful_calls / len(traces))
        result.warnings = sorted(set(warnings))
        return result

    async def run(self, session: Session) -> SessionResult:
        """Run an explicit protocol faithfully, or route only when `auto` is selected."""
        total_started = time.perf_counter()
        metrics: dict = {}
        warnings: list[str] = []
        trace_token = (
            self.router.start_trace_scope() if hasattr(self.router, "start_trace_scope") else None
        )
        try:
            await self._inject_context(session, metrics, warnings)
            if session.protocol == "auto":
                result = await self._run_auto(session, metrics)
            else:
                protocol = self.protocols.get(session.protocol)
                if protocol is None:
                    raise ValueError(f"Unknown protocol: {session.protocol}")
                result = await self._timed(
                    metrics,
                    "protocol_ms",
                    lambda: protocol.execute(session),
                )
                await self._refine_result(session, result, metrics)
                observed_roles = {
                    trace.role if hasattr(trace, "role") else trace.get("role")
                    for trace in self.router.current_traces()
                }
                assigned_models = [
                    model.id for model in self.config.models if model.role in observed_roles
                ]
                result.routing = {
                    "mode": "explicit",
                    "requested_protocol": session.protocol,
                    "selected_protocol": session.protocol,
                    "tier": "protocol",
                    "assigned_models": assigned_models,
                    "reason": "Explicit protocol selection is authoritative.",
                }
                result.audit_trail.insert(0, {"step": "routing", **result.routing})
            return self._attach_observability(result, metrics, warnings, total_started)
        finally:
            if trace_token is not None and hasattr(self.router, "finish_trace_scope"):
                self.router.finish_trace_scope(trace_token)

    async def _run_auto(self, session: Session, metrics: dict) -> SessionResult:
        routing = await self._timed(
            metrics,
            "routing_ms",
            lambda: self.smart_router.classify(session.query),
        )
        route_evidence = {
            "mode": "auto",
            "requested_protocol": "auto",
            "selected_protocol": "single_model" if routing.tier != "full_council" else "council",
            "tier": routing.tier,
            "difficulty": round(routing.difficulty, 3),
            "assigned_models": list(routing.assigned_models),
            "reason": routing.reason,
            "decomposed": False,
        }

        if routing.tier in {"fast", "standard"}:
            result = await self._timed(
                metrics,
                f"{routing.tier}_path_ms",
                lambda: self._single_model_path(session, routing),
            )
            result.routing = route_evidence
            result.audit_trail.insert(0, {"step": "routing", **route_evidence})
            return result

        decomposition = await self._timed(
            metrics,
            "decomposition_ms",
            lambda: self.decomposer.process(
                session.query,
                routing.difficulty,
                context=session.context or "",
            ),
        )

        if decomposition.was_decomposed:
            route_evidence["selected_protocol"] = "decomposition"
            route_evidence["decomposed"] = True
            route_evidence["assigned_models"] = list(
                dict.fromkeys(task.assigned_to for task in decomposition.subtasks)
            )
            result = SessionResult(
                id=session.id,
                query=session.query,
                protocol="auto",
                created_at=session.created_at,
                routing=route_evidence,
            )
            result.stages.append(
                {
                    "name": "Task Decomposition",
                    "subtasks": [
                        {
                            "desc": task.description,
                            "model": task.assigned_to,
                            "status": task.status,
                            "result": task.result[:200],
                        }
                        for task in decomposition.subtasks
                    ],
                }
            )
            result.final_answer = decomposition.synthesis
            failed_tasks = sum(task.status != "done" for task in decomposition.subtasks)
            synthesis_failed = is_provider_error_result(decomposition.synthesis)
            if failed_tasks or synthesis_failed:
                result.degraded = True
                result.warnings.append(
                    "Task decomposition completed with failed sub-tasks or synthesis."
                )
            successful_ratio = (
                (len(decomposition.subtasks) - failed_tasks) / len(decomposition.subtasks)
                if decomposition.subtasks
                else 0.0
            )
            result.confidence = 0.0 if synthesis_failed else 0.8 * successful_ratio
            result.audit_trail.extend(
                [
                    {"step": "routing", **route_evidence},
                    {"step": "decompose", "subtask_count": len(decomposition.subtasks)},
                ]
            )
            await self._refine_result(session, result, metrics)
            return result

        result = await self._timed(
            metrics,
            "protocol_ms",
            lambda: self.protocols["council"].execute(session),
        )
        result.protocol = "auto"
        result.routing = route_evidence
        result.audit_trail.insert(0, {"step": "routing", **route_evidence})
        await self._refine_result(session, result, metrics)
        return result

    async def _refine_result(self, session: Session, result: SessionResult, metrics: dict) -> None:
        if result.degraded or result.confidence >= 0.85 or not result.final_answer:
            return

        async def do_refine():
            architect = next(
                (model for model in self.config.models if model.role == "architect"),
                self.config.models[0],
            )
            critic = next(
                (model for model in self.config.models if model.role == "reviewer"),
                self.config.models[0],
            )
            return await self.refiner.refine(
                architect,
                critic,
                session.query,
                result.final_answer,
                context=session.context or "",
            )

        refined = await self._timed(metrics, "refine_ms", do_refine)
        if refined.iterations > 0 and refined.scores and refined.scores[-1] > 7.0:
            result.final_answer = refined.final
            result.stages.append(
                {
                    "name": "Self-Refine",
                    "iterations": refined.iterations,
                    "converged": refined.converged,
                    "scores": refined.scores,
                }
            )
            result.audit_trail.append(
                {
                    "step": "post_refine",
                    "iterations": refined.iterations,
                    "final_score": refined.scores[-1],
                }
            )
            result.confidence = min(0.95, result.confidence + 0.1)

    async def _single_model_path(
        self,
        session: Session,
        routing: RoutingDecision,
    ) -> SessionResult:
        """Handle routed single-model queries without running a full protocol."""
        model = next(
            (
                candidate
                for candidate in self.config.models
                if candidate.id == routing.assigned_models[0]
            ),
            self.config.models[-1],
        )
        response = await self.router.query(
            model,
            [{"role": "user", "content": session.query}],
            context=session.context or "",
        )

        result = SessionResult(
            id=session.id,
            query=session.query,
            protocol="auto",
            created_at=session.created_at,
        )
        result.final_answer = response
        result.confidence = 0.6 if routing.tier == "fast" else 0.7
        result.stages.append(
            {
                "name": "Single Model Path",
                "tier": routing.tier,
                "model": model.name,
                "response": response,
            }
        )
        result.audit_trail.append(
            {
                "step": "single_model_path",
                "model": model.id,
                "difficulty": routing.difficulty,
            }
        )
        return result
