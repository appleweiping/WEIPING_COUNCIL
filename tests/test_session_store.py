import json
import math
import os

import pytest

from backend.session_store import SessionStore, validate_session_payload


FIRST_ID = "550e8400-e29b-41d4-a716-446655440000"
SECOND_ID = "550e8400-e29b-41d4-a716-446655440001"


def _runtime_join(*parts: str) -> str:
    return "".join(parts)


def _runtime_true() -> bool:
    return bool(object())


def _payload(session_id: str, created_at: str, query: str = "hello") -> dict:
    return {
        "id": session_id,
        "query": query,
        "protocol": "auto",
        "created_at": created_at,
        "degraded": False,
    }


def test_session_store_saves_atomically_and_lists_by_created_time(tmp_path):
    store = SessionStore(tmp_path)
    store.save(_payload(FIRST_ID, "2026-08-23T01:00:00+00:00", "older"))
    store.save(_payload(SECOND_ID, "2026-08-23T02:00:00+00:00", "newer"))

    summaries = store.list_summaries()

    assert [item["id"] for item in summaries] == [SECOND_ID, FIRST_ID]
    assert store.get(FIRST_ID)["query"] == "older"
    assert not list(tmp_path.glob("*.tmp"))


def test_session_store_skips_corrupt_and_mismatched_artifacts(tmp_path):
    store = SessionStore(tmp_path)
    (tmp_path / f"{FIRST_ID}.json").write_text("not json", encoding="utf-8")
    (tmp_path / f"{SECOND_ID}.json").write_text(
        '{"id":"550e8400-e29b-41d4-a716-446655440099"}',
        encoding="utf-8",
    )

    assert store.list_summaries() == []
    assert store.get(FIRST_ID) is None
    assert store.find_prefix("../../") is None


def test_failed_replace_preserves_previous_session_and_cleans_temp_file(tmp_path, monkeypatch):
    store = SessionStore(tmp_path)
    store.save(_payload(FIRST_ID, "2026-08-23T01:00:00+00:00", "original"))

    def fail_replace(source, destination):
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.save(_payload(FIRST_ID, "2026-08-23T02:00:00+00:00", "replacement"))

    assert store.get(FIRST_ID)["query"] == "original"
    assert not list(tmp_path.glob("*.tmp"))


def test_find_prefix_ignores_corrupt_matching_files(tmp_path):
    store = SessionStore(tmp_path)
    store.save(_payload(FIRST_ID, "2026-08-23T01:00:00+00:00", "valid"))
    prefix = FIRST_ID[:8]
    (tmp_path / f"{prefix}-not-a-uuid.json").write_text(
        '{"id":"550e8400../../private"}',
        encoding="utf-8",
    )

    assert store.find_prefix(prefix)["query"] == "valid"


