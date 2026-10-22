#!/usr/bin/env python3
"""
vc — Weiping Council CLI
Multi-LLM deliberation from your terminal.

Usage:
  vc serve [--demo]               # API + web UI on http://127.0.0.1:8000
  vc                              # interactive REPL
  vc "your question"              # one-shot query (council protocol)
  vc "your question" -p debate    # specify protocol
  vc sessions                     # list recent sessions
  vc show <id>                    # replay a session
  vc models                       # list configured models
  vc protocols                    # list protocols
  vc status                       # check backend health

Add --demo to any command to use canned replies instead of real models.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import textwrap
import uuid
import time
import threading
import itertools
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

from backend.config import APP_VERSION
from backend.session_store import SessionStore

# Ensure project root is on sys.path so `from backend.*` works whether
# invoked as `python vc.py`, `python -m vc`, or via the `vc` entry-point.
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)


class _EncodingSafeStream:
    """Proxy a text stream and escape characters its encoding cannot represent."""

    def __init__(self, stream, encoding: str):
        self._stream = stream
        self._encoding = encoding

    def write(self, text: str):
        safe_text = text.encode(self._encoding, errors="backslashreplace").decode(self._encoding)
        return self._stream.write(safe_text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _safe_console_stream(stream):
    """Return a stream that cannot fail on unsupported terminal glyphs."""
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(errors="backslashreplace")
            return stream
        except (AttributeError, OSError, TypeError, ValueError):
            pass

    encoding = getattr(stream, "encoding", None)
    if encoding:
        return _EncodingSafeStream(stream, encoding)
    return stream


def _configure_console_output() -> None:
    """Keep CLI output usable on legacy Windows code pages such as GBK."""
    sys.stdout = _safe_console_stream(sys.stdout)
    sys.stderr = _safe_console_stream(sys.stderr)


# ── ANSI colour palette ───────────────────────────────────────────────────────
R = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BBLACK = "\033[90m"
BRED = "\033[91m"
BGREEN = "\033[92m"
BYELLOW = "\033[93m"
BBLUE = "\033[94m"
BMAGENTA = "\033[95m"
BCYAN = "\033[96m"
BWHITE = "\033[97m"

ANSI_CODES = frozenset(
    {
        R,
        BOLD,
        DIM,
        ITALIC,
        BLACK,
        RED,
        GREEN,
        YELLOW,
        BLUE,
        MAGENTA,
        CYAN,
        WHITE,
        BBLACK,
        BRED,
        BGREEN,
        BYELLOW,
        BBLUE,
        BMAGENTA,
        BCYAN,
        BWHITE,
    }
)
_TERMINAL_SEQUENCE = re.compile(
    r"(?:"
    r"\x1b\][^\x07]*(?:\x07|\x1b\\|$)"  # OSC, including clipboard/title controls
    r"|\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b[PX^_].*?(?:\x1b\\|$)"  # DCS/SOS/PM/APC
    r"|\x1b[ -/]*[@-~]"  # other ESC sequences
    r"|\x9b[0-?]*[ -/]*[@-~]"  # 8-bit CSI
    r"|\x9d.*?(?:\x9c|$)"  # 8-bit OSC
    r")",
    flags=re.DOTALL,
)
_BIDI_CONTROLS = (
    frozenset({0x061C, 0x200E, 0x200F})
    | frozenset(range(0x202A, 0x202F))
    | frozenset(range(0x2066, 0x206A))
)


def _sanitize_terminal_text(value: object) -> str:
    """Remove terminal-control and bidi-spoofing characters from untrusted text."""
    text = _TERMINAL_SEQUENCE.sub("", str(value))
    return "".join(
        char
        for char in text
        if char in {"\n", "\t"}
        or (ord(char) >= 0x20 and not 0x7F <= ord(char) <= 0x9F and ord(char) not in _BIDI_CONTROLS)
    )


def c(*args):
    """c(text, *codes) or c(*codes, text) — wrap text in ANSI codes."""
    codes = [a for a in args if isinstance(a, str) and a in ANSI_CODES]
    texts = [a for a in args if not (isinstance(a, str) and a in ANSI_CODES)]
    return "".join(codes) + _sanitize_terminal_text(texts[0] if texts else "") + R


def hr(char="─", width=None):
    w = width or min(shutil.get_terminal_size().columns, 88)
    return c(char * w, DIM)


def wrap(text: str, width: int = None, indent: str = "  ") -> str:
    w = width or min(shutil.get_terminal_size().columns - 4, 84)
    lines = []
    for para in _sanitize_terminal_text(text).split("\n"):
        if para.strip() == "":
            lines.append("")
        else:
            lines.extend(textwrap.wrap(para, w, initial_indent=indent, subsequent_indent=indent))
    return "\n".join(lines)


# ── Protocol metadata ─────────────────────────────────────────────────────────
PROTOCOLS = {
    "auto": ("◇", BCYAN, "Route by complexity with inspectable evidence"),
    "council": ("⚖", BBLUE, "All models → peer review → chairman synthesis"),
    "debate": ("⚔", BRED, "Pro vs con → rebuttals → judge verdict"),
    "redteam": ("🔴", BYELLOW, "Defend → attack → improve iteratively"),
    "consensus": ("🤝", BGREEN, "Iterative rounds until agreement threshold met"),
    "specialist": ("🎯", BMAGENTA, "Classify domain → route to expert → verify"),
    "tournament": ("🏆", BYELLOW, "Bracket elimination, best answer wins"),
}


# ── Spinner ───────────────────────────────────────────────────────────────────
class Spinner:
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, msg: str = "Thinking", color: str = CYAN):
        self.msg = _sanitize_terminal_text(msg)
        self.color = color
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._start_time = 0.0

    def _run(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            elapsed = time.time() - self._start_time
            line = f"\r  {c(frame, self.color)} {self.msg}  {c(f'{elapsed:.1f}s', DIM)}  "
            sys.stdout.write(line)
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._start_time = time.time()
        self._t.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._t.join()


# ── Formatting helpers ────────────────────────────────────────────────────────
def print_header():
    print()
    print(c("  ⚡ WEIPING_COUNCIL", BOLD, BMAGENTA) + "  " + c(f"v{APP_VERSION}", DIM))
    print(c("  Multi-LLM Deliberation System", DIM))
    print(hr())
    _show_startup_context()


def _show_startup_context():
    """Show recalled agentmemory context on startup."""
    try:
        from backend.memory.shared_memory import load_shared_memory

        ctx = load_shared_memory()
        if ctx.raw_summary:
            print(f"  {c('agentmemory', BOLD, BCYAN)}  {c('context recalled', DIM)}")
            first_line = _sanitize_terminal_text(ctx.raw_summary.splitlines()[0])[:80]
            print(f"  {c('·', DIM)} {first_line}")
            print()
        if ctx.projects:
            print(f"  {c('Active Projects', BOLD, BCYAN)}")
            for p in ctx.projects[:4]:
                prio = p["priority"]
                name = p["name"]
                status = p["status"][:50]
                print(f"  {c(f'P{prio}', DIM)} {c(name, BOLD)}  {c(status, DIM)}")
            print()
    except Exception:
        pass


def print_query_echo(query: str, protocol: str):
    query = _sanitize_terminal_text(query)
    protocol = protocol if isinstance(protocol, str) and protocol in PROTOCOLS else "council"
    icon, color, _ = PROTOCOLS.get(protocol, ("?", WHITE, ""))
    print()
    print(f"  {c('Query', BOLD, DIM)}  {c(query, ITALIC, WHITE)}")
    print(f"  {c('Protocol', BOLD, DIM)}  {c(icon + ' ' + protocol.capitalize(), color, BOLD)}")
    print(hr())


def print_confidence(value: float):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    pct = int(max(0.0, min(1.0, confidence)) * 100)
    if pct >= 70:
        color, label = BGREEN, "high"
    elif pct >= 40:
        color, label = BYELLOW, "moderate"
    else:
        color, label = BRED, "low"
    bar_len = 24
    filled = int(bar_len * pct / 100)
    bar = c("█" * filled, color) + c("░" * (bar_len - filled), BBLACK)
    print(f"  {c('Confidence', BOLD, DIM)}  {bar}  {c(f'{pct}%', color, BOLD)}  {c(label, DIM)}")


def print_final_answer(text: str):
    print()
    print(f"  {c('✦ Final Answer', BOLD, BGREEN)}")
    print(hr("─"))
    print(wrap(text))
    print(hr("─"))


def print_dissent(dissent: list):
    if not isinstance(dissent, list) or not dissent:
        return
    print()
    print(f"  {c('⚠ Dissenting Views', BOLD, BYELLOW)}  {c(f'({len(dissent)})', DIM)}")
    for d in dissent:
        d = _sanitize_terminal_text(d)
        snippet = d[:300] + ("…" if len(d) > 300 else "")
        print(wrap(snippet, indent="    "))


def print_audit(trail: list, verbose: bool):
    if not isinstance(trail, list) or not trail or not verbose:
        return
    print()
    print(f"  {c('Audit Trail', BOLD, DIM)}")
    for step in trail:
        try:
            rendered = json.dumps(step, ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            rendered = "[invalid audit entry]"
        print(f"    {c('·', DIM)} {c(rendered, BBLACK)}")


def print_routing(routing: dict):
    if not isinstance(routing, dict) or not routing:
        return
    selected = routing.get("selected_protocol", routing.get("tier", "unknown"))
    mode = routing.get("mode", "unknown")
    tier = routing.get("tier")
    detail = f"{mode} → {selected}"
    if tier and tier not in {"protocol", selected}:
        detail += f" ({tier})"
    print(f"  {c('Route', BOLD, DIM)}  {c(detail, BCYAN)}")


def _print_stage_evidence(label: object, value: object, depth: int = 0) -> None:
    """Render bounded protocol-specific evidence without hiding schema variants."""
    if depth > 4:
        print(f"    {c(str(label), DIM)}  {c('[nested evidence omitted]', BBLACK)}")
        return
    safe_label = _sanitize_terminal_text(label)
    indent = "    " + "  " * depth
    if isinstance(value, str):
        snippet = _sanitize_terminal_text(value)
        if len(snippet) > 1_200:
            snippet = snippet[:1_200] + "…"
        print(f"\n{indent}{c(safe_label, BOLD, CYAN)}")
        print(wrap(snippet, indent=indent + "  "))
        return
    if isinstance(value, dict):
        print(f"\n{indent}{c(safe_label, BOLD, CYAN)}")
        for key, child in list(value.items())[:100]:
            _print_stage_evidence(key, child, depth + 1)
        return
    if isinstance(value, list):
        print(f"\n{indent}{c(safe_label, BOLD, CYAN)}")
        for index, child in enumerate(value[:100], start=1):
            _print_stage_evidence(f"item {index}", child, depth + 1)
        return
    if isinstance(value, (bool, int, float)) or value is None:
        print(f"\n{indent}{c(safe_label + ':', DIM)} {c(str(value), BBLACK)}")


def print_stages(stages: list, verbose: bool):
    if not isinstance(stages, list) or not stages or not verbose:
        return
    print()
    print(f"  {c('Deliberation Stages', BOLD, DIM)}")
    for i, stage in enumerate(item for item in stages if isinstance(item, dict)):
        name = stage.get("name", f"Stage {i + 1}")
        print(f"\n  {c(f'  {i + 1}. {name}', BOLD, BBLUE)}")
        print(hr("·"))
        responses = stage.get("responses", {})
        if not isinstance(responses, dict):
            responses = {}
        for model_id, resp in responses.items():
            model_id = _sanitize_terminal_text(model_id)
            resp = _sanitize_terminal_text(resp)
            short = model_id.split("/")[-1]
            print(f"\n    {c(short, BOLD, CYAN)}")
            print(wrap(resp[:600] + ("…" if len(resp) > 600 else ""), indent="      "))
        if "agreement_ratio" in stage:
            try:
                ratio = float(stage["agreement_ratio"])
            except (TypeError, ValueError):
                ratio = math.nan
            if math.isfinite(ratio):
                pct = int(max(0.0, min(1.0, ratio)) * 100)
                print(f"\n    {c('Agreement:', DIM)} {c(f'{pct}%', BGREEN)}")
        for field, value in stage.items():
            if field not in {"name", "responses", "agreement_ratio"}:
                _print_stage_evidence(field.replace("_", " ").title(), value)


def print_result(result: dict, verbose: bool = False):
    if not isinstance(result, dict):
        result = {}
    print_confidence(result.get("confidence", 0))
    print_routing(result.get("routing") or {})
    print_final_answer(result.get("final_answer", ""))
    print_dissent(result.get("dissent", []))
    print_stages(result.get("stages", []), verbose)
    print_audit(result.get("audit_trail", []), verbose)
    sid = result.get("id", result.get("session_id", ""))
    sid = sid if isinstance(sid, str) else ""
    if sid:
        print(
            f"\n  {c('Session ID:', DIM)} {c(sid[:8], BBLACK)}  {c('(vc show ' + sid[:8] + ')', DIM)}"
        )
    print()


# ── Data directory ────────────────────────────────────────────────────────────
def data_dir() -> Path:
    d = Path(__file__).parent / "data" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_result(result: dict):
    sid = result.get("id") or result.get("session_id")
    if not sid:
        return
    SessionStore(data_dir()).save(result)


# ── Core query ────────────────────────────────────────────────────────────────
async def run_query(query: str, protocol: str, verbose: bool) -> dict | None:
    try:
        from backend.config import CouncilConfig
        from backend.council.orchestrator import Orchestrator
        from backend.council.session import Session
    except ImportError as e:
        print(c(f"\n  ✗ Import error: {e}", BRED))
        print(c("  Run: pip install -e .", DIM))
        return None

    config = CouncilConfig()
    orchestrator = Orchestrator(config)
    session = Session(
        id=str(uuid.uuid4()),
        query=query,
        protocol=protocol,
        context=None,
        created_at=datetime.now(UTC).isoformat(),
    )

    print_query_echo(query, protocol)

    icon, color, _ = PROTOCOLS.get(protocol, ("?", WHITE, ""))
    with Spinner(f"Running {icon} {protocol} protocol", color):
        result = await orchestrator.run(session)

    result_dict = result.to_dict()
    save_result(result_dict)
    return result_dict


# ── Sub-commands ──────────────────────────────────────────────────────────────
def cmd_sessions():
    sessions = SessionStore(data_dir()).list_summaries(limit=25)
    if not sessions:
        print(c("\n  No sessions yet.\n", DIM))
        return
    print(f"\n  {c('Recent Sessions', BOLD)}")
    print(hr())
    for session in sessions:
        ts = session.get("created_at", "")[:16].replace("T", " ")
        proto = session.get("protocol", "?")
        icon, color, _ = PROTOCOLS.get(proto, ("?", WHITE, ""))
        q = _sanitize_terminal_text(session.get("query", ""))[:55]
        sid = c(session.get("id", "")[:8], BBLACK)
        proto_str = c(f"{icon} {proto}", color)
        print(f"  {sid}  {c(ts, DIM)}  {proto_str:<28}  {q}")
    print(hr())
    print()


def cmd_show(session_id: str, verbose: bool):
    result = SessionStore(data_dir()).find_prefix(session_id)
    if result is None:
        print(c(f"\n  ✗ Session not found: {session_id}\n", BRED))
        sys.exit(1)
    print_query_echo(result.get("query", ""), result.get("protocol", "council"))
    print_result(result, verbose)


def cmd_models():
    try:
        from backend.config import CouncilConfig

        config = CouncilConfig()
    except ImportError:
        print(c("\n  Run: pip install -e .\n", BRED))
        sys.exit(1)

    role_colors = {
        "architect": BMAGENTA,
        "coordinator": BBLUE,
        "implementer": BGREEN,
        "reviewer": BYELLOW,
        "speedster": BCYAN,
        "bulk-worker": DIM,
    }
    print(f"\n  {c('Council Models', BOLD)}")
    print(hr())
    for m in config.models:
        rc = role_colors.get(m.role, WHITE)
        strengths = c(", ".join(m.strengths[:3]), BBLACK)
        print(f"  {c(m.name, BOLD):<22} {c(m.role, rc):<20} {c(m.id, DIM)}")
        print(f"  {'':22} {strengths}")
        print()
    print(f"  {c('Chairman:', BOLD, DIM)} {c(config.chairman, BMAGENTA)}")
    print(hr())
    print()


def cmd_protocols():
    print(f"\n  {c('Deliberation Protocols', BOLD)}")
    print(hr())
    for pid, (icon, color, desc) in PROTOCOLS.items():
        print(f"  {c(icon + ' ' + pid, BOLD, color):<30} {c(desc, DIM)}")
    print(hr())
    print()


def format_health_summary(data: dict) -> str:
    providers = data.get("providers") or []
    ready_count = sum(1 for provider in providers if provider.get("ready"))
    provider_total = len(providers)
    agentmemory = data.get("agentmemory") or {}
    agentmemory_status = (
        "ready" if agentmemory.get("ready") else agentmemory.get("status", "unknown")
    )
    lines = [
        f"Status {data.get('status', 'unknown')}",
        f"Version {data.get('version', '?')}",
        f"Models {data.get('models', '?')}",
        f"Providers {ready_count}/{provider_total} ready",
        f"agentmemory {agentmemory_status}",
    ]
    warnings = [warning for warning in data.get("warnings", []) if "api_key" not in warning.lower()]
    lines.extend(f"Warning {warning}" for warning in warnings)
    return "\n".join(lines)


def cmd_serve(host: str, port: int):
    import uvicorn

    dist = Path(__file__).parent / "frontend" / "dist"
    demo = os.environ.get("VC_DEMO") == "1"
    print(f"\n  {c('WEIPING_COUNCIL', BOLD)}  {c(f'v{APP_VERSION}', DIM)}")
    print(f"  {c('*', BGREEN)} http://{host}:{port}" + (c('  (demo mode: canned replies)', BYELLOW) if demo else ""))
    if not dist.is_dir():
        print(f"  {c('-', DIM)} web UI not built; run: cd frontend && npm ci && npm run build")
        print(f"  {c('-', DIM)} the API is still available at http://{host}:{port}/docs")
    print()
    uvicorn.run("backend.main:app", host=host, port=port, log_level="warning")


def cmd_status():
    import httpx

    print(f"\n  {c('Backend Status', BOLD)}")
    print(hr())
    try:
        r = httpx.get("http://localhost:8000/api/health", timeout=3)
        data = r.json()
        ready = data.get("status") == "ok"
        status_color = BGREEN if ready else BYELLOW
        print(f"  {c('*', status_color)} Backend  {c('http://localhost:8000', BCYAN)}")
        for line in format_health_summary(data).splitlines():
            print(f"  {c('-', DIM)} {_sanitize_terminal_text(line)}")
    except Exception as e:
        print(f"  {c('*', BRED)} Backend unreachable  {c(type(e).__name__, DIM)}")
        print(f"  {c('-', DIM)} Run: uvicorn backend.main:app --reload --port 8000")
    print(hr())
    print()


def cmd_projects():
    """Show active research projects from shared memory."""
    try:
        from backend.memory.shared_memory import load_shared_memory

        ctx = load_shared_memory()
        if not ctx.projects_available:
            print(c("\n  Structured project metadata is unavailable from agentmemory.\n", DIM))
            return
        if not ctx.projects:
            print(c("\n  No active projects were reported by agentmemory.\n", DIM))
            return
        print(f"\n  {c('Active Research Projects', BOLD, BCYAN)}")
        print(hr())
        for p in ctx.projects:
            prio = p["priority"]
            name = p["name"]
            direction = _sanitize_terminal_text(p["direction"])[:70]
            status = p["status"][:70]
            print(f"  {c(f'P{prio}', BYELLOW)} {c(name, BOLD)}")
            print(f"     {c('Direction:', DIM)} {direction}")
            print(f"     {c('Status:', DIM)} {c(status, DIM)}")
        print(hr())
        print()
    except Exception:
        print(c("\n  ✗ Could not load projects from agentmemory.\n", BRED))


def cmd_context():
    """Show the project context that will be injected into queries."""
    try:
        from backend.memory.shared_memory import load_shared_memory

        ctx = load_shared_memory()
        block = ctx.as_context_block()
        if not block:
            print(c("\n  No context available.\n", DIM))
            return
        print(f"\n  {c('Injected Context', BOLD, BCYAN)}")
        print(hr())
        for line in block.split("\n"):
            print(f"  {_sanitize_terminal_text(line)}")
        print(hr())
        print()
    except Exception:
        print(c("\n  ✗ Could not load context from agentmemory.\n", BRED))


# ── Interactive REPL ──────────────────────────────────────────────────────────
REPL_HELP = f"""
  {c("Commands", BOLD)}
  {c("/protocol <name>", CYAN)}   switch protocol  (auto, council, debate, redteam, consensus, specialist, tournament)
  {c("/verbose", CYAN)}           toggle verbose mode (show all stages)
  {c("/sessions", CYAN)}          list recent sessions
  {c("/models", CYAN)}            list configured models
  {c("/protocols", CYAN)}         list all protocols
  {c("/status", CYAN)}            check backend health
  {c("/projects", CYAN)}          show active research projects
  {c("/context", CYAN)}           show current project context injected into queries
  {c("/clear", CYAN)}             clear screen
  {c("/help", CYAN)}              show this help
  {c("/quit", CYAN)}  or Ctrl-C   exit

  {c("Tip:", DIM)} Enter to send · Shift+Enter for newline
