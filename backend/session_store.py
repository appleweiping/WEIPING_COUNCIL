"""Atomic, corruption-tolerant persistence for inspectable council sessions."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from .safe_json import sanitize_json_value, sanitize_unicode_scalar
from .runtime import project_public_api_format, project_public_model_id, project_public_text


SESSION_ID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
SESSION_PREFIX_RE = re.compile(r"^[0-9a-fA-F-]{4,36}$")
MAX_SESSION_BYTES = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 1_000_000
PROTOCOL_IDS = {
    "auto",
    "council",
    "debate",
    "redteam",
    "consensus",
    "specialist",
    "tournament",
}
SESSION_FIELDS = {
    "id",
    "session_id",
    "query",
    "protocol",
    "created_at",
    "stages",
    "final_answer",
    "confidence",
    "dissent",
    "audit_trail",
    "routing",
    "metrics",
    "provider_health",
    "model_call_traces",
    "degraded",
    "warnings",
}
PROVIDER_STATUS_FIELDS = {
    "role",
    "name",
    "model_id",
    "api_format",
    "source",
    "ready",
    "endpoint_configured",
    "has_api_key",
    "missing",
}
MODEL_TRACE_FIELDS = {
    "role",
    "model_name",
    "model_id",
    "latency_ms",
    "retry_delay_ms",
    "attempts",
    "status_code",
    "retry_reasons",
    "error_kind",
    "provider_status",
}
STAGE_FIELDS = {
    "name",
    "responses",
    "agreement_ratio",
    "reviews",
    "final",
    "confidence",
    "proponent",
    "opponent",
    "judge",
    "verdict",
    "attacker",
    "critique",
    "classification",
    "specialist",
    "answer",
    "verifications",
    "matchups",
    "winner",
    "subtasks",
    "iterations",
    "converged",
    "scores",
    "tier",
    "model",
    "response",
}
AUDIT_FIELDS = {
    "stage",
    "action",
    "step",
    "count",
    "model_count",
    "review_count",
    "dissent_count",
    "verifier_count",
    "remaining",
    "subtask_count",
    "iterations",
    "final_score",
    "agreement_ratio",
    "confidence",
    "difficulty",
    "attacker",
    "specialist",
    "winner",
    "model",
    "result",
    "mode",
    "requested_protocol",
    "selected_protocol",
    "tier",
    "assigned_models",
    "reason",
    "decomposed",
}
METRIC_FIELDS = {
    "context_ms",
    "protocol_ms",
    "routing_ms",
    "fast_path_ms",
    "standard_path_ms",
    "decomposition_ms",
    "refine_ms",
    "total_ms",
    "successful_model_calls",
    "failed_model_calls",
}


def _reject_nonstandard_constant(value: str):
    raise ValueError(f"non-standard JSON constant: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON numbers must be finite")
    return parsed


def _valid_text(value, *, minimum: int = 0, maximum: int = MAX_TEXT_LENGTH) -> bool:
    return (
        isinstance(value, str)
        and minimum <= len(value) <= maximum
        and sanitize_unicode_scalar(value) == value
    )


def _valid_list_of(payload: dict, field: str, item_type: type) -> bool:
    value = payload.get(field, [])
    return (
        isinstance(value, list)
        and len(value) <= 10_000
        and all(isinstance(item, item_type) for item in value)
    )


def _finite_number(value, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return (
        math.isfinite(number)
        and (minimum is None or number >= minimum)
        and (maximum is None or number <= maximum)
    )


def _valid_optional_text(record: dict, field: str, *, nullable: bool = False) -> bool:
    if field not in record:
        return True
    value = record[field]
    return (nullable and value is None) or _valid_text(value)


def _valid_optional_public_text(record: dict, field: str, *, maximum: int) -> bool:
    if not _valid_optional_text(record, field):
        return False
    return (
        field not in record or project_public_text(record[field], maximum=maximum) == record[field]
    )


def _valid_string_map(value) -> bool:
    return (
        isinstance(value, dict)
        and len(value) <= 1_000
        and all(_valid_text(key) and _valid_text(item) for key, item in value.items())
    )


def _valid_reviews(value) -> bool:
    """Accept current review records and legacy string-only review maps."""
    return (
        isinstance(value, dict)
        and len(value) <= 1_000
        and all(
            _valid_text(key)
            and (
                _valid_text(item)
                or (
                    isinstance(item, dict)
                    and set(item) == {"review"}
                    and _valid_text(item["review"])
                )
            )
            for key, item in value.items()
        )
    )


def _valid_string_record(value, fields: set[str]) -> bool:
    return (
        isinstance(value, dict)
        and not set(value) - fields
        and all(_valid_text(key) and _valid_text(item) for key, item in value.items())
    )


def _valid_record_list(value, fields: set[str]) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 10_000
        and all(_valid_string_record(item, fields) for item in value)
    )


def _valid_stage(stage: dict) -> bool:
    if set(stage) - STAGE_FIELDS:
        return False
    if not _valid_optional_text(stage, "name"):
        return False
    for field in (
        "final",
        "judge",
        "verdict",
        "attacker",
        "critique",
        "classification",
        "specialist",
        "answer",
        "winner",
        "tier",
        "model",
        "response",
    ):
        if not _valid_optional_text(stage, field):
            return False
    if "agreement_ratio" in stage and not _finite_number(
        stage["agreement_ratio"], minimum=0.0, maximum=1.0
    ):
        return False
    if (
        "confidence" in stage
        and stage["confidence"] is not None
        and not _finite_number(stage["confidence"], minimum=0.0, maximum=1.0)
    ):
        return False
    for field in ("responses", "verifications"):
        if field in stage and not _valid_string_map(stage[field]):
            return False
    if "reviews" in stage and not _valid_reviews(stage["reviews"]):
        return False
    for field in ("proponent", "opponent"):
        if field in stage and not _valid_string_record(
            stage[field], {"model", "argument", "rebuttal"}
        ):
            return False
    if "matchups" in stage and not _valid_record_list(
        stage["matchups"], {"a", "b", "winner", "verdict"}
    ):
        return False
    if "subtasks" in stage and not _valid_record_list(
        stage["subtasks"], {"desc", "model", "status", "result"}
    ):
        return False
    if "iterations" in stage and (
        isinstance(stage["iterations"], bool)
        or not isinstance(stage["iterations"], int)
        or not 0 <= stage["iterations"] <= 10_000
    ):
        return False
    if "converged" in stage and not isinstance(stage["converged"], bool):
        return False
    if "scores" in stage and not (
        isinstance(stage["scores"], list)
        and len(stage["scores"]) <= 10_000
        and all(_finite_number(score) for score in stage["scores"])
    ):
        return False
    return True


def _valid_audit_entry(entry: dict) -> bool:
    if set(entry) - AUDIT_FIELDS:
        return False
    for field in (
        "action",
        "step",
        "attacker",
        "specialist",
        "winner",
        "model",
        "result",
        "mode",
        "requested_protocol",
        "selected_protocol",
        "tier",
        "reason",
    ):
        if not _valid_optional_text(entry, field):
            return False
    for field in (
        "stage",
        "count",
        "model_count",
        "review_count",
        "dissent_count",
        "verifier_count",
        "remaining",
        "subtask_count",
        "iterations",
    ):
        if field in entry and (
            isinstance(entry[field], bool)
            or not isinstance(entry[field], int)
            or not 0 <= entry[field] <= 10_000
        ):
            return False
    for field in ("agreement_ratio", "confidence", "difficulty"):
        if (
            field in entry
            and entry[field] is not None
            and not _finite_number(entry[field], minimum=0.0, maximum=1.0)
        ):
            return False
    if "final_score" in entry and not _finite_number(entry["final_score"]):
        return False
    if "assigned_models" in entry and not (
        isinstance(entry["assigned_models"], list)
        and len(entry["assigned_models"]) <= 100
        and all(_valid_text(item) for item in entry["assigned_models"])
    ):
        return False
    if "decomposed" in entry and not isinstance(entry["decomposed"], bool):
        return False
    return True


def _valid_provider_status(status: dict) -> bool:
    if set(status) - PROVIDER_STATUS_FIELDS:
        return False
    for field, maximum in (("role", 64), ("name", 128), ("source", 128)):
        if not _valid_optional_public_text(status, field, maximum=maximum):
            return False
    if "model_id" in status and (
        not _valid_text(status["model_id"])
        or project_public_model_id(status["model_id"]) != status["model_id"]
    ):
        return False
    if "api_format" in status and (
        not _valid_text(status["api_format"])
        or project_public_api_format(status["api_format"]) != status["api_format"]
    ):
        return False
    for field in ("ready", "endpoint_configured", "has_api_key"):
        if field in status and not isinstance(status[field], bool):
            return False
    if "missing" in status and not (
        isinstance(status["missing"], list)
        and len(status["missing"]) <= 100
        and all(
            _valid_text(item) and item in {"model_id", "base_url", "api_key", "api_format"}
            for item in status["missing"]
        )
    ):
        return False
    return True


def _valid_model_trace(trace: dict) -> bool:
    if set(trace) - MODEL_TRACE_FIELDS:
        return False
    for field, maximum in (("role", 64), ("model_name", 128)):
        if not _valid_optional_public_text(trace, field, maximum=maximum):
            return False
    if "model_id" in trace and (
        not _valid_text(trace["model_id"])
        or project_public_model_id(trace["model_id"]) != trace["model_id"]
    ):
        return False
    if not _valid_optional_text(trace, "error_kind", nullable=True):
        return False
    if trace.get("error_kind") is not None and (
        project_public_text(trace["error_kind"], maximum=64) != trace["error_kind"]
    ):
        return False
    for field in ("latency_ms", "retry_delay_ms"):
        if field in trace and not _finite_number(trace[field], minimum=0.0):
            return False
    if "attempts" in trace and (
        isinstance(trace["attempts"], bool)
        or not isinstance(trace["attempts"], int)
        or not 0 <= trace["attempts"] <= 1_000
    ):
        return False
    if (
        "status_code" in trace
        and trace["status_code"] is not None
        and (
            isinstance(trace["status_code"], bool)
            or not isinstance(trace["status_code"], int)
            or not 100 <= trace["status_code"] <= 599
        )
    ):
        return False
    if "retry_reasons" in trace and not (
        isinstance(trace["retry_reasons"], list)
        and len(trace["retry_reasons"]) <= 100
        and all(
            _valid_text(item) and project_public_text(item, maximum=64) == item
            for item in trace["retry_reasons"]
        )
    ):
        return False
    if "provider_status" in trace and not (
        isinstance(trace["provider_status"], dict)
        and _valid_provider_status(trace["provider_status"])
    ):
        return False
    return True


def _valid_routing(routing: dict) -> bool:
    allowed = {
        "mode",
        "requested_protocol",
        "selected_protocol",
        "tier",
        "reason",
        "assigned_models",
        "difficulty",
        "decomposed",
    }
    if set(routing) - allowed:
        return False
    for field in ("mode", "requested_protocol", "selected_protocol", "tier", "reason"):
        if not _valid_optional_text(routing, field):
            return False
    if "assigned_models" in routing and not (
        isinstance(routing["assigned_models"], list)
        and len(routing["assigned_models"]) <= 100
        and all(_valid_text(item) for item in routing["assigned_models"])
    ):
        return False
    if "difficulty" in routing and not _finite_number(
        routing["difficulty"], minimum=0.0, maximum=1.0
    ):
        return False
    if "decomposed" in routing and not isinstance(routing["decomposed"], bool):
        return False
    return True


def _valid_metrics(metrics: dict) -> bool:
    return (
        not set(metrics) - METRIC_FIELDS
        and len(metrics) <= 1_000
        and all(_finite_number(value, minimum=0.0) for value in metrics.values())
    )


def validate_session_payload(payload: object) -> bool:
    """Validate current and legacy session artifacts before any consumer sees them."""
    if not isinstance(payload, dict):
        return False
    if set(payload) - SESSION_FIELDS:
        return False
    try:
        if sanitize_json_value(payload) != payload:
            return False
    except (TypeError, ValueError, RecursionError):
        return False

    session_id = payload.get("id")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        return False
    if not _valid_text(payload.get("query"), minimum=1, maximum=50_000):
        return False
    protocol = payload.get("protocol")
    if not isinstance(protocol, str) or protocol not in PROTOCOL_IDS:
        return False
    created_at = payload.get("created_at")
    if not _valid_text(created_at, minimum=1, maximum=64):
        return False
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False

    confidence = payload.get("confidence", 0.0)
    if not _finite_number(confidence, minimum=0.0, maximum=1.0):
        return False
    if not isinstance(payload.get("degraded", False), bool):
        return False
    if "final_answer" in payload and not _valid_text(payload["final_answer"]):
        return False
    if "session_id" in payload and payload["session_id"] != session_id:
        return False

    for field in ("dissent", "warnings"):
        if not _valid_list_of(payload, field, str):
            return False
        if any(not _valid_text(item) for item in payload.get(field, [])):
            return False
    for field in ("stages", "audit_trail", "provider_health", "model_call_traces"):
        if not _valid_list_of(payload, field, dict):
            return False
    if not all(_valid_stage(stage) for stage in payload.get("stages", [])):
        return False
    if not all(_valid_audit_entry(entry) for entry in payload.get("audit_trail", [])):
        return False
    if not all(_valid_provider_status(status) for status in payload.get("provider_health", [])):
        return False
    if not all(_valid_model_trace(trace) for trace in payload.get("model_call_traces", [])):
        return False
    routing = payload.get("routing", {})
    metrics = payload.get("metrics", {})
    if not isinstance(routing, dict) or not _valid_routing(routing):
        return False
    if not isinstance(metrics, dict) or not _valid_metrics(metrics):
        return False
    return True


class SessionStore:
    """Persist one JSON artifact per UUID without exposing arbitrary file paths."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, payload: dict) -> Path:
        clean_payload = sanitize_json_value(payload)
        if not validate_session_payload(clean_payload):
            raise ValueError("session payload does not satisfy the artifact schema")
        session_id = clean_payload["id"]

        destination = self.root / f"{session_id}.json"
        serialized = json.dumps(
            clean_payload,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        serialized_bytes = serialized.encode("utf-8")
        if len(serialized_bytes) > MAX_SESSION_BYTES:
            raise ValueError("serialized session exceeds the maximum artifact size")
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.root,
                prefix=f".{session_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(serialized_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, destination)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        return destination

    def get(self, session_id: str) -> dict | None:
        if not SESSION_ID_RE.fullmatch(session_id):
            return None
        payload = self._read(self.root / f"{session_id}.json")
        if payload is None or payload.get("id") != session_id:
            return None
        return payload

    def find_prefix(self, prefix: str) -> dict | None:
        if not SESSION_PREFIX_RE.fullmatch(prefix):
            return None
        valid_matches: list[dict] = []
        for path in self.root.glob(f"{prefix}*.json"):
            if not SESSION_ID_RE.fullmatch(path.stem):
                continue
            payload = self._read(path)
            session_id = str(payload.get("id", "")) if payload is not None else ""
            if (
                SESSION_ID_RE.fullmatch(session_id)
                and path.stem == session_id
                and session_id.startswith(prefix)
            ):
                valid_matches.append(payload)
        if len(valid_matches) != 1:
            return None
        return valid_matches[0]

    def list_summaries(self, limit: int = 50) -> list[dict]:
        records: list[dict] = []
        for path in self.root.glob("*.json"):
            payload = self._read(path)
            if payload is None:
                continue
            session_id = str(payload.get("id", ""))
            if not SESSION_ID_RE.fullmatch(session_id) or path.stem != session_id:
                continue
            records.append(
                {
                    "id": session_id,
                    "query": str(payload.get("query", ""))[:100],
                    "protocol": str(payload.get("protocol", "unknown")),
                    "created_at": str(payload.get("created_at", "")),
                    "degraded": bool(payload.get("degraded", False)),
                }
            )
        records.sort(key=lambda item: item["created_at"], reverse=True)
        return records[: max(0, min(limit, 100))]

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            if path.stat().st_size > MAX_SESSION_BYTES:
                return None
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_nonstandard_constant,
                parse_float=_parse_finite_float,
            )
        except (OSError, UnicodeError, ValueError, OverflowError, RecursionError):
            return None
        return payload if validate_session_payload(payload) else None
