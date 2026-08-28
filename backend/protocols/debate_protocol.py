"""Debate Protocol: Two sides argue, judge decides."""
import asyncio

from .base import BaseProtocol
from ..council.session import Session, SessionResult


class DebateProtocol(BaseProtocol):
    async def execute(self, session: Session) -> SessionResult:
        result = SessionResult(
            id=session.id, query=session.query,
            protocol="debate", created_at=session.created_at,
        )

        models = self.config.models
        if len(models) < 3:
            result.final_answer = "Need at least 3 models for debate protocol."
            return result

        proponent = models[0]
        opponent = models[1]
        judge = models[2]
        context = session.context or ""

        # Round 1: Opening statements
        pro_msg = [{"role": "user", "content": f"Argue IN FAVOR of this position: {session.query}\nBe thorough and persuasive."}]
        con_msg = [{"role": "user", "content": f"Argue AGAINST this position: {session.query}\nBe thorough and persuasive."}]

        pro_response, con_response = await asyncio.gather(
            self.router.query(proponent, pro_msg, context=context),
            self.router.query(opponent, con_msg, context=context),
        )

        result.stages.append({"name": "Opening Statements", "proponent": {"model": proponent.name, "argument": pro_response}, "opponent": {"model": opponent.name, "argument": con_response}})

        # Round 2: Rebuttals
        pro_rebuttal_msg = [{"role": "user", "content": f"Your opponent argued: {con_response}\n\nProvide your rebuttal, defending your original position on: {session.query}"}]
        con_rebuttal_msg = [{"role": "user", "content": f"Your opponent argued: {pro_response}\n\nProvide your rebuttal, defending your original position against: {session.query}"}]

        pro_rebuttal, con_rebuttal = await asyncio.gather(
            self.router.query(proponent, pro_rebuttal_msg, context=context),
            self.router.query(opponent, con_rebuttal_msg, context=context),
        )

        result.stages.append({"name": "Rebuttals", "proponent": {"model": proponent.name, "rebuttal": pro_rebuttal}, "opponent": {"model": opponent.name, "rebuttal": con_rebuttal}})

        # Round 3: Judge verdict
        judge_msg = [{"role": "user", "content": f"""You are the judge in a debate on: "{session.query}"

PROPONENT ({proponent.name}):
Opening: {pro_response}
Rebuttal: {pro_rebuttal}

OPPONENT ({opponent.name}):
Opening: {con_response}
Rebuttal: {con_rebuttal}

Deliver your verdict:
1. Who made the stronger argument and why?
2. What is the most balanced conclusion?
3. Confidence (0.0-1.0) in your verdict.

Format: VERDICT: <your analysis>\nWINNER: <proponent/opponent/draw>\nCONFIDENCE: <0.0-1.0>"""}]

        verdict = await self.router.query(judge, judge_msg, context=context)
        result.stages.append({"name": "Verdict", "judge": judge.name, "verdict": verdict})
        result.final_answer = verdict
        result.confidence = 0.7
        result.audit_trail = [
            {"stage": 1, "action": "opening_statements"},
            {"stage": 2, "action": "rebuttals"},
            {"stage": 3, "action": "judge_verdict"},
        ]

        return result
