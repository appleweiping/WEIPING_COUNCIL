"""Council configuration."""

from dataclasses import dataclass, field

APP_VERSION = "2.4.1"


@dataclass
class ModelConfig:
    id: str
    name: str
    role: str = "generalist"
    provider: str = "openrouter"
    provider_model: str = "openai/gpt-5.5"
    strengths: list[str] = field(default_factory=list)
    cost_per_1k: float = 0.0


@dataclass
class CouncilConfig:
    models: list[ModelConfig] = field(
        default_factory=lambda: [
            ModelConfig(
                id="architect",
                name="Opus",
                role="architect",
                provider="openrouter",
                provider_model="openai/gpt-5.5",
                strengths=["architecture", "complex-reasoning", "paper-writing", "security-audit"],
            ),
            ModelConfig(
                id="coordinator",
                name="Codex",
                role="coordinator",
                provider="openrouter",
                provider_model="openai/gpt-5.5",
                strengths=["parallel-execution", "server-commands", "fast-iteration", "bulk-work"],
            ),
            ModelConfig(
                id="implementer",
                name="OpenCode",
                role="implementer",
                provider="openrouter",
                provider_model="openai/gpt-5.5",
                strengths=["implementation", "testing", "doc-updates", "code-review"],
            ),
            ModelConfig(
                id="reviewer",
                name="Sonnet",
                role="reviewer",
                provider="openrouter",
                provider_model="openai/gpt-5.5",
                strengths=["code-review", "table-eligibility", "verification", "quality-gate"],
            ),
            ModelConfig(
                id="speedster",
                name="Haiku",
                role="speedster",
                provider="openrouter",
                provider_model="openai/gpt-5.5",
                strengths=["lint", "format-check", "pre-screening", "fast-triage"],
            ),
            ModelConfig(
                id="bulk-worker",
                name="DeepSeek",
                role="bulk-worker",
                provider="openrouter",
                provider_model="deepseek/deepseek-chat",
                strengths=["translation", "bulk-text", "chinese-content", "long-generation"],
            ),
        ]
    )
    chairman: str = "architect"
    default_protocol: str = "council"
    confidence_threshold: float = 0.7
    consensus_rounds_max: int = 5
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
