"""Regression tests for CLI output on legacy Windows console encodings."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import vc
from backend.memory import shared_memory
from backend.memory.shared_memory import SharedMemoryContext


ROOT = Path(__file__).resolve().parents[1]


class _StrictAsciiStream:
    encoding = "ascii"

    def __init__(self):
        self.value = ""

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        self.value += text
        return len(text)


def _run_with_gbk(*args: str) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env.update(
        {
            "AGENTMEMORY_URL": "",
            "PYTHONIOENCODING": "gbk",
            "PYTHONUTF8": "0",
        }
    )
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
        input=b"",
        timeout=30,
    )


def _decoded_output(result: subprocess.CompletedProcess[bytes]) -> tuple[str, str]:
    return result.stdout.decode("gbk"), result.stderr.decode("gbk")


def test_console_stream_fallback_escapes_unsupported_glyphs():
    target = _StrictAsciiStream()
    safe_stream = vc._safe_console_stream(target)

    safe_stream.write("result 🧪")

    assert target.value == r"result \U0001f9ea"


def test_untrusted_terminal_controls_are_removed_before_rendering():
    payload = (
        "before"
        "\x1b]52;c;Y2xpcGJvYXJkLXBheWxvYWQ=\x07"
        "\x1b[31mred\x1b[0m"
        "\rrewritten\x9b2J"
        "\u202ecod.exe"
        "\u061c\u200e\u200f"
        "after"
    )

    sanitized = vc._sanitize_terminal_text(payload)
    rendered = vc.c(payload, vc.BGREEN)
    spinner = vc.Spinner(payload)

    for value in (sanitized, spinner.msg):
        assert "\x1b" not in value
        assert all(control not in value for control in ("\u061c", "\u200e", "\u200f"))
        assert "\x07" not in value
        assert "\x9b" not in value
        assert "\r" not in value
        assert "\u202e" not in value
        assert "clipboard-payload" not in value
    assert "\x1b]52" not in rendered
    assert rendered.startswith(vc.BGREEN)
    assert rendered.endswith(vc.R)


def test_protocols_command_survives_gbk_subprocess():
    result = _run_with_gbk("-m", "vc", "protocols")
    stdout, stderr = _decoded_output(result)

    assert result.returncode == 0, stderr
    assert "Deliberation Protocols" in stdout
    for protocol in (
        "auto",
        "council",
        "debate",
        "redteam",
        "consensus",
        "specialist",
        "tournament",
    ):
        assert protocol in stdout
    assert "UnicodeEncodeError" not in stderr


def test_argument_error_survives_gbk_subprocess():
    result = _run_with_gbk("-m", "vc", "--not-a-real-option")
    _, stderr = _decoded_output(result)

    assert result.returncode == 2
    assert "unrecognized arguments" in stderr
    assert "UnicodeEncodeError" not in stderr


def test_interactive_header_survives_gbk_subprocess_eof():
    result = _run_with_gbk("-m", "vc")
    stdout, stderr = _decoded_output(result)

    assert result.returncode == 0, stderr
    assert "WEIPING_COUNCIL" in stdout
    assert "Type your question" in stdout
    assert "Goodbye" in stdout
    assert "UnicodeEncodeError" not in stderr


def test_headers_and_untrusted_text_survive_gbk_subprocess():
    script = "\n".join(
        [
            "import sys",
            "import time",
            "import vc",
            "vc._configure_console_output()",
            "payload = 'before' + chr(27) + ']52;c;Y2xpcGJvYXJk' + chr(7) + chr(27) + '[31mred' + chr(13) + 'after'",
            "vc.print_header()",
            "vc.print_query_echo('question 🧪' + payload, 'council')",
            "vc.print_confidence(0.5)",
            "vc.print_final_answer('answer 🧬' + payload)",
            "vc.print_dissent(['dissent 🔬' + payload])",
            "vc.print_stages([{'name': payload, 'responses': {'model': payload}}], True)",
            "vc.print_audit([{'note': payload}], True)",
            "print(vc.REPL_HELP)",
            "with vc.Spinner('work 🧪' + payload): time.sleep(0.12)",
            "print('stderr 🧪', file=sys.stderr)",
        ]
    )
    result = _run_with_gbk("-c", script)
    stdout, stderr = _decoded_output(result)

    assert result.returncode == 0, stderr
    assert "WEIPING_COUNCIL" in stdout
    assert "Final Answer" in stdout
    assert "answer" in stdout
    assert "stderr" in stderr
    assert "UnicodeEncodeError" not in stderr
    assert "\x1b]52" not in stdout
    assert "\x07" not in stdout


def test_result_renderer_defensively_handles_schema_invalid_values(capsys):
    cyclic = {}
    cyclic["self"] = cyclic
    malformed = {
        "confidence": float("inf"),
        "routing": [],
        "final_answer": {"unexpected": "object"},
        "dissent": {"unexpected": "object"},
        "stages": [
            "not-a-stage",
            {
                "name": "bad\x1b]52;c;payload\x07",
                "responses": [],
                "agreement_ratio": "not-a-number",
            },
        ],
        "audit_trail": [cyclic],
        "id": [],
    }

    vc.print_result(malformed, verbose=True)

    output = capsys.readouterr().out
    assert "Confidence" in output
    assert "Final Answer" in output
    assert "invalid audit entry" in output
    assert "\x1b]52" not in output
    assert "payload" not in output


def test_verbose_stage_renderer_exposes_all_protocol_specific_evidence(capsys):
    stages = [
        {"reviews": {"reviewer": {"review": "COUNCIL-REVIEW-MARKER"}}},
        {
            "proponent": {"argument": "PRO-ARG-MARKER", "rebuttal": "PRO-REB-MARKER"},
            "opponent": {"argument": "CON-ARG-MARKER", "rebuttal": "CON-REB-MARKER"},
            "verdict": "VERDICT-MARKER",
        },
        {"attacker": "ATTACKER-MARKER", "critique": "CRITIQUE-MARKER"},
        {
            "classification": "CLASSIFY-MARKER",
            "answer": "ANSWER-MARKER",
            "verifications": {"reviewer": "VERIFY-MARKER"},
        },
        {
            "matchups": [{"a": "a", "b": "b", "winner": "a", "verdict": "MATCH-MARKER"}],
            "winner": "WINNER-MARKER",
        },
        {
            "subtasks": [
                {
                    "desc": "SUBTASK-MARKER",
                    "model": "worker",
                    "status": "done",
                    "result": "RESULT-MARKER",
                }
            ]
        },
    ]

    vc.print_stages(stages, verbose=True)
    output = capsys.readouterr().out

    for marker in (
        "COUNCIL-REVIEW-MARKER",
        "PRO-ARG-MARKER",
        "PRO-REB-MARKER",
        "CON-ARG-MARKER",
        "CON-REB-MARKER",
        "VERDICT-MARKER",
        "ATTACKER-MARKER",
        "CRITIQUE-MARKER",
        "CLASSIFY-MARKER",
        "ANSWER-MARKER",
        "VERIFY-MARKER",
        "MATCH-MARKER",
        "WINNER-MARKER",
        "SUBTASK-MARKER",
        "RESULT-MARKER",
    ):
        assert marker in output


def test_projects_and_context_commands_never_echo_exception_messages(monkeypatch, capsys):
    sensitive_message = "sensitive-exception-value"

    def fail_closed():
        raise RuntimeError(sensitive_message)

    monkeypatch.setattr(shared_memory, "load_shared_memory", fail_closed)

    vc.cmd_projects()
    vc.cmd_context()
    output = capsys.readouterr().out

    assert sensitive_message not in output
    assert "Could not load projects from agentmemory" in output
    assert "Could not load context from agentmemory" in output


def test_projects_command_distinguishes_unavailable_metadata_from_empty_projects(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        shared_memory,
        "load_shared_memory",
        lambda: SharedMemoryContext(projects_available=False),
    )

    vc.cmd_projects()

    assert "Structured project metadata is unavailable" in capsys.readouterr().out
