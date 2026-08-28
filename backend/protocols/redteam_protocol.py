"""Red Team Protocol: One model attacks, others defend and find weaknesses."""
import asyncio

from .base import BaseProtocol
from ..council.session import Session, SessionResult


class RedTeamProtocol(BaseProtocol):
    async def execute(self, session: Session) -> SessionResult:
        result = SessionResult(
            id=session.id, query=session.query,
            protocol="redteam", created_at=session.created_at,
        )

        models = self.config.models
        if len(models) < 2:
            result.final_answer = "Need at least 2 models for red team protocol."
            return result

        attacker = next((m for m in models if m.role in {"critic", "reviewer"}), models[0])
        defenders = [m for m in models if m.id != attacker.id]
        context = session.context or ""

        # Stage 1: Defenders propose an answer
        defend_msg = [{"role": "user", "content": session.query}]
        defender_pairs = await asyncio.gather(*[
            self._query_pair(defender, defend_msg, context)
            for defender in defenders
        ])
        defender_responses = dict(defender_pairs)

        result.stages.append({"name": "Defender Proposals", "responses": defender_responses})

        # Stage 2: Attacker critiques
        combined = "\n\n".join(f"[{did}]: {resp}" for did, resp in defender_responses.items())
        attack_msg = [{"role": "user", "content": f"""You are a red team attacker. Find every weakness, flaw, logical error, and vulnerability in these responses to: "{session.query}"

Responses:
{combined}

Be ruthless. Find:
1. Logical fallacies
2. Missing considerations
3. Incorrect assumptions
4. Edge cases not handled
5. Potential failure modes"""}]

        attack_response = await self.router.query(attacker, attack_msg, context=context)
        result.stages.append({"name": "Red Team Attack", "attacker": attacker.name, "critique": attack_response})

        # Stage 3: Defenders respond to critique
        final_msg = [{"role": "user", "content": f"""The red team found these weaknesses in your answer to "{session.query}":

{attack_response}

Provide an improved answer that addresses these critiques."""}]

        improved = {}
        improved_pairs = await asyncio.gather(*[
            self._query_pair(defender, final_msg, context)
            for defender in defenders[:2]
        ])
        improved = dict(improved_pairs)

        result.stages.append({"name": "Improved Responses", "responses": improved})
        result.final_answer = list(improved.values())[0] if improved else "No improved response generated."
        result.confidence = 0.6
        result.dissent = [attack_response[:500]]
        result.audit_trail = [
            {"stage": 1, "action": "defender_proposals", "count": len(defender_responses)},
            {"stage": 2, "action": "red_team_attack", "attacker": attacker.id},
            {"stage": 3, "action": "improved_responses", "count": len(improved)},
        ]

        return result

    async def _query_pair(
        self,
        model,
        messages: list[dict],
        context: str = "",
    ) -> tuple[str, str]:
        return model.id, await self.router.query(model, messages, context=context)
