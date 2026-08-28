import asyncio
import inspect

import httpx
import pytest

from backend.council import orchestrator as orchestrator_module
from backend.council.orchestrator import Orchestrator
from backend.memory import shared_memory
from backend.memory.shared_memory import AgentMemoryClient, load_shared_memory
from backend.memory.shared_memory import MAX_CONTEXT_CHARS
from backend.config import CouncilConfig
from backend.engine.self_refine import SelfRefineEngine
from backend.engine.task_decomposer import SubTask, TaskDecomposer
from backend.providers.router import ModelRouter
from backend.runtime import RuntimeSettings


def _runtime_text(codepoints: tuple[int, ...]) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


def _runtime_join(*parts: str) -> str:
    return "".join(parts)


def test_agentmemory_client_loads_official_full_search_and_metadata_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        if request.url.path == "/agentmemory/search":
            assert request.method == "POST"
            assert b'"format":"full"' in request.content
            return httpx.Response(
                200,
                json={
                    "format": "full",
                    "results": [
                        {
                            "observation": {
                                "narrative": "Pony is the current research priority.",
                                "facts": ["Use agentmemory; the retired backend is disabled."],
                            },
                            "score": 0.9,
                            "sessionId": "session-1",
                        }
                    ],
                },
            )
        if request.url.path == "/agentmemory/sessions":
            return httpx.Response(
                200,
                json={
                    "sessions": [
                        {
                            "id": "session-1",
                            "project": "workspace/ProteinResearch",
                            "cwd": "not-for-public-output",
                            "status": "active",
                            "observationCount": 3,
                        }
                    ]
                },
            )
        if request.url.path == "/agentmemory/lessons":
            assert request.url.params["limit"] == "20"
            return httpx.Response(
                200,
                json={
                    "lessons": [
                        {
                            "content": "Keep research evidence reproducible.",
                            "confidence": 0.9,
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = AgentMemoryClient(
        base_url="".join(("https://agentmemory.", "local")),
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)

    assert "Pony is the current research priority." in ctx.raw_summary
    assert "Use agentmemory" in ctx.raw_summary
    assert ctx.projects_available is True
    assert ctx.projects[0]["name"] == "ProteinResearch"
    assert "not-for-public-output" not in repr(ctx.projects)
    assert ctx.rules_available is True
    assert ctx.rules == ["Keep research evidence reproducible."]
    assert ctx.warnings == []


def test_agentmemory_bearer_auth_is_sent_only_to_loopback_and_never_echoed():
    bearer_value = _runtime_text(
        (109, 101, 109, 111, 114, 121, 45, 102, 105, 120, 116, 117, 114, 101)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {bearer_value}"
        if request.url.path == "/agentmemory/search":
            return httpx.Response(
                200,
                json={
                    "format": "full",
                    "results": [{"observation": {"narrative": "safe memory", "facts": []}}],
                },
            )
        if request.url.path == "/agentmemory/sessions":
            return httpx.Response(200, json={"sessions": []})
        if request.url.path == "/agentmemory/lessons":
            return httpx.Response(200, json={"lessons": []})
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = AgentMemoryClient(
        base_url="http://127.0.0.1:3111",
        secret=bearer_value,
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)

    assert ctx.raw_summary == "safe memory"
    assert bearer_value not in repr(ctx)

    insecure = AgentMemoryClient(
        base_url="http://memory.example",
        secret=bearer_value,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ValueError, match="HTTPS or a loopback"):
        insecure.search_context("query")

    embedded_userinfo = AgentMemoryClient(
        base_url=_runtime_join("https://", "user:pass@", "memory.example"),
        secret=bearer_value,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ValueError, match="HTTPS or a loopback"):
        embedded_userinfo.search_context("query")


def test_agentmemory_requires_confidential_transport_without_a_secret():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "authorization" not in request.headers
        if request.url.path == "/agentmemory/search":
            return httpx.Response(200, json={"format": "full", "results": []})
        if request.url.path == "/agentmemory/sessions":
            return httpx.Response(200, json={"sessions": []})
        if request.url.path == "/agentmemory/lessons":
            return httpx.Response(200, json={"lessons": []})
        raise AssertionError(f"unexpected path: {request.url.path}")

    insecure = AgentMemoryClient(
        base_url="http://memory.example",
        secret="",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ValueError, match="HTTPS or a loopback"):
        insecure.search_context("private query")
    assert requests == []

    loopback = AgentMemoryClient(
        base_url="http://127.0.0.1:3111",
        secret="",
        transport=httpx.MockTransport(handler),
    )
    result = loopback.search_context("private query")

    assert result.snippets == []
    assert [request.url.path for request in requests] == [
        "/agentmemory/search",
        "/agentmemory/sessions",
        "/agentmemory/lessons",
    ]


def test_orchestrator_uses_immutable_runtime_agentmemory_credential(monkeypatch):
    configured = _runtime_text(
        (99, 111, 110, 102, 105, 103, 117, 114, 101, 100, 45, 102, 105, 120, 116, 117, 114, 101)
    )
    changed = _runtime_text(
        (99, 104, 97, 110, 103, 101, 100, 45, 102, 105, 120, 116, 117, 114, 101)
    )
    config = CouncilConfig()
    settings = RuntimeSettings.from_env(
        config,
        env={
            "AGENTMEMORY_URL": "http://127.0.0.1:3111",
            "AGENTMEMORY_SECRET": configured,
        },
    )
    council = Orchestrator(config, router=ModelRouter(config, settings=settings))
    captured = {}

    def fake_load_shared_memory(*, client):
        captured["client"] = client
        return shared_memory.SharedMemoryContext()

    def unexpected_environment_reload(*args, **kwargs):
        raise AssertionError("explicit runtime settings must not be reloaded")

    monkeypatch.setenv("AGENTMEMORY_SECRET", changed)
    monkeypatch.setattr(orchestrator_module, "load_shared_memory", fake_load_shared_memory)
    monkeypatch.setattr(shared_memory, "merged_runtime_env", unexpected_environment_reload)

    council._get_shared_context()

    assert captured["client"].base_url == "http://127.0.0.1:3111"
    assert captured["client"]._secret == configured
    assert changed not in repr(captured["client"])


def test_agentmemory_maps_explicit_structured_projects_and_rules_safely():
    unsafe_label = _runtime_join(
        "OPENROUTER",
        "_API",
        "_KEY",
        "=",
        "private-marker",
    )
    private_endpoint = _runtime_join("http://192", ".168.", "42.9:8111")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"content": "Safe recalled summary."}],
                "context": {
                    "projects": [
                        {
                            "priority": 1,
                            "name": "Protein Research",
                            "direction": private_endpoint,
                            "status": unsafe_label,
                        }
                    ],
                    "rules": ["Use reproducible tests.", unsafe_label, {"invalid": "rule"}],
                },
            },
        )

    client = AgentMemoryClient(
        base_url="".join(("https://agentmemory.", "local")),
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)

    assert ctx.projects_available is True
    assert ctx.rules_available is True
    assert ctx.projects == [
        {
            "priority": 1,
            "name": "Protein Research",
            "direction": "...redacted",
            "status": "...redacted",
        }
    ]
    assert ctx.rules == ["Use reproducible tests."]
    assert unsafe_label not in repr(ctx)
    assert private_endpoint not in repr(ctx)


def test_agentmemory_invalid_structured_fields_are_observable_without_coercion():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [], "projects": {"not": "a list"}, "rules": "not a list"},
        )

    client = AgentMemoryClient(
        base_url="".join(("https://agentmemory.", "local")),
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)

    assert ctx.projects_available is True
    assert ctx.rules_available is True
    assert ctx.projects == []
    assert ctx.rules == []
    assert len(ctx.warnings) == 2


