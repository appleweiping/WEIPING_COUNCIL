"""Canned replies for demo mode (VC_DEMO=1 or `vc serve --demo`).

Demo mode exists so the UI and CLI can be tried and screenshotted without an API
key. The protocol code runs for real (stages, peer review prompts, traces,
timings, session files); only the model replies come from this file. I wrote the
replies by hand for one sample question. They are not model output.
"""

from __future__ import annotations

import asyncio
import random

DEMO_QUESTION = (
    "Three of us are building a course-project web app over ten weeks. "
    "Should we split the backend into microservices or keep one service?"
)

_OPINIONS = {
    "architect": (
        "Keep one service. Microservices buy independent deployment and scaling for "
        "separate teams; you are one team of three with one deadline. The costs are "
        "real on day one: network calls instead of function calls, distributed "
        "failures, several CI pipelines, and data that has to be kept consistent "
        "across databases. Draw module boundaries inside the monolith (auth, "
        "courses, grading) so a later split is possible if it is ever needed."
    ),
    "coordinator": (
        "One service, one repo, one database. Week 1: skeleton, CI and deploy to a "
        "free host. Weeks 2-8: features behind clear modules. Weeks 9-10: polish "
        "and demo. Microservices would eat the first three weeks in Docker Compose "
        "and service discovery before any user-visible feature exists."
    ),
    "implementer": (
        "Monolith. Concretely: one FastAPI or Express app, Postgres, migrations from "
        "the start, and an integration test per endpoint. If one part really needs "
        "isolation (say, a slow PDF export), run it as a background worker in the "
        "same repo instead of a separate service."
    ),
    "reviewer": (
        "Agree on a single service, with one caveat: \"modular monolith\" only "
        "helps if the boundaries are enforced. Agree on which module owns which "
        "tables and do not reach into another module's tables directly; otherwise "
        "the code turns into one tangled package by week six."
    ),
    "speedster": "One service. Three people and ten weeks do not need microservices.",
    "bulk-worker": (
        "Single service. For a graded project, a working demo and a readable "
        "codebase matter more than architecture diagrams. If the course explicitly "
        "grades distributed-systems skills, split off one small service (for "
        "example notifications) to show the pattern, and keep everything else "
        "together."
    ),
}

_REVIEWS = {
    "architect": (
        "Ranking: B (8/10), C (8/10), D (7/10), F (6/10), E (5/10). B and C turn "
        "the advice into a plan. D's point about table ownership is the most useful "
        "warning. F's exception for a course that grades distributed systems is "
        "fair. E is correct but gives no reasons. All agree with the conclusion."
    ),
    "coordinator": (
        "Ranking: A (9/10), D (8/10), C (7/10), F (6/10), E (4/10). A explains why "
        "the trade-off fails for a team of three. D adds the enforcement detail. "
        "Everyone agrees on one service."
    ),
    "implementer": (
        "Ranking: A (9/10), D (8/10), B (7/10), F (7/10), E (4/10). F raises the "
        "only real disagreement: if the rubric rewards a split, a token service "
        "may be worth it. I agree with the main conclusion."
    ),
    "reviewer": (
        "Ranking: A (9/10), C (8/10), B (7/10), F (6/10), E (4/10). C is the only "
        "answer that names a concrete alternative (a background worker) for the "
        "part that might need isolation. Agree."
    ),
    "speedster": "A best, then C, D, B, F. All agree.",
    "bulk-worker": (
        "Ranking: A (9/10), D (8/10), C (7/10), B (7/10), E (5/10). Agree with the "
        "shared conclusion; A and D together cover both the why and the how."
    ),
}

_SYNTHESIS = (
    "ANSWER: Keep one backend service (a modular monolith). Microservices pay off "
    "when separate teams need to deploy and scale parts independently; a team of "
    "three with a ten-week deadline gets only the costs: network calls, partial "
    "failures, more pipelines and cross-database consistency.\n\n"
    "What to do instead:\n"
    "1. One repo, one service, one Postgres database, CI and a deploy in week 1.\n"
    "2. Split the code into modules (for example auth, courses, grading) and agree "
    "which module owns which tables; no module reads another's tables directly.\n"
    "3. If one task is slow or heavy, run it as a background worker in the same "
    "repo rather than as a separate service.\n"
    "4. Only if the course rubric explicitly rewards distributed design, split off "
    "one small, low-risk service such as notifications.\n"
    "CONFIDENCE: 0.86\n"
    "DISSENT: One member suggested splitting off a single small service if the "
    "course grades distributed-systems skills."
)

_OTHER_PROTOCOL = (
    "Demo mode only has canned replies for the council protocol and its sample "
    "question. Set a provider key in .env to run this protocol against real models."
)

_DIFFERENT_QUESTION_NOTE = (
    "(Demo mode: this is the canned answer to the sample question. Your question "
    "was not sent to any model.)\n\n"
)


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


# Openings of the prompts the protocols and engines build themselves. Anything
# else is the user's own question, i.e. a first-round call.
_INTERNAL_PROMPTS = (
    "You are reviewing responses", "You are the Chairman", "The council is trying",
    "Synthesize the final consensus", "Argue IN FAVOR", "Argue AGAINST",
    "Your opponent argued", "You are the judge", "You are a red team",
    "The red team found", "Classify this query", "You are the designated specialist",
    "Verify this specialist", "You are judging a tournament", "Rate the difficulty",
    "Break this complex query", "Answer this specific sub-question",
    "You decomposed this query", "You are a rigorous critic", "You previously answered",
    "Think step by step", "Rate this answer", "Here is a partial answer",
)


def canned_reply(role: str, messages: list[dict]) -> str:
    """Return the scripted reply for this role and council stage."""
    prompt = _last_user_text(messages)
    if prompt.startswith("You are reviewing responses"):
        return _REVIEWS.get(role, _REVIEWS["speedster"])
    if prompt.startswith("You are the Chairman"):
        if DEMO_QUESTION not in prompt:
            return "ANSWER: " + _DIFFERENT_QUESTION_NOTE + _SYNTHESIS.removeprefix("ANSWER: ")
        return _SYNTHESIS
    if not prompt.startswith(_INTERNAL_PROMPTS):
        return _OPINIONS.get(role, _OPINIONS["speedster"])
    return _OTHER_PROTOCOL


async def demo_reply(role: str, messages: list[dict]) -> str:
    # A short pause so the UI shows a running state and traces have latencies.
    await asyncio.sleep(random.uniform(0.15, 0.6))
    return canned_reply(role, messages)
