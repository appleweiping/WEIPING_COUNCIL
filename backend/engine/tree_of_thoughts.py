"""
Tree of Thoughts: Beam search with voting evaluation.
Based on Yao et al. (2023). Generates multiple candidate thoughts,
evaluates them via voting, keeps top-k, expands further.
"""
import math
from dataclasses import dataclass, field
from ..config import CouncilConfig, ModelConfig
from ..providers.router import ModelRouter


@dataclass
class Thought:
    content: str
    score: float = 0.0
    votes: dict[str, float] = field(default_factory=dict)
    depth: int = 0
    parent: str = ""


@dataclass
class ToTResult:
    best_thought: str
    beam: list[Thought]
    total_candidates: int
    depth_reached: int
    vote_history: list[dict] = field(default_factory=list)


class TreeOfThoughts:
    """Beam search over thought candidates with multi-model voting."""

    def __init__(self, config: CouncilConfig, router: ModelRouter,
                 beam_width: int = 5, max_depth: int = 3, vote_samples: int = 3):
        self.config = config
        self.router = router
        self.beam_width = beam_width
        self.max_depth = max_depth
        self.vote_samples = vote_samples

    async def search(self, query: str, generators: list[ModelConfig],
                     evaluators: list[ModelConfig]) -> ToTResult:
        """Run beam search with voting evaluation."""
        # Initial generation: each generator produces a candidate
        candidates = await self._generate_initial(query, generators)
        total_candidates = len(candidates)
        depth = 0

        vote_history = []

        for d in range(self.max_depth):
            depth = d + 1

            # Evaluate all candidates via voting
            scored = await self._evaluate_candidates(query, candidates, evaluators)
            vote_history.append({
                "depth": depth,
                "candidates": len(scored),
                "scores": [(t.content[:50], t.score) for t in scored]
            })

            # Keep top-k (beam)
            scored.sort(key=lambda t: t.score, reverse=True)
            beam = scored[:self.beam_width]

            # Check if top candidate is good enough (score > 8.5)
            if beam[0].score >= 8.5:
                break

            # Expand: generate refinements of top candidates
            if d < self.max_depth - 1:
                expanded = await self._expand(query, beam, generators)
                candidates = beam + expanded
                total_candidates += len(expanded)
            else:
                candidates = beam

        # Final beam
        candidates.sort(key=lambda t: t.score, reverse=True)
        best = candidates[0] if candidates else Thought(content="No result")

        return ToTResult(
            best_thought=best.content,
            beam=candidates[:self.beam_width],
            total_candidates=total_candidates,
            depth_reached=depth,
            vote_history=vote_history,
        )

    async def _generate_initial(self, query: str, generators: list[ModelConfig]) -> list[Thought]:
        """Each generator produces an initial thought."""
        thoughts = []
        for gen in generators:
            prompt = f"""Think step by step about this problem. Provide your best answer.

{query}

Be thorough but concise. Focus on accuracy and insight."""
            response = await self.router.query(gen, [{"role": "user", "content": prompt}])
            thoughts.append(Thought(content=response, depth=0))
        return thoughts

    async def _evaluate_candidates(self, query: str, candidates: list[Thought],
                                    evaluators: list[ModelConfig]) -> list[Thought]:
        """Multi-model voting on candidates."""
        for candidate in candidates:
            votes = {}
            for evaluator in evaluators[:self.vote_samples]:
                score = await self._vote(evaluator, query, candidate.content)
                votes[evaluator.id] = score
            candidate.votes = votes
            candidate.score = sum(votes.values()) / len(votes) if votes else 0.0
        return candidates

    async def _vote(self, evaluator: ModelConfig, query: str, candidate: str) -> float:
        """Single evaluator scores a candidate (0-10)."""
        prompt = f"""Rate this answer to the query on a scale of 0-10.

QUERY: {query}
ANSWER: {candidate}

Consider: accuracy, completeness, insight, clarity.
Respond with ONLY a number 0-10."""

        response = await self.router.query(evaluator, [{"role": "user", "content": prompt}], temperature=0.1)
        try:
            score = float(response.strip().split()[0])
        except (ValueError, IndexError):
            return 5.0
        if not math.isfinite(score):
            return 5.0
        return max(0.0, min(10.0, score))

    async def _expand(self, query: str, beam: list[Thought],
                      generators: list[ModelConfig]) -> list[Thought]:
        """Expand top candidates into refined versions."""
        expanded = []
        for thought in beam[:3]:  # Expand top 3
            gen = generators[len(expanded) % len(generators)]
            prompt = f"""Here is a partial answer to: {query}

CURRENT ANSWER: {thought.content}

Improve this answer. Make it more accurate, complete, and insightful.
Address any weaknesses you see. Respond with the improved version only."""
            response = await self.router.query(gen, [{"role": "user", "content": prompt}])
            expanded.append(Thought(content=response, depth=thought.depth + 1, parent=thought.content[:50]))
        return expanded
