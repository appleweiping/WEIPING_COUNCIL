"""FastAPI backend for WEIPING_COUNCIL."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import APP_VERSION, CouncilConfig
from .council.orchestrator import Orchestrator
from .council.session import Session
from .demo import DEMO_QUESTION
from .providers.router import ModelRouter
from .runtime import RuntimeSettings, agentmemory_auth_headers, project_public_text
from .safe_json import sanitize_unicode_scalar
from .session_store import SessionStore

app = FastAPI(title="WEIPING_COUNCIL", version=APP_VERSION)

config = CouncilConfig()
runtime_settings = RuntimeSettings.from_env(config)
app.add_middleware(
    CORSMiddleware,
    allow_origins=runtime_settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
orchestrator = Orchestrator(
    config,
    router=ModelRouter(config, settings=runtime_settings),
)

DATA_DIR = Path(__file__).parent.parent / "data" / "sessions"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROTOCOL_IDS = {
    "auto",
    "council",
    "debate",
    "redteam",
    "consensus",
    "specialist",
    "tournament",
}


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    protocol: str = Field(default="council", min_length=1, max_length=32)
    context: str | None = Field(default=None, max_length=50_000)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value):
        if not isinstance(value, str):
            return value
        normalized = sanitize_unicode_scalar(value).strip()
        if not normalized:
            raise ValueError("query must contain non-whitespace text")
        return normalized

    @field_validator("context", mode="before")
    @classmethod
    def normalize_context(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        return sanitize_unicode_scalar(value).strip() or None

    @field_validator("protocol")
    @classmethod
    def normalize_protocol(cls, value: str) -> str:
        return value.strip().lower()


class QueryResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    session_id: str
    query: str
    protocol: str
    created_at: str
    stages: list[dict]
    final_answer: str
    confidence: float
    dissent: list[str]
    audit_trail: list[dict]
    routing: dict
    metrics: dict
    provider_health: list[dict]
    model_call_traces: list[dict]
    degraded: bool
    warnings: list[str]


async def _health_snapshot() -> dict:
    # Report the immutable settings actually used by CORS and provider calls.
    # Re-reading a changed .env here would make /ready disagree with this process.
    settings = runtime_settings
    providers = settings.provider_status()
    warnings = []
    provider_degraded = any(not provider["ready"] for provider in providers)
    if provider_degraded:
        warnings.append("One or more providers are missing runtime configuration.")

    agentmemory = await _agentmemory_health(
        settings.agentmemory_url,
        settings.agentmemory_secret,
    )
    memory_degraded = agentmemory["configured"] and not agentmemory["ready"]
    if memory_degraded:
        warnings.append("agentmemory is unavailable; context recall is disabled.")

    degraded = provider_degraded or memory_degraded
    return {
        "status": "degraded" if degraded else "ok",
        "version": APP_VERSION,
        "models": len(config.models),
        "providers": providers,
        "runtime_policy": settings.public_policy(),
        "agentmemory": agentmemory,
        "demo": {"question": DEMO_QUESTION} if settings.demo else None,
        "degraded": degraded,
        "warnings": warnings,
    }


@app.get("/api/live")
async def live():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/api/health")
async def health():
    return await _health_snapshot()


@app.get("/api/ready")
async def ready():
    snapshot = await _health_snapshot()
    return JSONResponse(snapshot, status_code=200 if not snapshot["degraded"] else 503)


def _safe_health_token(value, default: str = "unknown") -> str:
    token = project_public_text(value, default=default, maximum=64)
    if not re.fullmatch(r"[A-Za-z0-9._+-]{1,64}", token):
        return default
    return token


async def _agentmemory_health(base_url: str, secret: str = "") -> dict:
    has_auth = bool(secret.strip()) if isinstance(secret, str) else False
    if not base_url:
        return {
            "ready": False,
            "configured": False,
            "has_auth": has_auth,
            "status": "not_configured",
        }
    try:
        headers = agentmemory_auth_headers(base_url, secret)
        async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
            request_kwargs = {"headers": headers} if headers else {}
            response = await client.get(
                f"{base_url.rstrip('/')}/agentmemory/health",
                **request_kwargs,
            )
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("agentmemory health response must be an object")
        status = _safe_health_token(data.get("status"))
        return {
            "ready": response.status_code == 200 and status == "healthy",
            "configured": True,
            "has_auth": has_auth,
            "status": status,
            "version": _safe_health_token(data.get("version"), default="unknown"),
        }
    except Exception as exc:
        return {
            "ready": False,
            "configured": True,
            "has_auth": has_auth,
            "status": "unreachable",
            "error": type(exc).__name__,
        }


@app.get("/api/models")
async def list_models():
    catalog = []
    for model in config.models:
        endpoint = runtime_settings.endpoint_for(model)
        status = endpoint.public_status()
        catalog.append(
            {
                "id": model.id,
                "name": model.name,
                "role": model.role,
                # This is the immutable runtime endpoint model, not the
                # dataclass default. Keep the historical field name for API
                # compatibility while making observability truthful.
                "provider_model": status["model_id"],
                "provider_source": status["source"],
                "api_format": status["api_format"],
                "ready": status["ready"],
                "missing": status["missing"],
                "strengths": model.strengths,
            }
        )
    return catalog


@app.get("/api/protocols")
async def list_protocols():
    return [
        {
            "id": "auto",
            "name": "Auto",
            "description": "Route by complexity with inspectable evidence",
        },
        {
            "id": "council",
            "name": "Council",
            "description": "All models answer, peer review, chairman synthesizes",
        },
        {
            "id": "debate",
            "name": "Debate",
            "description": "Two sides argue opposing positions, judge decides",
        },
        {
            "id": "redteam",
            "name": "Red Team",
            "description": "One model attacks, others defend and find weaknesses",
        },
        {
            "id": "consensus",
            "name": "Consensus",
            "description": "Iterative rounds until agreement threshold met",
        },
        {
            "id": "specialist",
            "name": "Specialist",
            "description": "Route to domain expert, others verify",
        },
        {
            "id": "tournament",
            "name": "Tournament",
            "description": "Bracket elimination, best answer wins",
        },
    ]


@app.post("/api/query", response_model=QueryResponse)
async def submit_query(req: QueryRequest):
    if req.protocol not in PROTOCOL_IDS:
        raise HTTPException(400, f"Unknown protocol: {req.protocol}")

    session = Session(
        id=str(uuid.uuid4()),
        query=req.query,
        protocol=req.protocol,
        context=req.context,
        created_at=datetime.now(UTC).isoformat(),
    )
    result = await orchestrator.run(session)
    payload = result.to_dict()
    SessionStore(DATA_DIR).save(payload)

    return QueryResponse(
        session_id=session.id,
        **payload,
    )


@app.get("/api/sessions")
async def list_sessions():
    return SessionStore(DATA_DIR).list_summaries(limit=50)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    payload = SessionStore(DATA_DIR).get(session_id)
    if payload is None:
        raise HTTPException(404, "Session not found")
    return payload


# Serve the built UI (frontend/dist, from `npm run build`) on the same port so
# `vc serve` is one process. Registered last so /api routes take precedence.
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
