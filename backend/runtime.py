"""Runtime settings, provider readiness, and call trace primitives."""

from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlparse

from dotenv import dotenv_values

from .config import CouncilConfig, ModelConfig


PUBLIC_REDACTED = "...redacted"
_PUBLIC_API_FORMATS = {"anthropic", "openai"}
_PUBLIC_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]*(?:/[A-Za-z0-9][A-Za-z0-9._:+-]*){0,3}")
_PUBLIC_HIGH_RISK_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-(?:or-v1-)?[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"hf_[A-Za-z0-9]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,}|"
    r"AIza[0-9A-Za-z_-]{30,}|hvs\.[A-Za-z0-9_-]{20,}|"
    r"AKIA[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_PUBLIC_CONFIGURED_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"[A-Za-z0-9_.-]*(?:api[_ .-]?key|access[_ .-]?token|client[_ .-]?secret)|"
    r"authorization|password|passwd|passphrase|private[_ .-]?key|secret|token"
    r")[ \t]*[:=][ \t]*[^\s,;]{4,}",
    flags=re.IGNORECASE,
)
_PUBLIC_AUTH_CREDENTIAL = re.compile(
    r"\b(?:Authorization[ \t]*[:=][ \t]*)?(?:Bearer|Basic|Token|ApiKey)[ \t]+"
    r"(?:['\"])?[^\s,'\"]{8,}",
    flags=re.IGNORECASE,
)
_PUBLIC_PRIVATE_ENDPOINT = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"169\.254(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r")(?:\:\d{1,5})?(?![A-Za-z0-9])"
    r"|(?:\[)?(?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f]):[0-9a-f:]+(?:\])?(?::\d{1,5})?"
    r"|(?<![A-Za-z0-9.-])(?:[A-Za-z0-9-]+\.)+(?:internal|local)"
    r"(?::\d{1,5})?(?![A-Za-z0-9.-])",
    flags=re.IGNORECASE,
)
_PUBLIC_URL_USERINFO = re.compile(
    r"(?:\b[A-Za-z][A-Za-z0-9+.-]*:)?//[^\s/@?#]+@",
    flags=re.IGNORECASE,
)
_PUBLIC_PRIVATE_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9+.:_\\/-])(?:"
    r"[A-Za-z]:[\\/]"
    r"|\\\\[^\s\\/]+[\\/][^\s\\/]+(?:[\\/]|$)"
    r"|/(?!/)[^\s/]+(?:/|$)"
    r"))",
    flags=re.IGNORECASE,
)


def _role_env(role: str) -> str:
    return role.upper().replace("-", "_")


def _runtime_text(value: object, default: str = "") -> str:
    """Normalize one configured scalar without ever logging its contents."""
    return value.strip() if isinstance(value, str) else default


def _valid_runtime_base_url(base_url: str, *, carries_credential: bool) -> bool:
    try:
        parsed = urlparse(_runtime_text(base_url))
        hostname = parsed.hostname or ""
        # Accessing port validates malformed bracket/port syntax as well.
        parsed.port
    except (TypeError, ValueError):
        return False
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        return False
    if not carries_credential or parsed.scheme.lower() == "https":
        return True
    loopback = hostname.lower() == "localhost"
    try:
        loopback = loopback or ip_address(hostname).is_loopback
    except ValueError:
        pass
    return loopback


def agentmemory_auth_headers(base_url: str, secret: str) -> dict[str, str]:
    """Build optional auth headers only for a confidential transport."""
    normalized_secret = _runtime_text(secret)
    if not _valid_runtime_base_url(
        base_url,
        # Durable memory, project metadata, rules, and the search query are
        # confidential even when the service accepts anonymous requests.
        carries_credential=True,
    ):
        raise ValueError("agentmemory transport requires HTTPS or a loopback URL")
    if not normalized_secret:
        return {}
    return {"Authorization": f"Bearer {normalized_secret}"}


