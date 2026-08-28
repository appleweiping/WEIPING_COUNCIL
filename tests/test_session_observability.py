import asyncio
import json

from fastapi.testclient import TestClient

from backend.config import APP_VERSION, CouncilConfig
from backend.council import orchestrator as orchestrator_module
from backend.council.orchestrator import Orchestrator
from backend.council.session import Session, SessionResult
from backend import main as main_module
from backend.main import app
from backend.memory.shared_memory import SharedMemoryContext
from backend.providers.router import ModelRouter
from backend.engine.smart_router import RoutingDecision
from backend.engine.task_decomposer import DecompositionResult, SubTask
from backend.runtime import ModelCallTrace
from backend.runtime import RuntimeSettings
from backend.session_store import SessionStore, validate_session_payload


class FakeRouter:
    def __init__(self):
        self.traces = []

    def start_trace_scope(self):
        self.traces = []
        return object()

    def finish_trace_scope(self, token):
        return self.traces

    def current_traces(self):
        return self.traces

    async def query(self, model, messages, temperature=0.7, context=""):
        content = messages[-1]["content"]
        self.traces.append(
            ModelCallTrace(
                role=model.role,
                model_name=model.name,
                model_id=model.id,
                provider_status={
                    "role": model.role,
                    "name": model.name,
                    "model_id": model.id,
                    "endpoint_configured": True,
                    "api_format": "openai",
                    "source": "test",
                    "ready": True,
                    "has_api_key": True,
                    "missing": [],
                },
                latency_ms=1.5,
                attempts=1,
            )
        )
        if "Rate the difficulty" in content:
            return "0.1"
        return "fake answer"

    async def query_all(self, messages, temperature=0.7, context=""):
        return {"Fake": "fake answer"}

    def provider_health(self):
        return [
            {
                "role": "architect",
                "name": "Opus",
                "model_id": "fake-model",
                "endpoint_configured": True,
                "api_format": "openai",
                "source": "test",
                "ready": True,
                "has_api_key": True,
                "missing": [],
            }
        ]


