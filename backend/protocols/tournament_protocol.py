"""Tournament Protocol: Bracket elimination, best answer wins."""

import asyncio
import re

from .base import BaseProtocol
from ..council.session import Session, SessionResult
from ..providers.router import is_provider_error_result


def _explicit_winner_side(verdict: object) -> str | None:
    """Return A/B only for one unambiguous, line-anchored winner declaration."""
    if is_provider_error_result(verdict) or not isinstance(verdict, str):
        return None
    explicit_markers = re.findall(r"(?im)^\s*WINNER\s*:\s*([AB])\b", verdict)
    all_markers = re.findall(r"(?i)\bWINNER\s*:\s*([AB])\b", verdict)
    return explicit_markers[0].upper() if len(explicit_markers) == len(all_markers) == 1 else None


class TournamentProtocol(BaseProtocol):
    async def execute(self, session: Session) -> SessionResult:
        result = SessionResult(
            id=session.id,
            query=session.query,
            protocol="tournament",
            created_at=session.created_at,
        )

        models = self.config.models
        context = session.context or ""
        if len(models) < 2:
            result.final_answer = "Need at least 2 models for tournament protocol."
            return result

        # Stage 1: All models answer
        messages = [{"role": "user", "content": session.query}]
        answers = dict(
            await asyncio.gather(*[self._query_pair(model, messages, context) for model in models])
        )

        result.stages.append({"name": "Initial Answers", "responses": answers})
        result.audit_trail.append({"stage": 1, "action": "initial_answers", "count": len(answers)})

        # Stage 2: Bracket elimination
        judge = next((m for m in models if m.id == self.config.chairman), models[0])
        remaining = list(answers.items())
        round_num = 2

        while len(remaining) > 1:
            next_round = []
            matchups = []

            for i in range(0, len(remaining) - 1, 2):
                a_id, a_answer = remaining[i]
                b_id, b_answer = remaining[i + 1]

                a_failed = is_provider_error_result(a_answer)
                b_failed = is_provider_error_result(b_answer)
                if a_failed or b_failed:
                    result.degraded = True
                    if a_failed and b_failed:
                        matchups.append(
                            {
                                "a": a_id,
                                "b": b_id,
                                "winner": "",
                                "verdict": "Both contestant responses were unavailable.",
                            }
                        )
                        result.warnings.append(
                            "A tournament matchup had no usable contestant response."
                        )
                        continue
                    winner = remaining[i + 1] if a_failed else remaining[i]
                    next_round.append(winner)
                    matchups.append(
                        {
                            "a": a_id,
                            "b": b_id,
                            "winner": winner[0],
                            "verdict": (
                                "The usable response advanced because its opponent was unavailable."
                            ),
                        }
                    )
                    result.warnings.append(
                        "A tournament contestant was unavailable; the usable response advanced."
                    )
                    continue

                judge_msg = [
                    {
                        "role": "user",
                        "content": f"""You are judging a tournament match for the query: "{session.query}"

CONTESTANT A ({a_id}):
{a_answer}

CONTESTANT B ({b_id}):
{b_answer}

Which response is better? Consider accuracy, completeness, clarity, and usefulness.
Reply with WINNER: A or WINNER: B, followed by a brief justification.""",
                    }
                ]

                verdict = await self.router.query(judge, judge_msg, context=context)
                winner_side = _explicit_winner_side(verdict)
                if winner_side is None:
                    matchups.append({"a": a_id, "b": b_id, "winner": "", "verdict": verdict})
                    result.stages.append(
                        {"name": f"Round {round_num} - Elimination", "matchups": matchups}
                    )
                    result.audit_trail.append(
                        {
                            "stage": round_num,
                            "action": "tournament_inconclusive",
                            "remaining": len(remaining),
                        }
                    )
                    result.final_answer = (
                        "Tournament could not determine a winner because the judge response "
                        "was unavailable or invalid."
                    )
                    result.confidence = 0.0
                    result.degraded = True
                    result.warnings.append(
                        "Tournament judge did not return one explicit WINNER: A or WINNER: B marker."
                    )
                    return result
                winner = remaining[i] if winner_side == "A" else remaining[i + 1]
                next_round.append(winner)
                matchups.append({"a": a_id, "b": b_id, "winner": winner[0], "verdict": verdict})

            # If odd number, last one gets a bye
            if len(remaining) % 2 == 1:
                bye = remaining[-1]
                if is_provider_error_result(bye[1]):
                    result.degraded = True
                    result.warnings.append(
                        "A tournament contestant with a bye was unavailable and could not advance."
                    )
                else:
                    next_round.append(bye)

            result.stages.append({"name": f"Round {round_num} - Elimination", "matchups": matchups})
            if not next_round:
                result.audit_trail.append(
                    {
                        "stage": round_num,
                        "action": "tournament_inconclusive",
                        "remaining": 0,
                    }
                )
                result.final_answer = (
                    "Tournament could not determine a winner because no usable contestant "
                    "response remained."
                )
                result.confidence = 0.0
                return result
            result.audit_trail.append(
                {"stage": round_num, "action": "elimination_round", "remaining": len(next_round)}
            )
            remaining = next_round
            round_num += 1

        # Winner
        winner_id, winner_answer = remaining[0]
        if is_provider_error_result(winner_answer):
            result.final_answer = (
                "Tournament could not determine a winner because no usable contestant "
                "response remained."
            )
            result.confidence = 0.0
            result.degraded = True
            result.warnings.append("The remaining tournament response was unavailable.")
            return result
        result.final_answer = winner_answer
        result.confidence = 0.5 if result.degraded else 0.75
        result.stages.append({"name": "Tournament Winner", "winner": winner_id})
        result.audit_trail.append(
            {"stage": round_num, "action": "tournament_winner", "winner": winner_id}
        )

        return result

    async def _query_pair(
        self,
        model,
        messages: list[dict],
        context: str = "",
    ) -> tuple[str, str]:
        return model.id, await self.router.query(model, messages, context=context)