def _public_detection_shadows(value: str) -> tuple[str, ...]:
    """Return bounded normalized/URL-decoded views for fail-closed inspection."""
    shadows: list[str] = []
    candidate = unicodedata.normalize("NFKC", value)
    for _ in range(8):
        if candidate not in shadows:
            shadows.append(candidate)
        decoded = unicodedata.normalize("NFKC", unquote(candidate))
        if decoded == candidate:
            break
        candidate = decoded
    return tuple(shadows)


def _looks_like_high_entropy_secret(value: str) -> bool:
    for segment in re.split(r"[/.:_-]+", value):
        # Public model slugs normally carry semantic separators. A long opaque
        # alphanumeric segment is indistinguishable from common token material,
        # so public observability fails closed regardless of character classes.
        if len(segment) >= 32 and segment.isalnum():
            return True
    return False


def _public_value_is_sensitive(value: str) -> bool:
    for shadow in _public_detection_shadows(value):
        if (
            _PUBLIC_HIGH_RISK_TOKEN.search(shadow)
            or _PUBLIC_CONFIGURED_CREDENTIAL.search(shadow)
            or _PUBLIC_AUTH_CREDENTIAL.search(shadow)
            or _PUBLIC_PRIVATE_ENDPOINT.search(shadow)
            or _PUBLIC_URL_USERINFO.search(shadow)
            or _PUBLIC_PRIVATE_PATH.search(shadow)
            or "".join(("BEGIN ", "PRIVATE ", "KEY")) in shadow.upper()
            or _looks_like_high_entropy_secret(shadow)
        ):
            return True
    return False


def project_public_text(
    value: object,
    *,
    default: str = PUBLIC_REDACTED,
    maximum: int = 256,
) -> str:
    """Project a short runtime label without exposing secret or private-endpoint material."""
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text:
        return ""
    if len(text) > maximum or any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in text
    ):
        return default
    if _public_value_is_sensitive(text):
        return default
    return text


def project_public_model_id(value: object) -> str:
    """Return a provider model slug only when its complete scalar is public-safe."""
    projected = project_public_text(value, maximum=256)
    if projected in {"", PUBLIC_REDACTED}:
        return projected
    if _PUBLIC_MODEL_ID.fullmatch(projected) is None:
        return PUBLIC_REDACTED
    return projected


def project_public_api_format(value: object) -> str:
    """Expose only supported API-format identifiers, never an invalid raw value."""
    normalized = _runtime_text(value).casefold()
    return normalized if normalized in _PUBLIC_API_FORMATS else "invalid"


def project_public_provider_status(status: Mapping[str, object]) -> dict:
    """Apply the same projection to endpoint and trace provider-status records."""
    if not isinstance(status, Mapping):
        status = {}
    missing = status.get("missing", [])
    safe_missing = (
        [
            item
            for item in missing
            if isinstance(item, str) and item in {"model_id", "base_url", "api_key", "api_format"}
        ]
        if isinstance(missing, list)
        else []
    )
    return {
        "role": project_public_text(status.get("role"), default="unknown", maximum=64),
        "name": project_public_text(status.get("name"), default="unknown", maximum=128),
        "model_id": project_public_model_id(status.get("model_id")),
        "endpoint_configured": status.get("endpoint_configured") is True,
        "api_format": project_public_api_format(status.get("api_format")),
        "source": project_public_text(status.get("source"), default="unknown", maximum=128),
        "ready": status.get("ready") is True,
        "has_api_key": status.get("has_api_key") is True,
        "missing": safe_missing,
    }


