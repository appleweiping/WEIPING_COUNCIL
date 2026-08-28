"""Specialist Protocol: Route to domain expert, others verify."""
import asyncio

from .base import BaseProtocol
from ..council.session import Session, SessionResult


class SpecialistProtocol(BaseProtocol):
    async def execute(self, session: Session) -> SessionResult:
        result = SessionResult(
            id=session.id, query=session.query,
            protocol="specialist", created_at=session.created_at,
        )

        models = self.config.models
        context = session.context or ""

        # Stage 1: Classify the domain
        classifier = next((m for m in models if m.id == self.config.chairman), models[0])
        classify_msg = [{"role": "user", "content": f"""Classify this query into a domain: "{session.query}"

Available specialists and their strengths:
{chr(10).join(f'- {m.name} ({m.role}): {", ".join(m.strengths)}' for m in models)}

Reply with ONLY the model name that is the best specialist for this query."""}]

        classification = await self.router.query(classifier, classify_msg, context=context)
        result.stages.append({"name": "Domain Classification", "classification": classification})
        result.audit_trail.append({"stage": 1, "action": "classify_domain", "result": classification})

        # Stage 2: Specialist answers
        # Try to match the classified specialist, fall back to first model
        specialist = models[0]
        for m in models:
            if m.name.lower() in classification.lower():
                specialist = m
                break

        specialist_msg = [{"role": "user", "content": f"""You are the designated specialist for this query. Provide a thorough, expert-level answer.

Query: {session.query}"""}]
        specialist_answer = await self.router.query(
            specialist,
            specialist_msg,
            context=context,
        )
        result.stages.append({"name": "Specialist Answer", "specialist": specialist.name, "answer": specialist_answer})
        result.audit_trail.append({"stage": 2, "action": "specialist_answer", "specialist": specialist.id})

        # Stage 3: Verification by others
        verifiers = [m for m in models if m.id != specialist.id][:2]
        verify_msg = [{"role": "user", "content": f"""Verify this specialist answer for accuracy and completeness.

Query: "{session.query}"
Specialist answer: {specialist_answer}

Check for:
1. Factual accuracy
2. Completeness
3. Any missing nuances
4. Overall quality (1-10)

Start with VERIFIED: YES or VERIFIED: NO"""}]

        verifications = dict(await asyncio.gather(*[
            self._query_pair(verifier, verify_msg, context)
            for verifier in verifiers
        ]))

        result.stages.append({"name": "Verification", "verifications": verifications})
        result.final_answer = specialist_answer
        result.confidence = 0.8 if all("VERIFIED: YES" in v.upper() for v in verifications.values()) else 0.5
        result.dissent = [v for v in verifications.values() if "VERIFIED: NO" in v.upper()]
        result.audit_trail.append({"stage": 3, "action": "verification", "verifier_count": len(verifications)})

        return result

    async def _query_pair(
        self,
        model,
        messages: list[dict],
        context: str = "",
    ) -> tuple[str, str]:
        return model.id, await self.router.query(model, messages, context=context)
