"""Consensus Protocol: Iterative rounds until agreement threshold met."""
import asyncio

from .base import BaseProtocol
from ..council.session import Session, SessionResult


class ConsensusProtocol(BaseProtocol):
    async def execute(self, session: Session) -> SessionResult:
        result = SessionResult(
            id=session.id, query=session.query,
            protocol="consensus", created_at=session.created_at,
        )

        models = self.config.models
        max_rounds = self.config.consensus_rounds_max
        threshold = self.config.confidence_threshold
        agreement_ratio = 0.0  # initialise before loop so it's always defined
        context = session.context or ""

        # Round 1: Initial responses
        messages = [{"role": "user", "content": session.query}]
        responses = dict(await asyncio.gather(*[
            self._query_pair(model, messages, context)
            for model in models
        ]))

        result.stages.append({"name": "Round 1 - Initial Responses", "responses": responses})
        result.audit_trail.append({"stage": 1, "action": "initial_responses", "count": len(responses)})

        # Iterative convergence rounds
        for round_num in range(2, max_rounds + 1):
            combined = "\n\n".join(f"[{mid}]: {resp}" for mid, resp in responses.items())
            convergence_msg = [{"role": "user", "content": f"""The council is trying to reach consensus on: "{session.query}"

Here are the current positions:
{combined}

Review all positions. State:
1. Points of agreement across all responses
2. Your updated position (incorporating valid points from others)
3. Remaining disagreements (if any)
4. Your confidence that consensus has been reached (0.0-1.0)

If you believe consensus is reached, start your response with CONSENSUS: YES
Otherwise start with CONSENSUS: NO"""}]

            new_responses = {}
            new_responses = dict(await asyncio.gather(*[
                self._query_pair(model, convergence_msg, context)
                for model in models
            ]))
            consensus_count = sum(
                1
                for resp in new_responses.values()
                if resp.strip().upper().startswith("CONSENSUS: YES")
            )

            responses = new_responses
            agreement_ratio = consensus_count / len(models)
            result.stages.append({
                "name": f"Round {round_num} - Convergence",
                "responses": responses,
                "agreement_ratio": agreement_ratio,
            })
            result.audit_trail.append({
                "stage": round_num,
                "action": "convergence_round",
                "agreement_ratio": agreement_ratio,
            })

            if agreement_ratio >= threshold:
                break

        # Final synthesis from chairman
        chairman = next((m for m in models if m.id == self.config.chairman), models[0])
        synthesis_msg = [{"role": "user", "content": f"""Synthesize the final consensus answer for: "{session.query}"

Final positions:
{chr(10).join(f'[{mid}]: {resp}' for mid, resp in responses.items())}

Produce the consensus answer."""}]

        result.final_answer = await self.router.query(
            chairman,
            synthesis_msg,
            context=context,
        )
        result.confidence = agreement_ratio
        result.dissent = [resp for mid, resp in responses.items() if "CONSENSUS: NO" in resp.upper()]

        return result

    async def _query_pair(
        self,
        model,
        messages: list[dict],
        context: str = "",
    ) -> tuple[str, str]:
        return model.id, await self.router.query(model, messages, context=context)