def _bounded_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(
    value: str | None,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(minimum, min(maximum, parsed))


def merged_runtime_env(
    env: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = None,
) -> Mapping[str, str]:
    """Return runtime env with process values taking priority over one exact .env.

    The default path is anchored to this project's root.  In particular, it never
    searches parent directories where another checkout's private configuration may
    live.  Tests and embedders may provide an explicit path.
    """
    if env is not None:
        return env

    resolved_dotenv = (
        Path(dotenv_path)
        if dotenv_path is not None
        else Path(__file__).resolve().parents[1] / ".env"
    )
    dotenv_env = {
        key: value
        for key, value in (
            dotenv_values(resolved_dotenv) if resolved_dotenv.is_file() else {}
        ).items()
        if value is not None
    }
    return {**dotenv_env, **os.environ}


@dataclass(frozen=True)
class ProviderEndpoint:
    role: str
    model_name: str
    model_id: str = field(repr=False)
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    api_format: str = field(repr=False)
    source: str

    @property
    def valid_base_url(self) -> bool:
        return _valid_runtime_base_url(
            self.base_url,
            carries_credential=bool(_runtime_text(self.api_key)),
        )

    @property
    def valid_api_format(self) -> bool:
        return self.api_format in _PUBLIC_API_FORMATS

    @property
    def ready(self) -> bool:
        return bool(
            _runtime_text(self.model_id)
            and self.valid_base_url
            and _runtime_text(self.api_key)
            and self.valid_api_format
        )

    @property
    def missing(self) -> list[str]:
        fields = []
        if not _runtime_text(self.model_id):
            fields.append("model_id")
        if not self.valid_base_url:
            fields.append("base_url")
        if not _runtime_text(self.api_key):
            fields.append("api_key")
        if not self.valid_api_format:
            fields.append("api_format")
        return fields

    def public_status(self) -> dict:
        return project_public_provider_status(
            {
                "role": self.role,
                "name": self.model_name,
                "model_id": self.model_id,
                "endpoint_configured": self.valid_base_url,
                "api_format": self.api_format,
                "source": self.source,
                "ready": self.ready,
                "has_api_key": bool(_runtime_text(self.api_key)),
                "missing": self.missing,
            }
        )


@dataclass
class ModelCallTrace:
    role: str
    model_name: str
    model_id: str
    provider_status: dict
    latency_ms: float = 0.0
    attempts: int = 0
    error_kind: str | None = None
    status_code: int | None = None
    retry_delay_ms: float = 0.0
    retry_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "role": project_public_text(self.role, default="unknown", maximum=64),
            "model_name": project_public_text(self.model_name, default="unknown", maximum=128),
            "model_id": project_public_model_id(self.model_id),
            "provider_status": project_public_provider_status(self.provider_status),
            "latency_ms": round(self.latency_ms, 2),
            "attempts": self.attempts,
            "error_kind": (
                project_public_text(self.error_kind, default="unknown", maximum=64)
                if self.error_kind is not None
                else None
            ),
            "status_code": self.status_code,
            "retry_delay_ms": round(self.retry_delay_ms, 2),
            "retry_reasons": [
                project_public_text(reason, default="unknown", maximum=64)
                for reason in self.retry_reasons[:100]
            ],
        }


