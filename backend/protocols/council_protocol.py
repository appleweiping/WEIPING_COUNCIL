"""Council Protocol: Classic multi-LLM deliberation (Karpathy-style + enhancements)."""
import asyncio
import math
from .base import BaseProtocol
from ..council.session import Session, SessionResult


class CouncilProtocol(BaseProtocol):
    """
    Three-stage council:
    1. Independent opinions from all models
    2. Peer review: each model reviews others (anonymized)
    3. Chairman synthesis with confidence scoring
    """

    async def execute(self, session: Session) -> SessionResult:
        result = SessionResult(
            id=session.id, query=session.query,
            protocol="council", created_at=session.created_at,
        )
        context = session.context or ""

        # Stage 1: First opinions
        messages = [{"role": "user", "content": session.query}]
        opinions = await self._gather_opinions(messages, context)
        result.stages.append({"name": "First Opinions", "responses": opinions})
        result.audit_trail.append({"stage": 1, "action": "gather_opinions", "model_count": len(opinions)})

        # Stage 2: Peer review
        reviews = await self._peer_review(session.query, opinions, context)
        result.stages.append({"name": "Peer Review", "reviews": reviews})
        result.audit_trail.append({"stage": 2, "action": "peer_review", "review_count": len(reviews)})

        # Stage 3: Chairman synthesis
        final, confidence, dissent = await self._chairman_synthesis(
            session.query,
            opinions,
            reviews,
            context,
        )
        result.final_answer = final
        result.confidence = confidence
        result.dissent = dissent
        evidence_confidence = (
            confidence
            if math.isfinite(confidence) and 0.0 <= confidence <= 1.0
            else None
        )
        result.stages.append({
            "name": "Chairman Synthesis",
            "final": final,
            "confidence": evidence_confidence,
        })
        result.audit_trail.append({
            "stage": 3,
            "action": "synthesis",
            "confidence": evidence_confidence,
            "dissent_count": len(dissent),
        })

        return result

    async def _gather_opinions(self, messages: list[dict], context: str = "") -> dict[str, str]:
        return await self.router.query_all(messages, context=context)

    async def _peer_review(
        self,
        query: str,
        opinions: dict[str, str],
        context: str = "",
    ) -> dict[str, dict]:
        model_ids = list(opinions.keys())

        async def review_one(reviewer_id: str) -> tuple[str, dict]:
            reviewer = next((m for m in self.config.models if m.id == reviewer_id), self.config.models[0])
            other_responses = [
                f"Response {chr(65+i)}: {resp}"
                for i, (mid, resp) in enumerate(opinions.items())
                if mid != reviewer_id
            ]
            review_prompt = f"""You are reviewing responses to this query: "{query}"

Here are the anonymized responses from other council members:

{chr(10).join(other_responses)}

Rank these responses from best to worst. For each, give:
1. A score (1-10)
2. Key strengths
3. Key weaknesses
4. Whether you agree or disagree with the conclusion

Be honest and critical. Your identity is hidden from the other reviewers."""

            review = await self.router.query(
                reviewer,
                [{"role": "user", "content": review_prompt}],
                context=context,
            )
            return reviewer_id, {"review": review}

        pairs = await asyncio.gather(*[review_one(rid) for rid in model_ids])
        return dict(pairs)

    async def _chairman_synthesis(
        self,
        query: str,
        opinions: dict,
        reviews: dict,
        context: str = "",
    ) -> tuple[str, float, list[str]]:
        chairman = next((m for m in self.config.models if m.id == self.config.chairman), self.config.models[0])

        synthesis_prompt = f"""You are the Chairman of the LLM Council. Your job is to produce the definitive answer.

Original query: "{query}"

Council member responses:
{chr(10).join(f'[{mid}]: {resp}' for mid, resp in opinions.items())}

Peer reviews:
{chr(10).join(f'[{mid}]: {r["review"]}' for mid, r in reviews.items())}

Produce:
1. The best possible answer, synthesizing the strongest points from all responses
2. A confidence score (0.0 to 1.0) for how certain the council is
3. Any dissenting opinions that should be noted (important disagreements)

Format your response as:
ANSWER: <your synthesized answer>
CONFIDENCE: <0.0-1.0>
DISSENT: <any notable disagreements, or "none">"""

        response = await self.router.query(
            chairman,
            [{"role": "user", "content": synthesis_prompt}],
            context=context,
        )

        # Parse response
        confidence = 0.7
        dissent = []
        answer = response

        if "CONFIDENCE:" in response:
            parts = response.split("CONFIDENCE:")
            answer = parts[0].replace("ANSWER:", "").strip()
            rest = parts[1]
            try:
                conf_line = rest.split("\n")[0].strip()
                confidence = float(conf_line)
            except (ValueError, IndexError):
                pass
            if "DISSENT:" in rest:
                dissent_text = rest.split("DISSENT:")[1].strip()
                if dissent_text.lower() != "none":
                    dissent = [dissent_text]

        return answer, confidence, dissent