def test_session_store_rejects_non_finite_json(tmp_path):
    store = SessionStore(tmp_path)
    payload = _payload(FIRST_ID, "2026-08-23T01:00:00+00:00")
    payload["confidence"] = math.nan

    with pytest.raises(ValueError):
        store.save(payload)

    (tmp_path / f"{SECOND_ID}.json").write_text(
        f'{{"id":"{SECOND_ID}","created_at":NaN}}',
        encoding="utf-8",
    )
    assert store.get(SECOND_ID) is None
    assert store.list_summaries() == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"protocol": []},
        {"query": {}},
        {"confidence": "bad"},
        {"stages": {}},
        {"dissent": ["valid", {"not": "text"}]},
        {"routing": []},
        {"degraded": 1},
        {"provider_health": [{"name": {"attacker": "object"}}]},
        {"model_call_traces": [{"role": {"attacker": "object"}}]},
        {"stages": [{"name": {"attacker": "object"}}]},
        {"stages": [{"responses": {"architect": {"attacker": "object"}}}]},
        {"stages": [{"reviews": {"reviewer": {"review": "ok", "extra": "bad"}}}]},
        {"routing": {"mode": {"toString": None, "valueOf": None}}},
        {"routing": {"selected_protocol": {"toString": None, "valueOf": None}}},
        {"routing": {"assigned_models": ["valid", {"attacker": "object"}]}},
        {"routing": {"difficulty": "hard"}},
        {"routing": {"decomposed": 1}},
        {"metrics": {"total_ms": {"attacker": "object"}}},
        {"model_call_traces": [{"provider_status": {"name": {"attacker": "object"}}}]},
        {_runtime_join("api_", "key"): "top-level-secret-marker"},
        {"provider_health": [{_runtime_join("api_", "key"): "provider-secret-marker"}]},
        {
            "provider_health": [
                {"base_url": _runtime_join("https://", "user:pass@", "example.test")}
            ]
        },
        {"model_call_traces": [{_runtime_join("api_", "key"): "trace-secret-marker"}]},
        {
            "model_call_traces": [
                {"provider_status": {_runtime_join("api_", "key"): "nested-secret-marker"}}
            ]
        },
        {
            "stages": [
                {
                    "name": "unsafe",
                    "provider_config": {
                        _runtime_join("api_", "key"): "stage-secret-marker",
                        "base_url": "http://private.invalid",
                    },
                }
            ]
        },
        {
            "stages": [
                {
                    "name": "unsafe",
                    "proponent": {
                        "model": "m",
                        _runtime_join("api_", "key"): "nested-stage-marker",
                    },
                }
            ]
        },
        {
            "audit_trail": [
                {
                    "step": "unsafe",
                    _runtime_join("api_", "key"): "audit-secret-marker",
                    "raw_exception": "x",
                }
            ]
        },
        {
            "metrics": {
                "total_ms": 1,
                _runtime_join("provider_", "secret"): "metrics-secret-marker",
            }
        },
    ],
)
def test_session_store_rejects_schema_invalid_artifacts(tmp_path, mutation):
    store = SessionStore(tmp_path)
    payload = {**_payload(FIRST_ID, "2026-08-23T01:00:00+00:00"), **mutation}
    (tmp_path / f"{FIRST_ID}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    assert store.get(FIRST_ID) is None
    assert store.find_prefix(FIRST_ID[:8]) is None
    assert store.list_summaries() == []


@pytest.mark.parametrize(
    "body",
    [
        f'{{"id":"{FIRST_ID}","query":"q","protocol":"auto",'
        '"created_at":"2026-08-23T01:00:00+00:00","confidence":1e999}',
        f'{{"id":"{FIRST_ID}","query":"q","protocol":"auto",'
        '"created_at":"2026-08-23T01:00:00+00:00",'
        '"metrics":{"nested":-1e999}}',
    ],
)
def test_session_store_rejects_exponent_overflow_at_any_depth(tmp_path, body):
    store = SessionStore(tmp_path)
    (tmp_path / f"{FIRST_ID}.json").write_text(body, encoding="utf-8")

    assert store.get(FIRST_ID) is None
    assert store.list_summaries() == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"confidence": 10**400},
        {"metrics": {"total_ms": 10**400}},
        {"stages": [{"agreement_ratio": 10**400}]},
        {"model_call_traces": [{"latency_ms": 10**400}]},
    ],
)
def test_session_store_rejects_integer_overflow_without_raising(tmp_path, mutation):
    store = SessionStore(tmp_path)
    payload = {**_payload(FIRST_ID, "2026-08-23T01:00:00+00:00"), **mutation}
    (tmp_path / f"{FIRST_ID}.json").write_text(json.dumps(payload), encoding="utf-8")

    assert validate_session_payload(payload) is False
    assert store.get(FIRST_ID) is None
    assert store.find_prefix(FIRST_ID[:8]) is None
    assert store.list_summaries() == []