def test_session_result_includes_metrics_provider_health_and_degraded_flag(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    config = CouncilConfig()
    orchestrator = Orchestrator(config, router=FakeRouter())
    session = Session(id="s1", query="hello", protocol="council", created_at="2026-06-01T00:00:00")

    result = asyncio.run(orchestrator.run(session))
    data = result.to_dict()

    assert data["metrics"]["total_ms"] >= 0
    assert "protocol_ms" in data["metrics"]
    assert "routing_ms" not in data["metrics"]
    assert data["routing"]["mode"] == "explicit"
    assert data["routing"]["selected_protocol"] == "council"
    assert data["provider_health"][0]["ready"] is True
    assert data["degraded"] is False
    assert data["model_call_traces"]
    assert "base_url" not in json.dumps(data["provider_health"])
    assert "fake://provider" not in json.dumps(data)


def test_every_named_protocol_result_satisfies_and_survives_session_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    store = SessionStore(tmp_path)
    protocols = ("council", "debate", "redteam", "consensus", "specialist", "tournament")

    for index, protocol in enumerate(protocols):
        orchestrator = Orchestrator(CouncilConfig(), router=FakeRouter())
        session_id = f"550e8400-e29b-41d4-a716-44665544000{index}"
        result = asyncio.run(
            orchestrator.run(
                Session(
                    id=session_id,
                    query="Give one deterministic research recommendation.",
                    protocol=protocol,
                    created_at="2026-08-27T00:00:00+00:00",
                )
            )
        )
        payload = result.to_dict()

        assert validate_session_payload(payload), protocol
        store.save(payload)
        assert store.get(session_id) == payload


def test_query_api_runs_and_persists_real_council_protocol(tmp_path, monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    monkeypatch.setattr(
        main_module,
        "orchestrator",
        Orchestrator(CouncilConfig(), router=FakeRouter()),
    )
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    response = TestClient(app).post(
        "/api/query",
        json={"query": "Give one deterministic research recommendation.", "protocol": "council"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["protocol"] == "council"
    assert body["stages"][1]["reviews"]
    assert SessionStore(tmp_path).get(body["id"]) == {
        key: value for key, value in body.items() if key != "session_id"
    }


def test_model_call_traces_are_scoped_to_each_session(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    config = CouncilConfig()
    router = FakeRouter()
    orchestrator = Orchestrator(config, router=router)
    first = Session(id="s1", query="hello", protocol="council", created_at="2026-06-01T00:00:00")
    second = Session(id="s2", query="again", protocol="council", created_at="2026-06-01T00:01:00")

    first_result = asyncio.run(orchestrator.run(first))
    second_result = asyncio.run(orchestrator.run(second))

    assert len(first_result.model_call_traces) > 0
    assert len(second_result.model_call_traces) == len(first_result.model_call_traces)


def test_real_router_traces_are_isolated_for_concurrent_sessions(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    config = CouncilConfig()
    router = ModelRouter(config, settings=RuntimeSettings.from_env(config, env={}))
    orchestrator = Orchestrator(config, router=router)
    first = Session(
        id="s1",
        query="what is simple basic hello",
        protocol="auto",
        created_at="2026-06-01T00:00:00",
    )
    second = Session(
        id="s2",
        query="what is simple basic hello again",
        protocol="auto",
        created_at="2026-06-01T00:01:00",
    )

    async def run_both():
        return await asyncio.gather(orchestrator.run(first), orchestrator.run(second))

    first_result, second_result = asyncio.run(run_both())

    assert len(first_result.model_call_traces) == 1
    assert len(second_result.model_call_traces) == 1
    assert first_result.model_call_traces[0]["role"] == "speedster"
    assert second_result.model_call_traces[0]["role"] == "speedster"


def test_agentmemory_warning_marks_session_degraded(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(warnings=["agentmemory context unavailable: ConnectError"]),
    )
    config = CouncilConfig()
    orchestrator = Orchestrator(config, router=FakeRouter())
    session = Session(id="s1", query="hello", protocol="council", created_at="2026-06-01T00:00:00")

    result = asyncio.run(orchestrator.run(session))

    assert result.degraded is True
    assert any("Context recall" in warning for warning in result.warnings)


def test_invalid_model_confidence_is_clamped_and_marked_degraded(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    config = CouncilConfig()
    orchestrator = Orchestrator(config, router=FakeRouter())

    class InvalidConfidenceProtocol:
        async def execute(self, session):
            result = SessionResult(
                id=session.id,
                query=session.query,
                protocol=session.protocol,
                created_at=session.created_at,
            )
            result.final_answer = "answer"
            result.confidence = 9.0
            return result

    orchestrator.protocols["council"] = InvalidConfidenceProtocol()
    session = Session(
        id="s1",
        query="hello",
        protocol="council",
        created_at="2026-06-01T00:00:00",
    )

    result = asyncio.run(orchestrator.run(session))

    assert result.confidence == 1.0
    assert result.degraded is True
    assert any("confidence" in warning for warning in result.warnings)


def test_non_finite_chairman_confidence_cannot_poison_session_json(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )

    class InfiniteConfidenceRouter(FakeRouter):
        async def query(self, model, messages, temperature=0.7, context=""):
            await super().query(model, messages, temperature, context)
            if "Chairman of the LLM Council" in messages[-1]["content"]:
                return "ANSWER: result\nCONFIDENCE: Infinity\nDISSENT: none"
            return "fake answer"

    orchestrator = Orchestrator(CouncilConfig(), router=InfiniteConfidenceRouter())
    session = Session(
        id="s1",
        query="hello",
        protocol="council",
        created_at="2026-06-01T00:00:00",
    )

    result = asyncio.run(orchestrator.run(session))

    assert result.confidence == 0.0
    assert result.degraded is True
    assert result.stages[-1]["confidence"] is None
    json.dumps(result.to_dict(), allow_nan=False)


def test_auto_standard_routing_uses_single_model_path(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    config = CouncilConfig()
    router = FakeRouter()
    orchestrator = Orchestrator(config, router=router)

    async def classify(query):
        return RoutingDecision(
            difficulty=0.4,
            tier="standard",
            assigned_models=["architect"],
            reason="test standard route",
        )

    monkeypatch.setattr(orchestrator.smart_router, "classify", classify)
    session = Session(
        id="s1",
        query="moderate question",
        protocol="auto",
        created_at="2026-06-01T00:00:00",
    )

    result = asyncio.run(orchestrator.run(session))

    assert result.protocol == "auto"
    assert result.routing["mode"] == "auto"
    assert result.routing["tier"] == "standard"
    assert result.routing["selected_protocol"] == "single_model"
    assert "standard_path_ms" in result.metrics
    assert "protocol_ms" not in result.metrics
    assert result.stages[0]["tier"] == "standard"


def test_auto_decomposition_routing_lists_actual_task_assignments(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    config = CouncilConfig()
    orchestrator = Orchestrator(config, router=FakeRouter())

    async def classify(query):
        return RoutingDecision(
            difficulty=0.9,
            tier="full_council",
            assigned_models=[model.id for model in config.models],
            reason="test complex route",
        )

    async def decompose(query, difficulty, context=""):
        return DecompositionResult(
            original_query=query,
            subtasks=[
                SubTask(0, "implement", "implementer", result="one", status="done"),
                SubTask(1, "review", "reviewer", result="two", status="done"),
            ],
            synthesis="combined",
            was_decomposed=True,
        )

    async def no_refine(session, result, metrics):
        return None

    monkeypatch.setattr(orchestrator.smart_router, "classify", classify)
    monkeypatch.setattr(orchestrator.decomposer, "process", decompose)
    monkeypatch.setattr(orchestrator, "_refine_result", no_refine)
    session = Session(
        id="s1",
        query="complex question",
        protocol="auto",
        created_at="2026-06-01T00:00:00",
    )

    result = asyncio.run(orchestrator.run(session))

    assert result.routing["selected_protocol"] == "decomposition"
    assert result.routing["assigned_models"] == ["implementer", "reviewer"]


def test_explicit_protocol_is_never_replaced_by_auto_routing(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "load_shared_memory",
        lambda **_: SharedMemoryContext(),
    )
    config = CouncilConfig()
    orchestrator = Orchestrator(config, router=FakeRouter())

    async def exploding_classifier(query):
        raise AssertionError("explicit protocols must not invoke the auto router")

    monkeypatch.setattr(orchestrator.smart_router, "classify", exploding_classifier)
    session = Session(
        id="s1",
        query="Design and compare a complex distributed architecture",
        protocol="debate",
        created_at="2026-06-01T00:00:00",
    )

    result = asyncio.run(orchestrator.run(session))

    assert result.protocol == "debate"
    assert result.routing["mode"] == "explicit"
    assert result.routing["selected_protocol"] == "debate"
    assert result.stages[0]["name"] == "Opening Statements"


def test_query_api_returns_actual_result_protocol_and_persists_json(tmp_path, monkeypatch):
    async def fake_run(session):
        result = SessionResult(
            id=session.id,
            query=session.query,
            protocol="auto",
            created_at=session.created_at,
        )
        result.final_answer = "fake answer"
        result.confidence = 0.7
        return result

    class FakeOrchestrator:
        async def run(self, session):
            return await fake_run(session)

    monkeypatch.setattr(main_module, "orchestrator", FakeOrchestrator())
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    client = TestClient(app)
    response = client.post(
        "/api/query",
        json={"query": "hello", "protocol": "council"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["protocol"] == "auto"
    saved = tmp_path / f"{body['id']}.json"
    assert saved.exists()
    assert json.loads(saved.read_text())["protocol"] == "auto"


def test_query_api_sanitizes_lone_surrogates_before_response_and_persistence(tmp_path, monkeypatch):
    class SurrogateOrchestrator:
        async def run(self, session):
            result = SessionResult(
                id=session.id,
                query=session.query,
                protocol=session.protocol,
                created_at=session.created_at,
            )
            result.final_answer = "answer:\ud800"
            result.dissent = ["dissent:\udfff"]
            result.stages = [{"responses": {"architect": "stage:\ud800"}}]
            return result

    monkeypatch.setattr(main_module, "orchestrator", SurrogateOrchestrator())
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    response = TestClient(app).post(
        "/api/query",
        json={"query": "hello", "protocol": "council"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["final_answer"] == "answer:\ufffd"
    assert body["dissent"] == ["dissent:\ufffd"]
    assert body["stages"][0]["responses"]["architect"] == "stage:\ufffd"
    saved = json.loads((tmp_path / f"{body['id']}.json").read_text(encoding="utf-8"))
    assert saved["final_answer"] == body["final_answer"]


def test_query_api_normalizes_isolated_surrogates_before_orchestration(tmp_path, monkeypatch):
    captured = {}

    class EchoOrchestrator:
        async def run(self, session):
            captured["context"] = session.context
            return SessionResult(
                id=session.id,
                query=session.query,
                protocol=session.protocol,
                created_at=session.created_at,
                final_answer="safe",
            )

    monkeypatch.setattr(main_module, "orchestrator", EchoOrchestrator())
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    request_body = (
        r'{"query":"before\ud800after","context":"context\udfff","protocol":"auto"}'
    ).encode("ascii")

    response = TestClient(app).post(
        "/api/query",
        content=request_body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "before\ufffdafter"
    assert captured["context"] == "context\ufffd"
    stored = json.loads((tmp_path / f"{body['id']}.json").read_text(encoding="utf-8"))
    assert stored["query"] == "before\ufffdafter"
    json.dumps(stored, ensure_ascii=False).encode("utf-8", errors="strict")


def test_query_api_rejects_unknown_protocol_before_running_orchestrator(monkeypatch):
    class ExplodingOrchestrator:
        async def run(self, session):
            raise AssertionError("orchestrator should not run")

    monkeypatch.setattr(main_module, "orchestrator", ExplodingOrchestrator())

    client = TestClient(app)
    response = client.post(
        "/api/query",
        json={"query": "hello", "protocol": "unknown"},
    )

    assert response.status_code == 400
    assert "Unknown protocol" in response.json()["detail"]


def test_query_api_rejects_blank_oversized_and_extra_inputs():
    client = TestClient(app)

    assert client.post("/api/query", json={"query": "   "}).status_code == 422
    assert client.post("/api/query", json={"query": "x" * 20_001}).status_code == 422
    assert client.post("/api/query", json={"query": "hello", "secret": "no"}).status_code == 422


def test_get_session_rejects_encoded_windows_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    client = TestClient(app)

    response = client.get("/api/sessions/..%5C..%5Cfrontend%5Cpackage")

    assert response.status_code == 404


def test_get_session_accepts_only_session_uuid_filenames(tmp_path, monkeypatch):
    session_id = "550e8400-e29b-41d4-a716-446655440000"
    payload = {
        "id": session_id,
        "query": "hello",
        "protocol": "council",
        "created_at": "2026-06-01T00:00:00+00:00",
    }
    (tmp_path / f"{session_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    client = TestClient(app)

    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["id"] == session_id


def test_health_endpoint_agentmemory_status_is_hermetic(monkeypatch):
    async def fake_agentmemory_health(base_url, secret=""):
        return {"ready": False, "configured": True, "status": "unreachable"}

    monkeypatch.setattr(main_module, "_agentmemory_health", fake_agentmemory_health)

    client = TestClient(app)
    response = client.get("/api/health")
    body = response.json()

    assert response.status_code == 200
    assert body["agentmemory"]["status"] == "unreachable"
    assert body["degraded"] is True


def test_health_endpoint_reports_readiness_without_secret_material(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    async def fake_agentmemory_health(base_url, secret=""):
        return {"ready": False, "configured": True, "status": "unreachable"}

    monkeypatch.setattr(main_module, "_agentmemory_health", fake_agentmemory_health)

    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == APP_VERSION
    assert body["status"] in {"ok", "degraded"}
    assert "providers" in body
    assert "agentmemory" in body
    assert "warnings" in body
    assert "sk-" not in json.dumps(body)
    assert "http://agentmemory" not in json.dumps(body)
    assert "base_url" not in json.dumps(body)
    assert body["runtime_policy"]["max_attempts"] >= 1


def test_models_endpoint_reports_active_runtime_model_without_endpoint_or_secret(monkeypatch):
    fixture_value = "".join(("test", "-key"))
    settings = RuntimeSettings.from_env(
        CouncilConfig(),
        env={
            "OPENROUTER_API_KEY": fixture_value,
            "OPENROUTER_BASE_URL": "".join(
                ("https://", "user:password@", "private.example/v1?token=secret")
            ),
            "OPENROUTER_MODEL": "shared-runtime-model",
            "VC_PROVIDER_ARCHITECT_MODEL": "architect-runtime-model",
        },
    )
    monkeypatch.setattr(main_module, "runtime_settings", settings)

    response = TestClient(app).get("/api/models")

    assert response.status_code == 200
    body = response.json()
    architect = next(item for item in body if item["role"] == "architect")
    coordinator = next(item for item in body if item["role"] == "coordinator")
    assert architect["provider_model"] == "architect-runtime-model"
    assert coordinator["provider_model"] == "shared-runtime-model"
    assert architect["provider_source"] == ("OPENROUTER_* + VC_PROVIDER_ARCHITECT_*")
    assert architect["ready"] is False
    assert architect["missing"] == ["base_url"]
    serialized = json.dumps(body)
    assert "test-key" not in serialized
    assert "private.example" not in serialized
    assert "user:password" not in serialized


def test_health_models_and_router_traces_share_fail_closed_provider_projection(monkeypatch):
    token_prefix = bytes((115, 107, 45, 111, 114, 45, 118, 49, 45)).decode()
    unsafe_model = token_prefix + "M" * 32
    configured_key = bytes((79, 80, 69, 78, 82, 79, 85, 84, 69, 82, 95, 65, 80, 73)).decode()
    unsafe_format = configured_key + "_KEY" + "=" + "format-marker"
    settings = RuntimeSettings.from_env(
        CouncilConfig(),
        env={
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_BASE_URL": "https://provider.example/v1",
            "OPENROUTER_MODEL": unsafe_model,
            "OPENROUTER_API_FORMAT": unsafe_format,
            "AGENTMEMORY_URL": "",
        },
    )
    monkeypatch.setattr(main_module, "runtime_settings", settings)

    models = TestClient(app).get("/api/models").json()
    health = TestClient(app).get("/api/health").json()
    router = ModelRouter(CouncilConfig(), settings=settings)
    asyncio.run(
        router.query(
            CouncilConfig().models[0],
            [{"role": "user", "content": "hello"}],
        )
    )
    trace = router.traces[-1].to_dict()
    rendered = json.dumps({"models": models, "health": health, "trace": trace})

    assert unsafe_model not in rendered
    assert unsafe_format not in rendered
    assert models[0]["provider_model"] == "...redacted"
    assert models[0]["api_format"] == "invalid"
    assert health["providers"][0]["model_id"] == "...redacted"
    assert trace["model_id"] == "...redacted"
    assert trace["provider_status"]["api_format"] == "invalid"


def test_protocol_degraded_state_and_warning_survive_observability_attachment():
    orchestrator = Orchestrator(CouncilConfig(), router=FakeRouter())
    result = SessionResult(
        id="s1",
        query="question",
        protocol="tournament",
        created_at="2026-08-27T00:00:00+00:00",
        degraded=True,
        warnings=["Tournament judge response was invalid."],
    )

    attached = orchestrator._attach_observability(result, {}, [], 0.0)

    assert attached.degraded is True
    assert "Tournament judge response was invalid." in attached.warnings


def test_live_and_ready_endpoints_separate_process_health_from_dependencies(monkeypatch):
    async def fake_agentmemory_health(base_url, secret=""):
        return {"ready": False, "configured": True, "status": "unreachable"}

    monkeypatch.setattr(main_module, "_agentmemory_health", fake_agentmemory_health)
    client = TestClient(app)

    assert client.get("/api/live").status_code == 200
    ready_response = client.get("/api/ready")
    assert ready_response.status_code == 503
    assert ready_response.json()["degraded"] is True


def test_disabled_optional_memory_does_not_degrade_ready_endpoint(monkeypatch):
    settings = RuntimeSettings.from_env(
        CouncilConfig(),
        env={
            "OPENROUTER_API_KEY": "test-key",
            "DEEPSEEK_API_KEY": "test-key",
            "AGENTMEMORY_URL": "",
        },
    )
    monkeypatch.setattr(main_module, "runtime_settings", settings)
    client = TestClient(app)

    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["agentmemory"]["configured"] is False
    assert response.json()["degraded"] is False


def test_health_reports_active_process_settings_without_reloading_env(monkeypatch):
    settings = RuntimeSettings.from_env(
        CouncilConfig(),
        env={"AGENTMEMORY_URL": ""},
    )
    monkeypatch.setattr(main_module, "runtime_settings", settings)

    def unexpected_reload(config):
        raise AssertionError("health must describe the settings active in this process")

    monkeypatch.setattr(main_module.RuntimeSettings, "from_env", unexpected_reload)
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["agentmemory"]["configured"] is False
    assert response.json()["degraded"] is True


def test_agentmemory_health_does_not_echo_untrusted_status_or_version(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "status": "healthy secret material",
                "version": {"private": "value"},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(
        main_module.httpx,
        "AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    result = asyncio.run(main_module._agentmemory_health("".join(("https://memory.", "local"))))

    assert result["ready"] is False
    assert result["status"] == "unknown"
    assert result["version"] == "unknown"
    assert "secret material" not in repr(result)


def test_agentmemory_health_rejects_secret_shaped_status_and_version(monkeypatch):
    token_prefix = bytes((115, 107, 45, 111, 114, 45, 118, 49, 45)).decode()
    unsafe_token = token_prefix + "Q" * 32

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"status": unsafe_token, "version": unsafe_token}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(main_module.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = asyncio.run(main_module._agentmemory_health("https://memory.example"))

    assert result["ready"] is False
    assert result["status"] == "unknown"
    assert result["version"] == "unknown"
    assert unsafe_token not in repr(result)


def test_agentmemory_health_uses_bearer_without_exposing_credential(monkeypatch):
    secret = bytes((104, 101, 97, 108, 116, 104, 45, 102, 105, 120, 116, 117, 114, 101)).decode()
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"status": "healthy", "version": "0.9.24"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return FakeResponse()

    monkeypatch.setattr(main_module.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = asyncio.run(
        main_module._agentmemory_health(
            "http://127.0.0.1:3111",
            secret,
        )
    )

    assert captured["headers"]["Authorization"] == f"Bearer {secret}"
    assert result == {
        "ready": True,
        "configured": True,
        "has_auth": True,
        "status": "healthy",
        "version": "0.9.24",
    }
    assert secret not in repr(result)
