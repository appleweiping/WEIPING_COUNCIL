"""
Self-Refine Engine: generate -> critique -> refine loop.
Based on Madaan et al. (2023). Max 3 iterations, stops early if quality threshold met.
Each iteration: model generates, critic evaluates, model refines based on feedback.
"""
import math
from dataclasses import dataclass, field
from ..config import ModelConfig
from ..providers.router import ModelRouter


@dataclass
class RefineResult:
    original: str
    final: str
    iterations: int
    critiques: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    converged: bool = False


class SelfRefineEngine:
    """Iterative self-refinement: generate -> critique -> refine."""

    def __init__(self, router: ModelRouter, max_iterations: int = 3, quality_threshold: float = 8.0):
        self.router = router
        self.max_iterations = max_iterations
        self.quality_threshold = quality_threshold  # out of 10

    async def refine(
        self,
        generator: ModelConfig,
        critic: ModelConfig,
        query: str,
        initial_response: str,
        context: str = "",
    ) -> RefineResult:
        """Run the refine loop on an initial response."""
        result = RefineResult(original=initial_response, final=initial_response, iterations=0)
        current = initial_response

        for i in range(self.max_iterations):
            # Critique step
            critique, score = await self._critique(critic, query, current, context)
            result.critiques.append(critique)
            result.scores.append(score)

            # Check convergence
            if score >= self.quality_threshold:
                result.converged = True
                result.final = current
                result.iterations = i + 1
                break

            # Refine step
            current = await self._refine(generator, query, current, critique, context)
            result.final = current
            result.iterations = i + 1

        return result

    async def _critique(
        self,
        critic: ModelConfig,
        query: str,
        response: str,
        context: str = "",
    ) -> tuple[str, float]:
        """Critic evaluates the response and provides actionable feedback."""
        prompt = f"""You are a rigorous critic. Evaluate this response to the query.

QUERY: {query}

RESPONSE: {response}

Provide:
1. A quality score (0-10, where 10 is perfect)
2. Specific weaknesses (be precise and actionable)
3. What's missing or could be improved

Format:
SCORE: <number>
CRITIQUE: <your detailed feedback>"""

        result = await self.router.query(
            critic,
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            context=context,
        )

        # Parse score
        score = 5.0
        try:
            for line in result.split("\n"):
                if line.strip().startswith("SCORE:"):
                    score = float(line.split("SCORE:")[1].strip().split()[0])
                    break
        except (ValueError, IndexError):
            pass
        if not math.isfinite(score):
            score = 5.0
        score = max(0.0, min(10.0, score))

        # Extract critique text
        critique = result
        if "CRITIQUE:" in result:
            critique = result.split("CRITIQUE:")[1].strip()

        return critique, score

    async def _refine(
        self,
        generator: ModelConfig,
        query: str,
        current: str,
        critique: str,
        context: str = "",
    ) -> str:
        """Generator improves its response based on critique."""
        prompt = f"""You previously answered this query:

QUERY: {query}

YOUR PREVIOUS ANSWER: {current}

A critic provided this feedback:
{critique}

Now produce an IMPROVED version of your answer that addresses all the critique points.
Keep what was good, fix what was weak, add what was missing.
Respond with ONLY the improved answer, no meta-commentary."""

        return await self.router.query(
            generator,
            [{"role": "user", "content": prompt}],
            temperature=0.5,
            context=context,
        )