def test_session_store_replaces_lone_surrogates_before_atomic_persistence(tmp_path):
    store = SessionStore(tmp_path)
    payload = _payload(FIRST_ID, "2026-08-23T01:00:00+00:00")
    payload.update(
        {
            "final_answer": "high:\ud800 low:\udfff",
            "stages": [{"responses": {"architect": "nested:\ud800"}}],
        }
    )

    destination = store.save(payload)
    loaded = store.get(FIRST_ID)

    assert destination.exists()
    assert loaded["final_answer"] == "high:\ufffd low:\ufffd"
    assert loaded["stages"][0]["responses"]["architect"] == "nested:\ufffd"
    destination.read_text(encoding="utf-8").encode("utf-8", errors="strict")


def test_session_store_rejects_cyclic_payloads_without_leaving_temp_files(tmp_path):
    store = SessionStore(tmp_path)
    payload = _payload(FIRST_ID, "2026-08-23T01:00:00+00:00")
    payload["metrics"] = payload

    with pytest.raises(ValueError, match="cyclic"):
        store.save(payload)

    assert not list(tmp_path.glob("*.tmp"))


def test_session_store_rejects_oversized_serialization_before_opening_temp_file(tmp_path):
    store = SessionStore(tmp_path)
    original = _payload(FIRST_ID, "2026-08-23T01:00:00+00:00", "original")
    store.save(original)
    oversized = {
        **original,
        "query": "replacement",
        "dissent": ["x" * 1_000_000 for _ in range(11)],
    }

    with pytest.raises(ValueError, match="maximum artifact size"):
        store.save(oversized)

    assert store.get(FIRST_ID)["query"] == "original"
    assert not list(tmp_path.glob("*.tmp"))


def test_session_store_rejects_unsafe_public_provider_evidence_from_old_artifacts(tmp_path):
    token_prefix = bytes((115, 107, 45, 111, 114, 45, 118, 49, 45)).decode()
    unsafe_model = token_prefix + "Q" * 32
    status = {
        "role": "architect",
        "name": "Opus",
        "model_id": unsafe_model,
        "api_format": "openai",
        "source": "OPENROUTER_*",
        "ready": True,
        "endpoint_configured": True,
        "has_api_key": _runtime_true(),
        "missing": [],
    }
    mutations = (
        {"provider_health": [status]},
        {
            "model_call_traces": [
                {
                    "role": "architect",
                    "model_name": "Opus",
                    "model_id": unsafe_model,
                    "provider_status": status,
                }
            ]
        },
    )
    store = SessionStore(tmp_path)

    for mutation in mutations:
        payload = {
            **_payload(FIRST_ID, "2026-08-23T01:00:00+00:00"),
            **mutation,
        }
        (tmp_path / f"{FIRST_ID}.json").write_text(json.dumps(payload), encoding="utf-8")

        assert validate_session_payload(payload) is False
        assert store.get(FIRST_ID) is None


def test_session_store_rejects_absolute_operator_paths_in_public_evidence():
    separator = chr(92)
    windows_path = _runtime_join("D", chr(58), separator, "Temp", separator, "private")
    posix_path = _runtime_join(chr(47), "opt", chr(47), "company", chr(47), "private")
    safe_status = {
        "role": "architect",
        "name": "Opus",
        "model_id": "openai/gpt-5.5",
        "api_format": "openai",
        "source": "OPENROUTER_*",
        "ready": True,
        "endpoint_configured": True,
        "has_api_key": True,
        "missing": [],
    }
    mutations = (
        {"provider_health": [{**safe_status, "source": windows_path}]},
        {
            "model_call_traces": [
                {
                    "role": "architect",
                    "model_name": "Opus",
                    "model_id": "openai/gpt-5.5",
                    "provider_status": safe_status,
                    "error_kind": posix_path,
                }
            ]
        },
        {
            "model_call_traces": [
                {
                    "role": "architect",
                    "model_name": "Opus",
                    "model_id": "openai/gpt-5.5",
                    "provider_status": safe_status,
                    "retry_reasons": [windows_path],
                }
            ]
        },
    )

    for mutation in mutations:
        payload = {
            **_payload(FIRST_ID, "2026-08-23T01:00:00+00:00"),
            **mutation,
        }
        assert validate_session_payload(payload) is False
