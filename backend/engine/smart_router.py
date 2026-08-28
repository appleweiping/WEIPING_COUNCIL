"""
Smart Router: RouteLLM-inspired difficulty classification and model routing.
Simple queries go to fast/cheap models. Complex queries go to full council.
Threshold calibrated at ~0.12 for 50/50 split (adjustable).
"""

import math
import re
from dataclasses import dataclass
from ..config import CouncilConfig, ModelConfig
from ..providers.router import ModelRouter, is_provider_error_result


@dataclass
class RoutingDecision:
    difficulty: float  # 0.0 (trivial) to 1.0 (extremely complex)
    tier: str  # "fast", "standard", "full_council"
    assigned_models: list[str]
    reason: str


# Complexity signals (heuristic pre-filter before LLM classification)
COMPLEXITY_KEYWORDS = {
    "high": [
        "compare",
        "tradeoff",
        "debate",
        "analyze",
        "design",
        "architect",
        "prove",
        "derive",
        "optimize",
        "security",
        "vulnerability",
        "novel",
    ],
    "low": [
        "what is",
        "define",
        "list",
        "how to",
        "simple",
        "basic",
        "hello",
        "translate",
        "summarize",
        "format",
        "convert",
    ],
}


class SmartRouter:
    """Routes queries to appropriate model tier based on difficulty."""

    def __init__(self, config: CouncilConfig, router: ModelRouter):
        self.config = config
        self.router = router
        self.threshold_fast = 0.25  # Below this → fast tier (Haiku only)
        self.threshold_standard = 0.6  # Below this → standard (single strong model)
        # Above threshold_standard → full council

    async def classify(self, query: str) -> RoutingDecision:
        """Classify query difficulty and route to appropriate tier."""
        # Stage 1: Heuristic pre-filter (instant, no API call)
        heuristic_score = self._heuristic_score(query)

        # If clearly simple or clearly complex, skip LLM classification
        if heuristic_score < 0.15:
            return RoutingDecision(
                difficulty=heuristic_score,
                tier="fast",
                assigned_models=[self._get_fast_model().id],
                reason="Heuristic: simple query detected",
            )

        if heuristic_score > 0.85:
            return RoutingDecision(
                difficulty=heuristic_score,
                tier="full_council",
                assigned_models=[m.id for m in self.config.models],
                reason="Heuristic: highly complex query detected",
            )

        # Stage 2: LLM-based classification (use cheapest model)
        classifier = self._get_fast_model()
        score, classifier_evidence = await self._llm_classify(classifier, query)

        if score < self.threshold_fast:
            return RoutingDecision(
                difficulty=score,
                tier="fast",
                assigned_models=[classifier.id],
                reason=(f"{classifier_evidence}: difficulty {score:.2f} < {self.threshold_fast}"),
            )
        elif score < self.threshold_standard:
            best = self._get_best_model()
            return RoutingDecision(
                difficulty=score,
                tier="standard",
                assigned_models=[best.id],
                reason=(f"{classifier_evidence}: difficulty {score:.2f}, routed to {best.name}"),
            )
        else:
            return RoutingDecision(
                difficulty=score,
                tier="full_council",
                assigned_models=[m.id for m in self.config.models],
                reason=(
                    f"{classifier_evidence}: difficulty {score:.2f} >= {self.threshold_standard}"
                ),
            )

    def _heuristic_score(self, query: str) -> float:
        """Fast heuristic scoring without API calls."""
        query_lower = query.lower()
        score = 0.5  # neutral baseline

        # Length signal
        word_count = len(query.split())
        if word_count < 8:
            score -= 0.15
        elif word_count > 50:
            score += 0.15

        # Keyword signals
        for kw in COMPLEXITY_KEYWORDS["high"]:
            if kw in query_lower:
                score += 0.1
        for kw in COMPLEXITY_KEYWORDS["low"]:
            if kw in query_lower:
                score -= 0.1

        # Multi-part questions
        if "?" in query and query.count("?") > 1:
            score += 0.1
        if any(c in query for c in ["1.", "2.", "3.", "a)", "b)"]):
            score += 0.1

        # Code/math signals
        if re.search(r"```|def |class |import |SELECT |O\(n", query):
            score += 0.15

        return max(0.0, min(1.0, score))

    async def _llm_classify(self, model: ModelConfig, query: str) -> tuple[float, str]:
        """Use a cheap LLM to classify difficulty (0-1)."""
        prompt = f"""Rate the difficulty of answering this query on a scale of 0.0 to 1.0.
0.0 = trivial (simple fact, definition, translation)
0.5 = moderate (requires some reasoning or domain knowledge)
1.0 = extremely complex (multi-step reasoning, novel analysis, expert-level)

Query: "{query}"

Respond with ONLY a number between 0.0 and 1.0, nothing else."""

        response = await self.router.query(
            model, [{"role": "user", "content": prompt}], temperature=0.0
        )
        if is_provider_error_result(response):
            return 0.5, "Classifier unavailable; neutral fallback"

        try:
            score = float(response.strip())
        except ValueError:
            # Extract the first finite-looking number from a verbose response.
            match = re.search(r"(\d+\.?\d*)", response)
            if match is None:
                return 0.5, "Classifier output unparseable; neutral fallback"
            score = float(match.group(1))

        # Provider output is untrusted. Non-finite or out-of-range values would
        # otherwise produce invalid JSON route evidence or dishonest difficulty.
        if not math.isfinite(score):
            return 0.5, "Classifier output non-finite; neutral fallback"
        normalized_score = max(0.0, min(1.0, score))
        evidence = "LLM classifier"
        if normalized_score != score:
            evidence = "LLM classifier output clamped"
        return normalized_score, evidence

    def _get_fast_model(self) -> ModelConfig:
        """Get the fastest/cheapest model (Haiku)."""
        for m in self.config.models:
            if m.role == "speedster":
                return m
        return self.config.models[-1]

    def _get_best_model(self) -> ModelConfig:
        """Get the strongest single model (Opus)."""
        for m in self.config.models:
            if m.role == "architect":
                return m
        return self.config.models[0]