@dataclass
class RuntimeSettings:
    endpoints: dict[str, ProviderEndpoint] = field(default_factory=dict)
    agentmemory_url: str = "http://localhost:3111"
    agentmemory_secret: str = field(default="", repr=False)
    cors_origins: list[str] = field(default_factory=list)
    provider_timeout_seconds: float = 120.0
    provider_max_attempts: int = 3
    provider_backoff_base_seconds: float = 0.5
    provider_backoff_max_seconds: float = 8.0
    provider_max_concurrency: int = 8

    @classmethod
    def from_env(
        cls,
        config: CouncilConfig,
        env: Mapping[str, str] | None = None,
        dotenv_path: str | Path | None = None,
    ) -> "RuntimeSettings":
        source_env = merged_runtime_env(env, dotenv_path=dotenv_path)
        endpoints = {}
        for model in config.models:
            role_key = _role_env(model.role)
            shared = {
                "model_id": _runtime_text(source_env.get("OPENROUTER_MODEL")),
                "base_url": _runtime_text(
                    source_env.get("OPENROUTER_BASE_URL"), config.openrouter_base_url
                ),
                "api_key": _runtime_text(source_env.get("OPENROUTER_API_KEY")),
                "api_format": _runtime_text(source_env.get("OPENROUTER_API_FORMAT"), "openai"),
            }
            base = shared
            source = "OPENROUTER_*"
            deepseek_api_key = _runtime_text(source_env.get("DEEPSEEK_API_KEY"))
            if model.role == "bulk-worker" and deepseek_api_key:
                base = {
                    "model_id": _runtime_text(source_env.get("DEEPSEEK_MODEL")),
                    "base_url": _runtime_text(
                        source_env.get("DEEPSEEK_BASE_URL"), "https://api.deepseek.com/v1"
                    ),
                    "api_key": deepseek_api_key,
                    "api_format": _runtime_text(source_env.get("DEEPSEEK_API_FORMAT"), "openai"),
                }
                source = "DEEPSEEK_*"
            model_id_fallback = "deepseek-chat" if source == "DEEPSEEK_*" else model.provider_model

            role_overrides = {
                "model_id": _runtime_text(source_env.get(f"VC_PROVIDER_{role_key}_MODEL")),
                "base_url": _runtime_text(source_env.get(f"VC_PROVIDER_{role_key}_BASE_URL")),
                "api_key": _runtime_text(source_env.get(f"VC_PROVIDER_{role_key}_API_KEY")),
                "api_format": _runtime_text(source_env.get(f"VC_PROVIDER_{role_key}_FORMAT")),
            }
            if any(role_overrides.values()):
                source = f"{source} + VC_PROVIDER_{role_key}_*"
            resolved = {field: role_overrides[field] or value for field, value in base.items()}

            endpoints[model.role] = ProviderEndpoint(
                role=model.role,
                model_name=model.name,
                model_id=resolved["model_id"] or model_id_fallback,
                base_url=resolved["base_url"] or "",
                api_key=resolved["api_key"] or "",
                api_format=(resolved["api_format"] or "openai").lower(),
                source=source,
            )

        cors_origins = [
            item.strip()
            for item in _runtime_text(
                source_env.get("VC_CORS_ORIGINS"),
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if item.strip()
        ]

        return cls(
            endpoints=endpoints,
            agentmemory_url=_runtime_text(
                source_env.get("AGENTMEMORY_URL"), "http://localhost:3111"
            ),
            agentmemory_secret=_runtime_text(source_env.get("AGENTMEMORY_SECRET")),
            cors_origins=cors_origins,
            provider_timeout_seconds=_bounded_float(
                source_env.get("VC_PROVIDER_TIMEOUT_SECONDS"), 120.0, 1.0, 600.0
            ),
            provider_max_attempts=_bounded_int(source_env.get("VC_PROVIDER_MAX_ATTEMPTS"), 3, 1, 6),
            provider_backoff_base_seconds=_bounded_float(
                source_env.get("VC_PROVIDER_BACKOFF_BASE_SECONDS"), 0.5, 0.0, 30.0
            ),
            provider_backoff_max_seconds=_bounded_float(
                source_env.get("VC_PROVIDER_BACKOFF_MAX_SECONDS"), 8.0, 0.0, 120.0
            ),
            provider_max_concurrency=_bounded_int(
                source_env.get("VC_PROVIDER_MAX_CONCURRENCY"), 8, 1, 64
            ),
        )

    def endpoint_for(self, model: ModelConfig) -> ProviderEndpoint:
        return self.endpoints.get(
            model.role,
            ProviderEndpoint(
                role=model.role,
                model_name=model.name,
                model_id=model.provider_model,
                base_url="",
                api_key="",
                api_format="openai",
                source="unconfigured",
            ),
        )

    def provider_status(self) -> list[dict]:
        return [endpoint.public_status() for endpoint in self.endpoints.values()]

    def degraded(self) -> bool:
        return not all(endpoint.ready for endpoint in self.endpoints.values())

    def public_policy(self) -> dict:
        """Return safe execution policy metadata without endpoint or credential values."""
        return {
            "timeout_seconds": self.provider_timeout_seconds,
            "max_attempts": self.provider_max_attempts,
            "max_concurrency": self.provider_max_concurrency,
        }