"""


async def repl():
    print_header()
    protocol = "council"
    verbose = False

    print(f"  {c('Type your question and press Enter.', DIM)}  {c('/help for commands', BBLACK)}")
    print()

    while True:
        icon, color, _ = PROTOCOLS.get(protocol, ("?", WHITE, ""))
        prompt = f"  {c(icon, color)} {c(protocol, BOLD, color)} {c('›', DIM)} "

        try:
            query = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {c('Goodbye.', DIM)}\n")
            break

        if not query:
            continue

        # Slash commands
        if query.startswith("/"):
            parts = query.split()
            cmd = parts[0].lower()

            if cmd in ("/quit", "/exit", "/q"):
                print(f"\n  {c('Goodbye.', DIM)}\n")
                break
            elif cmd == "/help":
                print(REPL_HELP)
            elif cmd == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                print_header()
            elif cmd == "/verbose":
                verbose = not verbose
                print(
                    f"  {c('Verbose mode:', DIM)} {c('on', BGREEN) if verbose else c('off', BBLACK)}\n"
                )
            elif cmd == "/sessions":
                cmd_sessions()
            elif cmd == "/models":
                cmd_models()
            elif cmd == "/status":
                cmd_status()
            elif cmd == "/protocol" and len(parts) > 1:
                p = parts[1].lower()
                if p in PROTOCOLS:
                    protocol = p
                    icon2, color2, desc = PROTOCOLS[p]
                    print(
                        f"  {c('Protocol →', DIM)} {c(icon2 + ' ' + p, BOLD, color2)}  {c(desc, DIM)}\n"
                    )
                else:
                    print(c(f"  Unknown protocol: {p}. Options: {', '.join(PROTOCOLS)}\n", BRED))
            elif cmd == "/projects":
                cmd_projects()
            elif cmd == "/context":
                cmd_context()
            else:
                print(c(f"  Unknown command: {cmd}. Type /help\n", BRED))
            continue

        # Regular query
        result = await run_query(query, protocol, verbose)
        if result:
            print_result(result, verbose)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    _configure_console_output()
    parser = argparse.ArgumentParser(
        prog="vc",
        description="Weiping Council — multi-LLM deliberation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          vc serve --demo                       # try the web UI without an API key
          vc serve                              # web UI + API on http://127.0.0.1:8000
          vc "Monolith or microservices?" --demo
          vc                                    # interactive REPL
          vc "What is the best way to learn Rust?"
          vc "Should I use microservices?" -p debate
          vc "My startup idea: X" -p redteam
          vc "Explain transformers" -p tournament -v
          vc sessions
          vc show abc123
          vc models
          vc protocols
          vc status
        """),
    )
    parser.add_argument(
        "query_or_cmd",
        nargs="?",
        help="Query text, or: serve / sessions / show / models / protocols / status",
    )
    parser.add_argument("session_id", nargs="?", help="Session ID (for 'show')")
    parser.add_argument(
        "-p",
        "--protocol",
        default="council",
        choices=list(PROTOCOLS.keys()),
        help="Deliberation protocol (default: council)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show all stages and audit trail"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use canned replies instead of calling models (no API key needed)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for serve")
    parser.add_argument("--port", type=int, default=8000, help="Port for serve")

    args = parser.parse_args()
    if args.demo:
        os.environ["VC_DEMO"] = "1"

    # No args → interactive REPL
    if not args.query_or_cmd:
        asyncio.run(repl())
        return

    cmd = args.query_or_cmd.lower()

    if cmd == "serve":
        cmd_serve(args.host, args.port)
    elif cmd == "sessions":
        cmd_sessions()
    elif cmd == "show":
        if not args.session_id:
            print(c("Usage: vc show <session_id>", BRED))
            sys.exit(1)
        cmd_show(args.session_id, args.verbose)
    elif cmd == "models":
        cmd_models()
    elif cmd == "protocols":
        cmd_protocols()
    elif cmd == "status":
        cmd_status()
    else:
        # One-shot query
        print_header()
        result = asyncio.run(run_query(args.query_or_cmd, args.protocol, args.verbose))
        if result:
            print_result(result, args.verbose)


if __name__ == "__main__":
    main()
