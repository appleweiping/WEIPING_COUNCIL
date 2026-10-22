import importlib.util
import json
import sys
from pathlib import Path

import pytest

from backend import demo

_SPEC = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parent.parent / "eval" / "run_eval.py"
)
run_eval = importlib.util.module_from_spec(_SPEC)
sys.modules["run_eval"] = run_eval  # dataclasses look the module up by name
_SPEC.loader.exec_module(run_eval)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("so she has 18 left.\nANSWER: 18", 18.0),
        ("ANSWER: $1,234.50", 1234.5),
        ("first 3, then 7, finally ANSWER: 10 apples", 10.0),
        ("The total is 42.", 42.0),
        ("no digits here", None),
    ],
)
def test_extract_number(text, expected):
    assert run_eval.extract_number(text) == expected


def test_demo_run_writes_summary_without_network(tmp_path, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(demo.asyncio, "sleep", no_sleep)
    data = tmp_path / "questions.jsonl"
    data.write_text(
        "\n".join(
            json.dumps(item)
            for item in [
                {"question": "Tom has 3 apples and buys 4 more. How many?", "answer": 7},
                {"question": "A box holds 6 eggs. How many eggs in 5 boxes?", "answer": 30},
            ]
        ),
        encoding="utf-8",
    )
    summary = run_eval.main(
        ["--demo", "--data", str(data), "--protocols", "council", "--out", str(tmp_path / "out")]
    )

    by_arm = {line["arm"]: line for line in summary}
    assert set(by_arm) == {"single:architect", "council"}
    assert by_arm["single:architect"]["calls_per_question"] == 1
    assert by_arm["council"]["calls_per_question"] == 13
    assert all(line["n"] == 2 and line["failed_calls"] == 0 for line in summary)
    written = list((tmp_path / "out").glob("*-demo.json"))
    assert len(written) == 1
    assert len(json.loads(written[0].read_text(encoding="utf-8"))["rows"]) == 4
