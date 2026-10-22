import asyncio

from backend import demo
from backend.config import CouncilConfig
from backend.council.orchestrator import Orchestrator
from backend.council.session import Session
from backend.providers.router import ModelRouter
from backend.runtime import DEMO_MODEL_ID, RuntimeSettings


def _demo_orchestrator(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(demo.asyncio, "sleep", no_sleep)
    config = CouncilConfig()
    settings = RuntimeSettings.from_env(config, env={"VC_DEMO": "1"})
    return Orchestrator(config, router=ModelRouter(config, settings=settings))


def _run(orchestrator, query, protocol="council"):
    session = Session(id="demo-test", query=query, protocol=protocol, created_at="2026-01-01T00:00:00")
    return asyncio.run(orchestrator.run(session))


def test_demo_settings_need_no_keys_and_skip_memory():
    settings = RuntimeSettings.from_env(CouncilConfig(), env={"VC_DEMO": "1"})
    assert settings.demo is True
    assert settings.agentmemory_url == ""
    statuses = settings.provider_status()
    assert len(statuses) == 6
    assert all(status["ready"] and status["model_id"] == DEMO_MODEL_ID for status in statuses)


def test_agentmemory_is_off_unless_configured():
    settings = RuntimeSettings.from_env(CouncilConfig(), env={})
    assert settings.demo is False
    assert settings.agentmemory_url == ""


def test_demo_council_runs_every_stage_without_network(monkeypatch):
    result = _run(_demo_orchestrator(monkeypatch), demo.DEMO_QUESTION)

    assert [stage["name"] for stage in result.stages] == [
        "First Opinions",
        "Peer Review",
        "Chairman Synthesis",
    ]
    assert len(result.stages[0]["responses"]) == 6
    # 6 opinions + 6 peer reviews + 1 chairman call, all answered by the script.
    assert len(result.model_call_traces) == 13
    assert all(trace["error_kind"] is None for trace in result.model_call_traces)
    assert result.final_answer.startswith("Keep one backend service")
    assert result.confidence == 0.86
    assert result.dissent and "distributed-systems" in result.dissent[0]
    assert result.degraded is False
    assert "Demo mode: replies are canned and no model was called." in result.warnings


def test_demo_says_so_when_the_question_is_not_the_sample(monkeypatch):
    result = _run(_demo_orchestrator(monkeypatch), "Is Rust or C++ better for embedded work?")
    assert "Your question was not sent to any model" in result.final_answer


def test_demo_other_protocols_explain_the_limitation(monkeypatch):
    result = _run(_demo_orchestrator(monkeypatch), demo.DEMO_QUESTION, protocol="debate")
    assert "only has canned replies for the council protocol" in result.final_answer
