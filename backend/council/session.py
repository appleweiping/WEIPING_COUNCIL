"""Session data model."""

from dataclasses import dataclass, field

from ..safe_json import sanitize_json_value


@dataclass
class Session:
    id: str
    query: str
    protocol: str
    context: str | None = None
    created_at: str = ""


@dataclass
class SessionResult:
    id: str
    query: str
    protocol: str
    created_at: str
    stages: list[dict] = field(default_factory=list)
    final_answer: str = ""
    confidence: float = 0.0
    dissent: list[str] = field(default_factory=list)
    audit_trail: list[dict] = field(default_factory=list)
    routing: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    provider_health: list[dict] = field(default_factory=list)
    model_call_traces: list[dict] = field(default_factory=list)
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return sanitize_json_value(
            {
                "id": self.id,
                "query": self.query,
                "protocol": self.protocol,
                "created_at": self.created_at,
                "stages": self.stages,
                "final_answer": self.final_answer,
                "confidence": self.confidence,
                "dissent": self.dissent,
                "audit_trail": self.audit_trail,
                "routing": self.routing,
                "metrics": self.metrics,
                "provider_health": self.provider_health,
                "model_call_traces": self.model_call_traces,
                "degraded": self.degraded,
                "warnings": self.warnings,
            }
        )
