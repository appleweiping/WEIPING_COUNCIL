"""Regression coverage for provider-failure semantics in routed protocols."""

from __future__ import annotations

import asyncio

import pytest

from backend.config import CouncilConfig
from backend.council.session import Session
from backend.engine.task_decomposer import SubTask, TaskDecomposer
from backend.protocols.tournament_protocol import TournamentProtocol
from backend.providers.router import is_provider_error_result


def _two_member_config() -> CouncilConfig:
    defaults = CouncilConfig()
    return CouncilConfig(models=defaults.models[:2], chairman=defaults.models[0].id)


def test_provider_failure_marker_recognizer_is_exact_and_does_not_match_normal_brackets():
    assert is_provider_error_result("[Judge ERROR: provider call failed (timeout)]") is True
    assert is_provider_error_result("[Judge unavailable: missing provider configuration]") is True
    assert is_provider_error_result("[analysis error: ordinary prose]") is False
    assert is_provider_error_result("prefix [Judge ERROR: provider call failed (timeout)]") is False


def test_decomposer_marks_fixed_provider_failure_results_failed_not_done():
    class FailedRouter:
        async def query(self, model, messages, temperature=0.7, context=""):
            return f"[{model.name} ERROR: provider call failed (timeout)]"

    config = _two_member_config()
    tasks = [SubTask(id=0, description="research", assigned_to=config.models[0].id)]

    asyncio.run(TaskDecomposer(config, FailedRouter())._execute_tasks("query", tasks))

    assert tasks[0].status == "failed"
    assert "provider call failed" in tasks[0].result


def test_decomposer_skips_dependents_when_a_required_task_failed():
    class FailedRouter:
        calls = 0

        async def query(self, model, messages, temperature=0.7, context=""):
            self.calls += 1
            return f"[{model.name} ERROR: provider call failed (timeout)]"

    config = _two_member_config()
    tasks = [
        SubTask(id=0, description="research", assigned_to=config.models[0].id),
        SubTask(
            id=1,
            description="implement",
            assigned_to=config.models[1].id,
            depends_on=[0],
        ),
    ]
    router = FailedRouter()

    asyncio.run(TaskDecomposer(config, router)._execute_tasks("query", tasks))

    assert router.calls == 1
    assert [task.status for task in tasks] == ["failed", "failed"]
    assert tasks[1].result == "Skipped because a required dependency failed."


@pytest.mark.parametrize(
    "judge_verdict",
    [
        "The second response seems stronger.",
        "WINNER: A\nWINNER: B",
        "WINNER: A, but the alternative says WINNER: B",
        "[Judge unavailable: missing provider configuration (api_key)]",
    ],
)
def test_tournament_never_defaults_to_b_for_invalid_or_failed_judgments(judge_verdict):
    class Router:
        async def query(self, model, messages, temperature=0.7, context=""):
            if "CONTESTANT A" in messages[-1]["content"]:
                return judge_verdict
            return f"answer-{model.id}"

    config = _two_member_config()
    protocol = TournamentProtocol(config, Router())
    session = Session(
        id="s1",
        query="Compare two answers",
        protocol="tournament",
        created_at="2026-08-27T00:00:00+00:00",
    )

    result = asyncio.run(protocol.execute(session))

    assert result.degraded is True
    assert result.confidence == 0.0
    assert "could not determine a winner" in result.final_answer
    assert result.stages[-1]["matchups"][-1]["winner"] == ""
    assert result.audit_trail[-1]["action"] == "tournament_inconclusive"
    assert all(stage.get("name") != "Tournament Winner" for stage in result.stages)


def test_tournament_preserves_normal_explicit_winner_path():
    class Router:
        async def query(self, model, messages, temperature=0.7, context=""):
            if "CONTESTANT A" in messages[-1]["content"]:
                return "WINNER: B\nThe second answer is more complete."
            return f"answer-{model.id}"

    config = _two_member_config()
    protocol = TournamentProtocol(config, Router())
    session = Session(
        id="s1",
        query="Compare two answers",
        protocol="tournament",
        created_at="2026-08-27T00:00:00+00:00",
    )

    result = asyncio.run(protocol.execute(session))

    assert result.degraded is False
    assert result.confidence == 0.75
    assert result.final_answer == f"answer-{config.models[1].id}"
    assert result.stages[-1]["winner"] == config.models[1].id


def test_tournament_never_selects_a_failed_contestant_over_a_usable_answer():
    class Router:
        judge_called = False

        async def query(self, model, messages, temperature=0.7, context=""):
            if "CONTESTANT A" in messages[-1]["content"]:
                self.judge_called = True
                return "WINNER: A\nThe first response looks better."
            if model.id == config.models[0].id:
                return f"[{model.name} unavailable: missing provider configuration (api_key)]"
            return "usable answer"

    config = _two_member_config()
    router = Router()
    protocol = TournamentProtocol(config, router)
    session = Session(
        id="s1",
        query="Compare two answers",
        protocol="tournament",
        created_at="2026-08-27T00:00:00+00:00",
    )

    result = asyncio.run(protocol.execute(session))

    assert router.judge_called is False
    assert result.final_answer == "usable answer"
    assert result.stages[-1]["winner"] == config.models[1].id
    assert result.degraded is True
    assert result.confidence == 0.5


def test_tournament_is_inconclusive_when_no_usable_answer_remains():
    class Router:
        async def query(self, model, messages, temperature=0.7, context=""):
            return f"[{model.name} ERROR: provider call failed (timeout)]"

    config = _two_member_config()
    protocol = TournamentProtocol(config, Router())
    session = Session(
        id="s1",
        query="Compare two answers",
        protocol="tournament",
        created_at="2026-08-27T00:00:00+00:00",
    )

    result = asyncio.run(protocol.execute(session))

    assert result.degraded is True
    assert result.confidence == 0.0
    assert "no usable contestant response remained" in result.final_answer
    assert result.audit_trail[-1]["action"] == "tournament_inconclusive"


def test_tournament_does_not_advance_a_failed_odd_contestant_on_a_bye():
    defaults = CouncilConfig()
    config = CouncilConfig(models=defaults.models[:3], chairman=defaults.models[0].id)

    class Router:
        async def query(self, model, messages, temperature=0.7, context=""):
            return f"[{model.name} ERROR: provider call failed (timeout)]"

    result = asyncio.run(
        TournamentProtocol(config, Router()).execute(
            Session(
                id="s1",
                query="Compare answers",
                protocol="tournament",
                created_at="2026-08-27T00:00:00+00:00",
            )
        )
    )

    assert result.degraded is True
    assert result.confidence == 0.0
    assert "no usable contestant response remained" in result.final_answer
