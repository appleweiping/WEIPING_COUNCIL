"""Does a council answer better than one model? A small GSM8K check.

Runs grade-school math word problems from GSM8K (test split, fetched from the
Hugging Face datasets server) through one council member on its own and through
one or more protocols, then compares exact-number accuracy, model calls and
wall time per question.

    python eval/run_eval.py --n 20                         # single vs council
    python eval/run_eval.py --n 20 --protocols council,debate
    python eval/run_eval.py --demo --data my_questions.jsonl   # offline plumbing check

Cost: the single arm makes 1 call per question; council makes 13 (6 opinions,
6 peer reviews, 1 chairman) plus up to 6 more when self-refine runs. 20
questions through council is roughly 260-380 calls on your provider account.

--data takes a JSONL file with {"question": ..., "answer": <number>} per line.
In --demo mode every reply is canned (backend/demo.py), so accuracy is
meaningless; it only checks that the harness runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import CouncilConfig  # noqa: E402
from backend.council.orchestrator import Orchestrator  # noqa: E402
from backend.council.session import Session  # noqa: E402
from backend.providers.router import ModelRouter  # noqa: E402
from backend.runtime import RuntimeSettings  # noqa: E402

ROWS_URL = "https://datasets-server.huggingface.co/rows"
PROMPT = (
    "{question}\n\nSolve it step by step, then finish with a final line of the form "
    "'ANSWER: <number>'."
)
_NUMBER = r"-?\$?\d[\d,]*(?:\.\d+)?"


@dataclass
class Row:
    arm: str
    index: int
    gold: float
    predicted: float | None
    correct: bool
    model_calls: int
    failed_calls: int
    seconds: float


def load_gsm8k(n: int, offset: int = 0) -> list[dict]:
    """Fetch n GSM8K test problems; the gold answer follows '####'."""
    items: list[dict] = []
    while len(items) < n:
        length = min(100, n - len(items))
        response = httpx.get(
            ROWS_URL,
            params={
                "dataset": "openai/gsm8k",
                "config": "main",
                "split": "test",
                "offset": offset + len(items),
                "length": length,
            },
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json()["rows"]
        if not rows:
            break
        for row in rows:
            solution = row["row"]["answer"]
            gold = solution.split("####")[-1].strip().replace(",", "")
            items.append({"question": row["row"]["question"], "answer": float(gold)})
    return items[:n]


def load_jsonl(path: Path) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            items.append({"question": record["question"], "answer": float(record["answer"])})
    return items


def extract_number(text: str) -> float | None:
    """Prefer the last 'ANSWER: <n>' line, else the last number in the text."""
    tagged = re.findall(rf"ANSWER:\s*({_NUMBER})", text or "", flags=re.IGNORECASE)
    candidates = tagged or re.findall(_NUMBER, text or "")
    if not candidates:
        return None
    try:
        return float(candidates[-1].replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _score(arm, index, gold, answer, traces, seconds) -> Row:
    predicted = extract_number(answer)
    failed = sum(1 for trace in traces if trace.get("error_kind"))
    return Row(
        arm=arm,
        index=index,
        gold=gold,
        predicted=predicted,
        correct=predicted is not None and abs(predicted - gold) < 1e-6,
        model_calls=len(traces),
        failed_calls=failed,
        seconds=round(seconds, 2),
    )


async def run_single(router: ModelRouter, role: str, index: int, item: dict) -> Row:
    model = next(m for m in router.config.models if m.role == role)
    started = time.perf_counter()
    token = router.start_trace_scope()
    try:
        answer = await router.query(
            model, [{"role": "user", "content": PROMPT.format(question=item["question"])}]
        )
    finally:
        traces = [trace.to_dict() for trace in router.finish_trace_scope(token)]
    return _score(f"single:{role}", index, item["answer"], answer, traces, time.perf_counter() - started)


async def run_protocol(orchestrator: Orchestrator, protocol: str, index: int, item: dict) -> Row:
    session = Session(
        id=str(uuid.uuid4()),
        query=PROMPT.format(question=item["question"]),
        protocol=protocol,
        created_at=datetime.now(UTC).isoformat(),
    )
    started = time.perf_counter()
    result = await orchestrator.run(session)
    return _score(
        protocol,
        index,
        item["answer"],
        result.final_answer,
        result.model_call_traces,
        time.perf_counter() - started,
    )


def summarize(rows: list[Row]) -> list[dict]:
    summary = []
    for arm in dict.fromkeys(row.arm for row in rows):
        group = [row for row in rows if row.arm == arm]
        summary.append(
            {
                "arm": arm,
                "n": len(group),
                "accuracy": round(sum(row.correct for row in group) / len(group), 3),
                "calls_per_question": round(sum(row.model_calls for row in group) / len(group), 1),
                "failed_calls": sum(row.failed_calls for row in group),
                "seconds_per_question": round(sum(row.seconds for row in group) / len(group), 1),
            }
        )
    return summary


async def evaluate(args) -> tuple[list[Row], list[dict]]:
    items = load_jsonl(Path(args.data)) if args.data else load_gsm8k(args.n, args.offset)
    items = items[: args.n]
    config = CouncilConfig()
    env = {**os.environ, "VC_DEMO": "1"} if args.demo else None
    settings = RuntimeSettings.from_env(config, env=env)
    router = ModelRouter(config, settings=settings)
    orchestrator = Orchestrator(config, router=router)
    protocols = [p.strip() for p in args.protocols.split(",") if p.strip()]

    rows: list[Row] = []
    for index, item in enumerate(items):
        rows.append(await run_single(router, args.single_role, index, item))
        for protocol in protocols:
            rows.append(await run_protocol(orchestrator, protocol, index, item))
        done = ", ".join(f"{row.arm}={'ok' if row.correct else 'x'}" for row in rows if row.index == index)
        print(f"[{index + 1}/{len(items)}] {done}", flush=True)
    return rows, summarize(rows)


def main(argv: list[str] | None = None) -> list[dict]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=20, help="number of questions")
    parser.add_argument("--offset", type=int, default=0, help="first GSM8K test index")
    parser.add_argument("--data", help="local JSONL instead of GSM8K")
    parser.add_argument("--protocols", default="council", help="comma-separated protocols")
    parser.add_argument("--single-role", default="architect", help="member for the single arm")
    parser.add_argument("--demo", action="store_true", help="canned replies, no API calls")
    parser.add_argument("--out", default=str(ROOT / "eval" / "results"), help="results directory")
    args = parser.parse_args(argv)

    rows, summary = asyncio.run(evaluate(args))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{stamp}{'-demo' if args.demo else ''}.json"
    out_path.write_text(
        json.dumps({"args": vars(args), "summary": summary, "rows": [asdict(r) for r in rows]}, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"{'arm':<20}{'n':>4}{'accuracy':>10}{'calls/q':>9}{'failed':>8}{'s/q':>7}")
    for line in summary:
        print(
            f"{line['arm']:<20}{line['n']:>4}{line['accuracy']:>10.3f}"
            f"{line['calls_per_question']:>9}{line['failed_calls']:>8}{line['seconds_per_question']:>7}"
        )
    print(f"\nwrote {out_path}")
    return summary


if __name__ == "__main__":
    main()