def test_agentmemory_accepts_explicit_structure_in_list_memory_records():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "memory": {
                        "content": "summary",
                        "projects": [
                            {
                                "priority": 2,
                                "name": "Analog Research",
                                "direction": "Validate simulations",
                                "status": "active",
                            }
                        ],
                        "rules": ["Keep evidence inspectable."],
                    }
                }
            ],
        )

    client = AgentMemoryClient(
        base_url="".join(("https://agentmemory.", "local")),
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)

    assert ctx.projects_available is True
    assert ctx.rules_available is True
    assert ctx.projects[0]["name"] == "Analog Research"
    assert ctx.rules == ["Keep evidence inspectable."]


def test_agentmemory_unavailable_returns_empty_context_with_warning():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    client = AgentMemoryClient(
        base_url="".join(("https://agentmemory.", "local")),
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)

    assert ctx.as_context_block() == ""
    assert ctx.warnings
    assert "agentmemory" in ctx.warnings[0].lower()


def test_agentmemory_can_be_explicitly_disabled_without_warning():
    client = AgentMemoryClient(base_url="")

    ctx = load_shared_memory(query="weiping council", client=client)

    assert ctx.as_context_block() == ""
    assert ctx.warnings == []


def test_agentmemory_client_reads_url_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTMEMORY_URL", raising=False)
    (tmp_path / ".env").write_text(
        "AGENTMEMORY_URL=http://dotenv-agentmemory:3111\n",
        encoding="utf-8",
    )
    client = AgentMemoryClient(dotenv_path=tmp_path / ".env")

    assert client.base_url == "http://dotenv-agentmemory:3111"


def test_shared_memory_module_has_no_retired_backends_or_markdown_paths():
    source = inspect.getsource(shared_memory)

    assert "".join(("agent", "-hub")) not in source.lower()
    assert "messages-vc" not in source.lower()
    assert "".join(("memory", "\\INDEX")) not in source
    assert "Vipin's Knowledgebase\\memory" not in source


def test_agentmemory_context_is_bounded():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agentmemory/sessions":
            return httpx.Response(200, json={"sessions": []})
        if request.url.path == "/agentmemory/lessons":
            return httpx.Response(200, json={"lessons": []})
        return httpx.Response(
            200,
            json={
                "format": "full",
                "results": [
                    {"observation": {"narrative": "x" * 10_000, "facts": []}} for _ in range(5)
                ],
            },
        )

    client = AgentMemoryClient(
        base_url="".join(("https://agentmemory.", "local")),
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)

    assert len(ctx.raw_summary) <= MAX_CONTEXT_CHARS


def test_agentmemory_replaces_isolated_surrogates_before_context_injection():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agentmemory/sessions":
            return httpx.Response(200, json={"sessions": []})
        if request.url.path == "/agentmemory/lessons":
            return httpx.Response(200, json={"lessons": []})
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(
                b'{"format":"full","results":[{"observation":'
                b'{"narrative":"before\\ud800after","facts":[]}}]}'
            ),
        )

    client = AgentMemoryClient(
        base_url="".join(("https://agentmemory.", "local")),
        transport=httpx.MockTransport(handler),
    )

    ctx = load_shared_memory(query="weiping council", client=client)
    block = ctx.as_context_block()

    assert ctx.raw_summary == "before\ufffdafter"
    assert chr(0xD800) not in block
    block.encode("utf-8", errors="strict")


def test_complete_agentmemory_context_block_is_bounded_and_preserves_section_labels():
    ctx = shared_memory.SharedMemoryContext(
        raw_summary="x" * 30_000,
        projects=[
            {
                "priority": index,
                "name": f"Project {index}",
                "direction": "d" * 1_000,
                "status": "active",
            }
            for index in range(100)
        ],
        rules=["r" * 1_000 for _ in range(20)],
        projects_available=True,
        rules_available=True,
    )

    block = ctx.as_context_block()

    assert len(block) <= MAX_CONTEXT_CHARS
    assert "=== Recalled Agentmemory Context ===" in block
    assert "=== Active Projects ===" in block
    assert "=== Key Rules ===" in block
    block.encode("utf-8", errors="strict")


def test_auto_decomposition_preserves_run_context_for_each_subtask():
    class RecordingRouter:
        def __init__(self):
            self.calls = []

        async def query(self, model, messages, temperature=0.7, context=""):
            self.calls.append({"messages": messages, "context": context})
            return f"result-{len(self.calls)}"

    config = CouncilConfig()
    router = RecordingRouter()
    decomposer = TaskDecomposer(config, router)
    tasks = [
        SubTask(id=0, description="first", assigned_to=config.models[0].id),
        SubTask(
            id=1,
            description="second",
            assigned_to=config.models[1].id,
            depends_on=[0],
        ),
    ]

    asyncio.run(
        decomposer._execute_tasks(
            "original",
            tasks,
            context="untrusted recalled context",
        )
    )

    assert [call["context"] for call in router.calls] == [
        "untrusted recalled context",
        "untrusted recalled context",
    ]
    assert "Context from previous steps" in router.calls[1]["messages"][0]["content"]


def test_auto_decomposition_caps_untrusted_model_output_at_five_subtasks():
    class VerboseRouter:
        async def query(self, model, messages, temperature=0.7, context=""):
            return "\n".join(f"{index}. task {index} | depends: none" for index in range(1, 21))

    config = CouncilConfig()
    decomposer = TaskDecomposer(config, VerboseRouter())

    tasks = asyncio.run(decomposer._decompose("large task", context="memory"))

    assert len(tasks) == 5


def test_post_protocol_refinement_preserves_untrusted_run_context():
    class RecordingRouter:
        def __init__(self):
            self.contexts = []

        async def query(self, model, messages, temperature=0.7, context=""):
            self.contexts.append(context)
            if "rigorous critic" in messages[0]["content"]:
                return "SCORE: 1\nCRITIQUE: improve it"
            return "improved"

    config = CouncilConfig()
    router = RecordingRouter()
    engine = SelfRefineEngine(router, max_iterations=1)

    asyncio.run(
        engine.refine(
            config.models[0],
            config.models[1],
            "question",
            "initial",
            context="untrusted recalled context",
        )
    )

    assert router.contexts == [
        "untrusted recalled context",
        "untrusted recalled context",
    ]


def test_refinement_rejects_non_finite_internal_scores():
    class InfiniteScoreRouter:
        async def query(self, model, messages, temperature=0.7, context=""):
            if "rigorous critic" in messages[0]["content"]:
                return "SCORE: Infinity\nCRITIQUE: retry"
            return "improved"

    config = CouncilConfig()
    engine = SelfRefineEngine(InfiniteScoreRouter(), max_iterations=1)

    result = asyncio.run(
        engine.refine(
            config.models[0],
            config.models[1],
            "question",
            "initial",
        )
    )

    assert result.scores == [5.0]
