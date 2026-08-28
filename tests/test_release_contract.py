"""Release and handoff contract checks."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

from backend.config import APP_VERSION
from backend.main import QueryResponse
import scripts.release_scan as release_scan
from scripts.release_scan import SESSION_REQUIRED_FIELDS, check_sensitive_patterns


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _runtime_text(*parts: str) -> str:
    return bytes(byte for part in parts for byte in part.encode("utf-8")).decode("utf-8")


def test_version_consistency_across_runtime_packages_and_cli():
    pyproject = tomllib.loads(_read("pyproject.toml"))
    package = json.loads(_read("frontend/package.json"))
    lock = json.loads(_read("frontend/package-lock.json"))
    cli = _read("vc.py")

    assert pyproject["project"]["version"] == APP_VERSION
    assert package["version"] == APP_VERSION
    assert lock["version"] == APP_VERSION
    assert lock["packages"][""]["version"] == APP_VERSION
    assert package["engines"]["node"] == ">=22.18.0"
    assert lock["packages"][""]["engines"]["node"] == ">=22.18.0"
    assert "from backend.config import APP_VERSION" in cli


def test_release_scan_contract_blocks_mirror_registry_lockfiles():
    assert "registry.npmmirror.com" not in _read("frontend/package-lock.json")


def test_lint_rule_baseline_is_explicit_for_reproducible_ci():
    pyproject = tomllib.loads(_read("pyproject.toml"))

    assert pyproject["tool"]["ruff"]["lint"]["select"] == ["E4", "E7", "E9", "F"]


def test_repository_checkout_policy_preserves_release_snapshot_bytes():
    rules = {
        line.strip()
        for line in _read(".gitattributes").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "* text=auto eol=lf" in rules
    assert "*.png binary" in rules


def test_windows_launcher_anchors_paths_and_uses_project_virtualenv():
    launcher = _read("start.cmd")

    assert 'set "ROOT=%~dp0"' in launcher
    assert 'cd /d "%ROOT%"' in launcher
    assert 'set "PYTHON=%ROOT%.venv\\Scripts\\python.exe"' in launcher
    assert '"%PYTHON%" -m uvicorn' in launcher
    assert '/D "%FRONTEND%"' in launcher
    assert "VC_START_DRY_RUN" in launcher
    assert 'if not exist "%PYTHON%"' in launcher
    assert 'if not exist "%FRONTEND%\\node_modules"' in launcher


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe integration")
def test_windows_launcher_dry_run_is_safe_from_foreign_working_directory(tmp_path):
    env = {**os.environ, "VC_START_DRY_RUN": "1"}
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(ROOT / "start.cmd")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout.replace("/", "\\").lower()
    assert f"root={str(ROOT).lower()}" in output
    assert str(ROOT / ".venv" / "Scripts" / "python.exe").lower() in output
    assert str(ROOT / "frontend").lower() in output
    assert not (tmp_path / ".env").exists()


def test_public_sources_do_not_contain_operator_specific_absolute_paths():
    assert check_sensitive_patterns() == []


def _init_git_fixture(root: Path, tracked: dict[str, bytes]) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name, content in tracked.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        subprocess.run(["git", "-C", str(root), "add", "--", name], check=True)


def test_release_scan_reads_only_tracked_files(tmp_path, monkeypatch):
    _init_git_fixture(tmp_path, {"public.txt": b"public"})
    ignored = tmp_path / "node_modules" / "private" / "ignored.txt"
    ignored.parent.mkdir(parents=True)
    ignored.write_bytes(_runtime_text("sk-", "A" * 32).encode())
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    assert check_sensitive_patterns() == []


@pytest.mark.parametrize(
    "path",
    ["Dist/leak.txt", "Data/Sessions/leak.json", "Data/private.json", "Sessions/x.json"],
)
def test_release_scan_rejects_force_tracked_generated_files(tmp_path, monkeypatch, path):
    _init_git_fixture(tmp_path, {path: b"not releasable"})
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = check_sensitive_patterns()

    assert any("tracked generated/private path" in error for error in errors)


@pytest.mark.parametrize(
    "path",
    [
        ".env.local",
        ".netrc",
        ".git-credentials",
        "_netrc",
        "auth.json",
        ".docker/config.json",
        ".config/gh/hosts.yml",
        ".kube/config",
        ".ssh/config",
        "Credentials.json",
        "id_rsa",
        "keys/secret.pem",
        "frontend/.NPMRC",
    ],
)
def test_release_scan_rejects_sensitive_configuration_paths(path, monkeypatch):
    snapshots = {
        "index": {Path(path): b"benign"},
        "worktree": {Path(path): b"benign"},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    errors = check_sensitive_patterns()

    assert any("tracked generated/private path" in error for error in errors)


def test_release_scan_rejects_retired_local_performance_tracker(tmp_path, monkeypatch):
    tracked = {
        Path("backend/memory/tracker.py"): b"class PerformanceTracker: pass\n",
        Path("data/model_performance.json"): b"{}\n",
    }
    snapshots = {"index": tracked, "worktree": tracked}
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)

    errors = release_scan.check_sensitive_patterns()

    assert any("backend/memory/tracker.py" in error for error in errors)
    assert any("data/model_performance.json" in error for error in errors)


@pytest.mark.parametrize(
    "payload",
    [
        _runtime_text("sk-", "or-v1-", "A" * 32).encode(),
        _runtime_text("sk-", "B" * 32).encode("utf-16-le"),
        _runtime_text("github_", "pat_11", "C" * 76).encode(),
        "\\".join(["D:", "Temp", "operator-private"]).encode("utf-16-le"),
    ],
)
def test_release_scan_rejects_token_path_and_utf16_mutations(tmp_path, monkeypatch, payload):
    _init_git_fixture(tmp_path, {"leak.txt": payload})
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = check_sensitive_patterns()

    assert errors
    assert all(
        "AAAA" not in error and "BBBB" not in error and "CCCC" not in error for error in errors
    )


def test_release_scan_fails_if_tracked_sources_change_during_scan(monkeypatch):
    snapshots = iter(
        [
            {
                "index": {Path("public.txt"): b"public"},
                "worktree": {Path("public.txt"): b"public"},
            },
            {
                "index": {Path("public.txt"): b"changed"},
                "worktree": {Path("public.txt"): b"changed"},
            },
        ]
    )
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: next(snapshots))
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)

    assert "tracked sources changed during release scan" in check_sensitive_patterns()


def test_release_scan_main_rechecks_sources_after_every_gate(monkeypatch, capsys):
    snapshots = iter(
        [
            {
                "index": {Path("public.txt"): b"before"},
                "worktree": {Path("public.txt"): b"before"},
            },
            {
                "index": {Path("public.txt"): b"after"},
                "worktree": {Path("public.txt"): b"after"},
            },
        ]
    )
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: next(snapshots))
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)
    for name in (
        "check_versions",
        "check_lockfile_registry",
        "check_sensitive_patterns",
        "check_session_contract_docs",
        "check_tool_policy",
        "check_ci_contract",
    ):
        monkeypatch.setattr(release_scan, name, lambda: [])

    assert release_scan.main() == 1
    assert "changed during the complete release gate" in capsys.readouterr().out


def test_release_scan_reads_staged_index_even_when_worktree_is_safe(tmp_path, monkeypatch):
    _init_git_fixture(tmp_path, {"public.txt": b"SAFE=value\n"})
    candidate = tmp_path / "public.txt"
    candidate.write_text(
        _runtime_text("TOKEN=", "sk-", "or-v1-", "Z" * 32), encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "public.txt"], check=True)
    candidate.write_text("SAFE=value\n", encoding="utf-8")
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = check_sensitive_patterns()

    assert any("index:public.txt: blocked pattern secret-api-key" in error for error in errors)
    assert any("index and worktree differ" in error for error in errors)


def test_release_scan_compares_snapshots_even_if_git_diff_is_hidden(monkeypatch):
    snapshots = {
        "index": {Path("public.txt"): b"index"},
        "worktree": {Path("public.txt"): b"worktree"},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    errors = check_sensitive_patterns()

    assert "tracked index and worktree differ; stage or revert changes before release" in errors


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_release_scan_rejects_git_index_visibility_flags(tmp_path, monkeypatch, flag):
    _init_git_fixture(tmp_path, {"public.txt": b"public"})
    subprocess.run(["git", "-C", str(tmp_path), "update-index", flag, "public.txt"], check=True)
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = check_sensitive_patterns()

    assert any("assume-unchanged or skip-worktree" in error for error in errors)


def test_release_scan_rejects_and_does_not_echo_secret_shaped_filename(tmp_path, monkeypatch):
    secret_tail = "Z" * 32
    filename = _runtime_text("sk-", "or-v1-", secret_tail, ".txt")
    _init_git_fixture(tmp_path, {filename: b"public"})
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = check_sensitive_patterns()
    rendered = "\n".join(errors)

    assert "tracked path contains blocked pattern secret-api-key" in rendered
    assert secret_tail not in rendered


@pytest.mark.parametrize(
    "value",
    [
        "".join(("http://", "192.", "168.10.25:8080")),
        "".join(("http://", "169.", "254.10.25:8080")),
        "".join(("https://[", "fd", "12:3456::1]:8443")),
        "".join(("https://[", "fe", "80::1]:8443")),
        "".join(("https://service.", "internal:8443/path")),
        "".join(("https://service.", "local/path")),
        "".join(("https://", "user:pass@", "public.example/path")),
        "".join(("postgresql", "://", "user:pass@", "public-db.example/db")),
        "".join(("redis", "://", ":pass@", "cache.example/0")),
        "".join(("mongodb+srv", "://", "user:pass@", "cluster.example/db")),
        "".join(("db.", "internal:5432")),
    ],
)
def test_release_scan_rejects_private_endpoint_fragments(value, monkeypatch):
    import scripts.release_scan as release_scan

    snapshots = {
        "index": {Path("public.txt"): value.encode("utf-8")},
        "worktree": {Path("public.txt"): value.encode("utf-8")},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    errors = release_scan.check_sensitive_patterns()

    assert any("blocked pattern" in item for item in errors)


@pytest.mark.parametrize(
    "value",
    [
        _runtime_text("VC_PROVIDER_ARCHITECT_API_KEY=", "AIza", "A" * 35),
        _runtime_text(
            "Authorization: Bearer ",
            "eyJ",
            "A" * 24,
            ".",
            "B" * 24,
            ".",
            "C" * 24,
        ),
        '{"' + "VC_PROVIDER_ARCHITECT_API_KEY" + '":"' + "opaque_" + "A" * 40 + '"}',
        '{"' + "OPENAI_API_KEY" + '":"' + "opaque_" + "B" * 40 + '"}',
        '{"' + "Authorization" + '":"' + "Bearer " + "opaque_" + "C" * 40 + '"}',
        '{"' + "Authorization" + '":"' + "Basic " + "Q" * 24 + '=="}',
        '{"' + "OPENAI_API_KEY" + '":\n"' + "opaque_" + "D" * 40 + '"}',
        '{"' + "Authorization" + '":\n"' + "Bearer " + "opaque_" + "E" * 40 + '"}',
        r"{\"" + "OPENAI_API_KEY" + r"\":\"" + "opaque_" + "F" * 40 + r"\"}",
        r"{\"" + "Authorization" + r"\":\"" + "Bearer " + "opaque_" + "G" * 40 + r"\"}",
        "COHERE_API_KEY=" + "opaque_" + "H" * 40,
        "GOOGLE_API_KEY=" + "opaque_" + "I" * 40,
        "AWS_SECRET_ACCESS_KEY=" + "opaque_" + "J" * 40,
        "DB_PASSWORD=" + "opaque_" + "K" * 40,
        "DB_PASS" + "WORD=1.2.3",
        "SESSION_" + "".join(("COO", "KIE=^1.2.3")),
        "API_" + "".join(("K", "EY=2.0.0-beta")),
        "SLACK_WEBHOOK_URL=" + "https://hooks.example/" + "L" * 40,
        "SENTRY_DSN=" + "https://dsn.example/" + "M" * 40,
        "ACME_API_KEY=" + "\\\n" + "opaque_" + "N" * 40,
        "ACME_API_KEY: |\n  " + "opaque_" + "O" * 40,
        'DB_PASSWORD="' + "opaque!_" + "P" * 40 + '"',
        'DB_PASSWORD="' + "correct horse battery staple" + '"',
        "_ACME_API_KEY=" + "opaque_" + "Q" * 40,
        "SERVICE_CREDENTIALS=" + "opaque_" + "R" * 40,
        'OPENAI_API_KEY="' + "sk" + "\\x2d" + "S" * 32 + '"',
        "SECRET_KEY_BASE=" + "opaque_" + "T" * 40,
        "GOOGLE_APPLICATION_CREDENTIALS=" + "opaque_" + "U" * 40,
        "DOCKER_AUTH_CONFIG=" + "opaque_" + "V" * 40,
        "TOKEN_VALUE=" + "opaque_" + "W" * 40,
        "OPENAI_API_KEY_FILE=" + "opaque_" + "X" * 40,
        'DB_PASSWORD="' + "P@ssw0rd123!" + '"',
        'SESSION_COOKIE="' + "abc12345" + '"',
        "apiKey=" + "opaque_" + "Y" * 40,
        "apikey=" + "opaque_" + "Z" * 40,
        "accessToken=" + "opaque_" + "A" * 40,
        "refreshToken=" + "opaque_" + "B" * 40,
        "clientSecret=" + "opaque_" + "C" * 40,
        "privateKey=" + "opaque_" + "D" * 40,
        "databaseUrl=" + "https://db.example/" + "E" * 40,
        "webhookUrl=" + "https://hooks.example/" + "F" * 40,
        "githubPat=" + "opaque_" + "G" * 40,
        "connectionString=" + "opaque_" + "H" * 40,
        "serviceCookieValue=" + "opaque_" + "I" * 40,
        "providerAuthorizationValue=" + "opaque_" + "J" * 40,
        'DB_PASSWORD="' + "don't_share_" + "H" * 24 + '"',
        "DB_PASSWORD='" + 'say"no_' + "I" * 24 + "'",
        'DB_PASSWORD="' + 'abc\\"def_' + "J" * 24 + '"',
        "ACME_API_" + "K" + "EY: |2-\n  " + "opaque_" + "K" * 40,
        "DB_PASS" + "WORD=" + '"""' + "opaque_" + "O" * 40 + '"""',
        "DB_PASS" + 'WORD="' + "abc\n" + "def_" + "P" * 32 + '"',
        "".join(("DB_PASS", "WORD=letmein")),
        "".join(("DB_PASS", 'WORD="letmein"')),
        "".join(("SESSION_", "COO", "KIE=abc1234")),
        "".join(("API_", "K", "EY=abcdefg")),
        "".join(("Author", "ization: Bearer abcdefghijkl")),
        "".join(("Author", "ization: Token abcdefghijkl")),
        "".join(("Author", "ization: ApiKey abcdefghijkl")),
        'settings:\n  "' + "OPENAI_API_KEY" + '": "' + "opaque_" + "Q" * 40 + '"',
        "headers:\n  x-api-key: " + "opaque_" + "R" * 40,
        "config:\n  db-pass" + "word: letmein",
        "headers:\n  x.api.key: " + "opaque_" + "S" * 40,
        "ACME_API_KEY=" + "test_live_" + "L" * 32,
        "ACME_API_KEY=" + "your_live_" + "M" * 32,
        "OPENAI_API_KEY" + "\\075" + "opaque_" + "N" * 40,
        _runtime_text("glpat-", "A" * 32),
        _runtime_text("hvs.", "A" * 32),
        _runtime_text("hf_", "A" * 32),
        _runtime_text("npm_", "A" * 32),
    ],
)
def test_release_scan_rejects_role_and_common_provider_credentials_without_echo(value, monkeypatch):
    snapshots = {
        "index": {Path("public.txt"): value.encode("utf-8")},
        "worktree": {Path("public.txt"): value.encode("utf-8")},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    rendered = "\n".join(check_sensitive_patterns())

    assert "blocked pattern" in rendered
    assert value not in rendered


@pytest.mark.parametrize(
    "value",
    [
        "OPENAI_API_KEY=replace_with_your_api_key",
        "TOKEN_COUNT=" + "1" * 40,
        "API_KEY_ROTATION=automatic_rotation_policy_enabled",
        "OPENAI_API_KEY=replace_me_with_your_api_key",
        "OPENAI_API_KEY=redacted_redacted_redacted",
    ],
)
def test_release_scan_preserves_explicit_placeholders_and_benign_metrics(value, monkeypatch):
    snapshots = {
        "index": {Path("public.txt"): value.encode("utf-8")},
        "worktree": {Path("public.txt"): value.encode("utf-8")},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    assert check_sensitive_patterns() == []


def test_python_reference_exemption_is_limited_to_the_assignment_prefix():
    fixture_name = _runtime_text("OPENAI_API_K", "EY")
    marker = "OPAQUECREDENTIALVALUE7319"
    safe_reference = _runtime_text("api_", "ke", f'y = source_env["{fixture_name}"]')
    unsafe_values = [
        f'payload = wrapper("{fixture_name}={marker}")',
        f'payload = wrapper(value="{fixture_name}={marker}")',
        f'payload = ["{fixture_name}={marker}"]',
        f'payload = "{fixture_name}={marker}"',
        f"# {fixture_name}={marker}",
    ]

    assert not release_scan._contains_configured_credential(
        safe_reference, source_path=Path("probe.py")
    )
    assert all(
        release_scan._contains_configured_credential(value, source_path=Path("probe.py"))
        for value in unsafe_values
    )


def test_python_ast_reconstructs_static_credentials_and_subscript_targets():
    fixture_name = _runtime_text("OPENAI_API_K", "EY")
    fixture_value = _runtime_text("opaque_", "F9k3Lm7Q2xW8v6N4p2Q7")
    sources = [
        f'{fixture_name} = "opaque_" + "F9k3Lm7Q2xW8v6N4p2Q7"',
        f'os.environ["{fixture_name}"] = "{fixture_value}"',
        f'settings = {{"{fixture_name}": "{fixture_value}"}}',
        f'header = "Author" + "ization: Bearer {fixture_value}"',
    ]

    for source in sources:
        raw = source.encode("utf-8")
        views = release_scan._configured_credential_views(
            raw, Path("probe.py"), release_scan._scan_views(raw)
        )
        assert any(
            release_scan._contains_configured_credential(view, source_path=path)
            for view, path in views
        )


def test_structured_and_python_setter_credentials_fail_closed():
    fixture_name = _runtime_text("OPENAI_API_K", "EY")
    database_name = _runtime_text("DB_PASS", "WORD")
    fixture_value = _runtime_text("opaque_", "F9k3Lm7Q2xW8v6N4p2Q7")
    punctuation = "!abcDEF7"
    tick = chr(96)
    header_name = _runtime_text("x-api-", "key")
    generic_field_name = _runtime_text("to", "ken")
    structured = [
        f'$env:{fixture_name} = "{fixture_value}"',
        f"ENV {fixture_name} {fixture_value}",
        f'process.env["{fixture_name}"]="{fixture_value}"',
        f'headers["{header_name}"]="{fixture_value}"',
        f'- name: "{fixture_name}"\n  value: "{fixture_value}"',
        f'os.Setenv("{fixture_name}", "{fixture_value}")',
        f'<add name="{fixture_name}" value="{fixture_value}" />',
        f'Set-Item -Path Env:{fixture_name} -Value "{fixture_value}"',
        f'process.env["{fixture_name}"]={tick}{fixture_value}{tick}',
        f'os.Setenv("{fixture_name}", {tick}{fixture_value}{tick})',
        f'<add value="{fixture_value}" name="{fixture_name}" />',
        f'<add value="{fixture_value}" ' + "k" + f'ey="{fixture_name}" />',
        f'${{env:{fixture_name}}}="{fixture_value}"',
        f'[Environment]::SetEnvironmentVariable("{fixture_name}","{fixture_value}")',
        f'Set-Item Env:\\{fixture_name} -Value "{fixture_value}"',
        f'Set-Item -LiteralPath Env:{fixture_name} -Value "{fixture_value}"',
        f'Set-Item -Value "{fixture_value}" -Path Env:{fixture_name}',
        f'Set-Item -Path Env:{fixture_name} {tick}\n  -Value "{fixture_value}"',
        f'[Environment]::SetEnvironmentVariable(\n  "{fixture_name}",\n'
        f'  "{fixture_value}",\n  "Process"\n)',
        f"$env:{fixture_name} = @'\n{fixture_value}\n'@",
        f'$env:{fixture_name} = @"\n{fixture_value}\n"@',
        f"${{env:{fixture_name}}} = @'\n{fixture_value}\n'@",
        f"[Environment]::SetEnvironmentVariable('{fixture_name}', "
        f"@'\n{fixture_value}\n'@, 'Process')",
        f'[Environment]::SetEnvironmentVariable("{fixture_name}", '
        f'"{fixture_value[:2]}" + "{fixture_value[2:]}", "Process")',
        f"- name: {fixture_name}\n  optional: false\n  value: {fixture_value}",
        f"- value: {fixture_value}\n  optional: false\n  name: {fixture_name}",
        f"- name: {fixture_name}\n  # fixture comment\n\n  value: {fixture_value}",
        f"- value: {fixture_value}\n  # fixture comment\n\n  name: {fixture_name}",
        f"- {{name: {fixture_name}, value: {fixture_value}}}",
        f"- {{value: {fixture_value}, name: {fixture_name}}}",
        f'- "name": {fixture_name}\n  "value": {fixture_value}',
        f"- 'value': {fixture_value}\n  'name': {fixture_name}",
        f'{{"safe":"x","{generic_field_name}":"{fixture_value}"}}',
        f'config: {{ {generic_field_name}: "{fixture_value}" }}',
        f"export {fixture_name}={fixture_value}",
        f'<environmentVariable name="{fixture_name}" value="{fixture_value}"/>',
        f"os.Setenv({tick}{fixture_name}{tick}, {tick}{fixture_value}{tick})",
        "".join(("Author", f"ization: Token {punctuation}")),
        "".join(("Author", f"ization: ApiKey {punctuation}")),
        "".join(("Author", "ization: Token tok:abc123")),
        "".join(("Author", "ization: ApiKey abc,def")),
        "".join(("Author", "ization: Token ]abcDEF7")),
        "".join(("Author", "ization: Token }abcDEF7")),
        "".join(("Author", 'ization: Digest response="abcDEF7"')),
    ]
    structured.extend(
        "".join(("Author", f"ization: {scheme} {quote}abc,def123{quote}"))
        for scheme in ("Basic", "Bearer", "Token", "ApiKey")
        for quote in ("'", '"')
    )
    assert all(release_scan._contains_configured_credential(value) for value in structured)
    assert not release_scan._contains_configured_credential("Authorization: Digest")

    setters = [
        f'os.putenv("{fixture_name}", "{fixture_value}")',
        f'os.environ.setdefault("{fixture_name}", "{fixture_value}")',
        f'config.set("{database_name}", "{fixture_value}")',
        f'set_key(".env", "{fixture_name}", "{fixture_value}")',
        'putenv(k' + f'ey="{fixture_name}", value="{fixture_value}")',
        f'config.set(option="{database_name}", value="{fixture_value}")',
        f'dotenv.set_key(dotenv_path=".env", key_to_set="{fixture_name}", '
        f'value_to_set="{fixture_value}")',
        f'import os as o\no.putenv("{fixture_name}", "{fixture_value}")',
        f'from os import putenv as writer\nwriter("{fixture_name}", "{fixture_value}")',
        f'import os\nwriter = os.putenv\nwriter("{fixture_name}", "{fixture_value}")',
        f'import os\nwriter = os.putenv\nwriter("{fixture_name}", '
        f'"{fixture_value}")\nwriter = print',
        f"import os\nwriter = os.putenv\ndef shadow():\n    writer = print\n"
        f'writer("{fixture_name}", "{fixture_value}")',
        f"import os\nwriter = os.putenv\nif False:\n    writer = print\n"
        f'writer("{fixture_name}", "{fixture_value}")',
        f'import os\nwriter = helper = os.putenv\nwriter("{fixture_name}", "{fixture_value}")',
        f'from dotenv import set_key as writer\nwriter(".env", "{fixture_name}", '
        f'"{fixture_value}")',
    ]
    for source in setters:
        raw = source.encode("utf-8")
        views = release_scan._configured_credential_views(
            raw, Path("probe.py"), release_scan._scan_views(raw)
        )
        assert any(
            release_scan._contains_configured_credential(view, source_path=path)
            for view, path in views
        )

    source_reference = "SOURCE_" + "KEY"
    references = [
        f"$env:{fixture_name} = $env:SOURCE_KEY",
        f"ENV {fixture_name} ${{{source_reference}}}",
        f"ENV {fixture_name} ${{{source_reference}:-fallback}}",
        f"ENV {fixture_name} ${{{source_reference}:-}}",
        f"${{env:{fixture_name}}} = ${{env:{source_reference}}}",
        f"Set-Item -Path Env:{fixture_name} -Value ${{env:{source_reference}}}",
        f'[Environment]::SetEnvironmentVariable("{fixture_name}",'
        f' "${{env:{source_reference}}}", "Process")',
        f"- {{name: {fixture_name}, value: ${{{source_reference}}}}}",
        f'- "name": {fixture_name}\n  "value": ${{{source_reference}}}',
        f"- name: {fixture_name}\n  valueFrom:\n    secretKeyRef:\n"
        "      name: provider\n      key: provider",
    ]
    assert all(not release_scan._contains_configured_credential(value) for value in references)

    reference_field = "k" + "ey"
    separated_reference = _runtime_text(
        f"secretKeyRef:\n  name: app\n  {reference_field}: provider\n"
        f"unrelated:\n  {reference_field}: {fixture_value}"
    )
    assert release_scan._contains_configured_credential(separated_reference)

    safe_python = [
        "".join(("lookup(k", 'ey="customer_id")')),
        "".join(('metadata = {"k', 'ey": "display_name"}')),
        "".join(("k", 'ey = "primary_label"')),
        "".join(("k", 'ey = "name"')),
        "".join(("lookup(k", 'ey="type")')),
        "".join(("k", 'ey = "customer-id"')),
        "".join(("k", 'ey = "customerId"')),
    ]
    unsafe_names = ("pass" + "word", "sec" + "ret", "to" + "ken", "k" + "ey", "au" + "th")
    unsafe_python = [f'{name}="abcd1234"' for name in unsafe_names]
    high_entropy = "Q7m9V2x4C8p6R3t5N1s4"
    alphabetic_entropy = "qmvxcpzrtnshdfwkabeg"
    generic_name = "k" + "ey"
    unsafe_python.extend(
        (
            f'{generic_name}="{high_entropy}_id"',
            f'data={{"{generic_name}": "{high_entropy}_label"}}',
            f'lookup({generic_name}="{high_entropy}_name")',
            f'{generic_name}="{alphabetic_entropy}_id"',
            f'data={{"{generic_name}": "{alphabetic_entropy}_label"}}',
        )
    )

    def configured_hit(source: str) -> bool:
        raw = source.encode()
        return any(
            release_scan._contains_configured_credential(view, source_path=path)
            for view, path in release_scan._configured_credential_views(
                raw, Path("probe.py"), release_scan._scan_views(raw)
            )
        )

    assert all(not configured_hit(source) for source in safe_python)
    assert all(configured_hit(source) for source in unsafe_python)


def test_structured_scanner_patterns_are_bounded_on_ci_yaml():
    workflow = _read(".github/workflows/ci.yml")
    started = time.perf_counter()

    for pattern in release_scan.STRUCTURED_CREDENTIAL_ASSIGNMENTS:
        tuple(pattern.finditer(workflow))

    assert time.perf_counter() - started < 2.0


def test_python_static_high_risk_tokens_are_reconstructed(monkeypatch):
    prefixes = ("g" + "hp_", "h" + "f_", "n" + "pm_", "s" + "k-")
    tail = "A" * 32
    for prefix in prefixes:
        sources = [
            f'message = "{prefix}" + "{tail}"\n',
            f'def reveal():\n    return "{prefix}" + "{tail}"\n',
            f'matched = candidate == "{prefix}" + "{tail}"\n',
            f'def f(value="{prefix}" + "{tail}"):\n    return value\n',
            f'message = "".join(("{prefix[:2]}", "{prefix[2:]}", "{tail}"))\n',
            f"message = f'{prefix}{{\"{tail}\"}}'\n",
        ]
        for source in sources:
            snapshots = {
                "index": {Path("probe.py"): source.encode()},
                "worktree": {Path("probe.py"): source.encode()},
            }
            monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
            monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
            monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

            assert any("blocked pattern" in item for item in check_sensitive_patterns())


def test_python_named_static_values_flow_into_signatures_and_credential_sinks(monkeypatch):
    tail = "A" * 36
    token_sources = [
        f'a="gh"\nb="p_"\nc="{tail}"\nx=a+b+c\n',
        f'a="gh"\nb="p_"\nc="{tail}"\nx="".join((a,b,c))\n',
        f'a="gh"\nb="p_"\nc="{tail}"\nx=f"{{a}}{{b}}{{c}}"\n',
    ]
    credential_sources = [
        'x="opaque_' + tail + '"\npayload={"to' + 'ken": x}\n',
        'import os\nx="opaque_' + tail + '"\nos.putenv("TO' + 'KEN", x)\n',
        'x="opaque_' + tail + '"\npayload={"to' + 'ken": x}\nx="cleared"\n',
        'if condition:\n    x="opaque_' + tail + '"\nelse:\n    x=source\n'
        'payload={"to' + 'ken": x}\n',
        'try:\n    x="opaque_' + tail + '"\nexcept Exception:\n    x=source\n'
        'payload={"to' + 'ken": x}\n',
        'for item in items:\n    x="opaque_' + tail + '"\npayload={"to' + 'ken": x}\n',
        'x="opaque_' + tail + '" if condition else source\npayload={"to' + 'ken": x}\n',
        'x=source or "opaque_' + tail + '"\npayload={"to' + 'ken": x}\n',
        'x=config.get("source", "opaque_' + tail + '")\npayload={"to' + 'ken": x}\n',
        'import os\nto' + 'ken=os.getenv("TOKEN", "opaque_' + tail + '")\n',
        'import os\nto' + 'ken=os.getenv("TOKEN") or "opaque_' + tail + '"\n',
        'def reveal():\n    x="opaque_' + tail + '"\n    return {"to' + 'ken": x}\n',
        'class Reveal:\n    x="opaque_' + tail + '"\n    payload={"to' + 'ken": x}\n',
    ]
    for source in (*token_sources, *credential_sources):
        snapshots = {
            "index": {Path("probe.py"): source.encode()},
            "worktree": {Path("probe.py"): source.encode()},
        }
        monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
        monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
        monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

        assert any("blocked pattern" in item for item in check_sensitive_patterns())

    dynamic_sources = [
        'def render(x):\n    return {"to' + 'ken": x}\n',
        'x="opaque_' + tail + '"\ndef render(x):\n    return {"to' + 'ken": x}\n',
        'import os\nto' + 'ken=os.getenv("TOKEN", "${TOKEN}")\n',
        'x="access_' + 'token_id" if condition else source\npayload={"to' + 'ken": x}\n',
        f'a="gh"\na=source\nb="p_"\nc="{tail}"\nx=a+b+c\n',
    ]
    for source in dynamic_sources:
        snapshots = {
            "index": {Path("probe.py"): source.encode()},
            "worktree": {Path("probe.py"): source.encode()},
        }
        monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)

        assert check_sensitive_patterns() == []


def test_javascript_static_values_are_reconstructed_without_flagging_dynamic_references(
    monkeypatch,
):
    tail = "A" * 36
    unsafe_sources = [
        f'const x = "gh" + "p_" + "{tail}";\n',
        f'const x = `gh${{"p_"}}{tail}`;\n',
        f'const x = ["gh", "p_", "{tail}"].join("");\n',
        f'const x = "gh" +\n  "p_" +\n  "{tail}";\n',
        f'const x = "gh" /* split */ + // split\n  "p_" + "{tail}";\n',
        f'const x: string = "gh" + "p_" + "{tail}";\n',
        f'let x = "gh" + "p_" + "{tail}";\n',
        f'var x = "gh" + "p_" + "{tail}";\n',
        f'const x = "gh" + "p_" + "{tail}"\nconsole.log(x);\n',
        f'const x = "gh" + "p_" + "{tail}" // done\nconsole.log(x);\n',
        f'const x = "gh" + "p_" + "{tail}" /* done */\nconsole.log(x);\n',
        'const x = "opaque_' + tail + '"; const payload = { to' + 'ken: x };\n',
        'const x =\n  "opaque_' + tail + '"; const payload = { to' + 'ken: x };\n',
        'const x = "opaque_' + tail + '" // done\nconst payload = { to' + 'ken: x };\n',
        'let x = "opaque_' + tail + '"; const payload = { to' + 'ken: x }; '
        'x = "cleared";\n',
        'const x = "opaque_' + tail + '"; const payload = { to' + 'ken: x }; '
        'function render(x) { return x; }\n',
        'let x; if (condition) { x = "opaque_' + tail + '"; } '
        'else { x = source; } const payload = { to' + 'ken: x };\n',
        'let x; if (condition) { x = source; } '
        'else { x = "opaque_' + tail + '"; } const payload = { to' + 'ken: x };\n',
        'const x = condition ? "opaque_' + tail + '" : source; '
        'const payload = { to' + 'ken: x };\n',
        'const x = source || "opaque_' + tail + '"; const payload = { to'
        + 'ken: x };\n',
        'const x = source ?? "opaque_' + tail + '"; const payload = { to'
        + 'ken: x };\n',
        'const to' + 'ken = process.env.TOKEN || "opaque_' + tail + '";\n',
        'const to' + 'ken = process.env.TOKEN ?? "opaque_' + tail + '";\n',
    ]
    for source in unsafe_sources:
        snapshots = {
            "index": {Path("probe.js"): source.encode()},
            "worktree": {Path("probe.js"): source.encode()},
        }
        monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
        monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
        monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

        assert any("blocked pattern" in item for item in check_sensitive_patterns())

    safe_sources = [
        'function render(x) { return { to' + 'ken: x }; }\n',
        'const x = process.env.SOURCE; const payload = { to' + 'ken: x };\n',
        'const x = "opaque_' + tail + '"; x = process.env.SOURCE; '
        'const payload = { to' + 'ken: x };\n',
        'const x = "opaque_' + tail + '"; function render(x) { return { to'
        + 'ken: x }; }\n',
        'const x = "opaque_' + tail + '"; class C { render(x) { return { to'
        + 'ken: x }; } }\n',
        'const x = "opaque_' + tail + '"; const renderer = { render(x) { return { to'
        + 'ken: x }; } };\n',
        'const x = "opaque_' + tail + '"; const render = x => ({ to'
        + 'ken: x });\n',
        'const x = "opaque_' + tail + '"; const render = (x) => ({ to'
        + 'ken: x });\n',
        'const to' + 'ken = process.env.TOKEN || "${TOKEN}";\n',
        'const x = condition ? "access_' + 'token_id" : source; const payload = { to'
        + 'ken: x };\n',
    ]
    for source in safe_sources:
        snapshots = {
            "index": {Path("probe.js"): source.encode()},
            "worktree": {Path("probe.js"): source.encode()},
        }
        monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)

        assert check_sensitive_patterns() == []


def test_late_bound_closures_and_literal_destructuring_preserve_python_scope_safety():
    secret = _runtime_text("opaque_", "Q7m9V2x4C8p6R3t5N1s4D8f2")

    def configured_hit(source: str) -> bool:
        raw = source.encode()
        return any(
            release_scan._contains_configured_credential(view, source_path=path)
            for view, path in release_scan._configured_credential_views(
                raw, Path("probe.py"), release_scan._scan_views(raw)
            )
        )

    unsafe_sources = (
        _runtime_text(
            'def reveal():\n    return {"to',
            'ken": value}\nvalue="',
            secret,
            '"\n',
        ),
        _runtime_text(
            'def outer():\n    def reveal():\n        return {"to',
            'ken": value}\n    value="',
            secret,
            '"\n',
        ),
        _runtime_text('value, = ("', secret, '",)\npayload={"to', 'ken": value}\n'),
        _runtime_text('[value] = ["', secret, '"]\npayload={"to', 'ken": value}\n'),
        _runtime_text('def reveal(value="', secret, '"):\n    return {"to', 'ken": value}\n'),
        _runtime_text(
            'value="', secret, '"\ndef reveal(alias=value):\n    return {"to', 'ken": alias}\n'
        ),
        _runtime_text('def reveal(*, value="', secret, '"):\n    return {"to', 'ken": value}\n'),
        _runtime_text('items=[{"to', 'ken": value} for value in ["', secret, '"]]\n'),
        _runtime_text('items=[(to', 'ken := value) for value in ["', secret, '"]]\n'),
    )
    safe_sources = (
        _runtime_text(
            'def reveal(value):\n    return {"to',
            'ken": value}\nvalue="',
            secret,
            '"\n',
        ),
        _runtime_text(
            'def reveal():\n    value = source\n    return {"to',
            'ken": value}\nvalue="',
            secret,
            '"\n',
        ),
        _runtime_text('value, = (source,)\npayload={"to', 'ken": value}\n'),
        _runtime_text(
            'value="', secret, '"\nitems=[{"to', 'ken": value} for value in source]\n'
        ),
        _runtime_text(
            'value="', secret, '"\ntry:\n    work()\nexcept Exception as value:\n'
            '    payload={"to', 'ken": value}\n'
        ),
        _runtime_text(
            'value="', secret, '"\nmatch source:\n    case value:\n        payload={"to',
            'ken": value}\n',
        ),
    )

    assert all(configured_hit(source) for source in unsafe_sources)
    assert all(not configured_hit(source) for source in safe_sources)


def test_javascript_closure_control_destructuring_and_lexical_block_flow_are_scoped():
    secret = _runtime_text("opaque_", "Q7m9V2x4C8p6R3t5N1s4D8f2")

    def configured_hit(source: str) -> bool:
        raw = source.encode()
        return any(
            release_scan._contains_configured_credential(view, source_path=path)
            for view, path in release_scan._configured_credential_views(
                raw, Path("probe.js"), release_scan._scan_views(raw)
            )
        )

    unsafe_sources = (
        _runtime_text('function reveal(){return {to', 'ken:value};}\nconst value="', secret, '";'),
        _runtime_text('const reveal=()=>({to', 'ken:value});\nconst value="', secret, '";'),
        _runtime_text(
            'const renderer={reveal(){return {to',
            'ken:value};}};\nconst value="',
            secret,
            '";',
        ),
        _runtime_text(
            'let value="', secret, '";if(condition)value=source;const payload={to',
            'ken:value};',
        ),
        _runtime_text(
            'let value="', secret, '";while(condition)value=source;const payload={to',
            'ken:value};',
        ),
        _runtime_text(
            'let value="', secret, '";for(;condition;)value=source;const payload={to',
            'ken:value};',
        ),
        _runtime_text('const [value]=["', secret, '"];const payload={to', 'ken:value};'),
        _runtime_text(
            'const {item:value}={item:"', secret, '"};const payload={to', 'ken:value};'
        ),
        _runtime_text(
            'const value="', secret, '";{const value=source;}const payload={to',
            'ken:value};',
        ),
        _runtime_text(
            'const value="', secret, '";for(let value=source;condition;){}'
            'const payload={to', 'ken:value};'
        ),
        _runtime_text(
            'for(let value="', secret, '";condition;value++){const payload={to',
            'ken:value};}',
        ),
        _runtime_text(
            'for(const value of ["', secret, '"]){const payload={to', 'ken:value};}'
        ),
        _runtime_text(
            'for(const {node:{value}} of [{node:{value:"', secret,
            '"}}]){const payload={to', 'ken:value};}',
        ),
        _runtime_text('function reveal(value="', secret, '"){return {to', 'ken:value};}'),
        _runtime_text(
            'const value="', secret, '";function reveal(alias=value){return {to',
            'ken:alias};}',
        ),
        _runtime_text('const reveal=(value="', secret, '")=>({to', 'ken:value});'),
        _runtime_text(
            'function reveal({node:{value="', secret,
            '"}}){return {to', 'ken:value};}',
        ),
        _runtime_text(
            'const {value="', secret, '"}=source;const payload={to', 'ken:value};'
        ),
        _runtime_text(
            'const {item:value="', secret, '"}={};const payload={to', 'ken:value};'
        ),
        _runtime_text('const [value="', secret, '"]=[];const payload={to', 'ken:value};'),
        _runtime_text('const value="', secret, '";headers.set("Authorization",value);'),
        _runtime_text('const value="', secret, '";config.append("to', 'ken",value);'),
        _runtime_text(
            'const value="', secret, '";const payload={["to', 'ken"]:value};'
        ),
        _runtime_text(
            'const value="', secret, '";const payload={"to', 'ken":value};'
        ),
        _runtime_text('const value="', secret, '";headers["to', 'ken"]=value;'),
        _runtime_text(
            'const {node:{value}}={node:{value:"', secret,
            '"}};const payload={to', 'ken:value};',
        ),
        _runtime_text(
            'const [[value]]=[["', secret, '"]];const payload={to', 'ken:value};'
        ),
        _runtime_text(
            'const key="to', 'ken";const value="', secret,
            '";const payload={[key]:value};',
        ),
        _runtime_text(
            'const value="', secret,
            '";const payload={["to"+"ken"]:value};',
        ),
        _runtime_text(
            'const key="to', 'ken";const value="', secret,
            '";config.set(key,value);',
        ),
    )
    safe_sources = (
        _runtime_text(
            'function reveal(value){return {to',
            'ken:value};}\nconst value="',
            secret,
            '";',
        ),
        _runtime_text(
            'function reveal(){const value=source;return {to',
            'ken:value};}\nconst value="',
            secret,
            '";',
        ),
        _runtime_text(
            'let value="', secret, '";value=source;const payload={to', 'ken:value};'
        ),
        _runtime_text('const [value]=[source];const payload={to', 'ken:value};'),
        _runtime_text(
            'const value=source;{const value="', secret, '";}const payload={to',
            'ken:value};',
        ),
        _runtime_text(
            'const value="', secret, '";function reveal({value}){return {to',
            'ken:value};}',
        ),
        _runtime_text(
            'const value="', secret, '";const reveal=([value])=>({to', 'ken:value});'
        ),
        _runtime_text(
            'const value="', secret, '";try{work();}catch(value){const payload={to',
            'ken:value};}',
        ),
        _runtime_text(
            'const value="', secret, '";for(const value of source){const payload={to',
            'ken:value};}',
        ),
        _runtime_text(
            'const value="', secret,
            '";for(const {node:{value}} of source){const payload={to',
            'ken:value};}',
        ),
        _runtime_text(
            'const value=source;for(const value of ["', secret,
            '"]){}const payload={to', 'ken:value};',
        ),
        _runtime_text(
            'const value="', secret, '";const doc="payload={to', 'ken:value}";'
        ),
        _runtime_text(
            'const value="', secret, '";const doc=`payload={to', 'ken:value}`;'
        ),
        _runtime_text('const value="', secret, '";const pattern=/{to', 'ken:value}/;'),
        _runtime_text(
            'const value="', secret, '";headers.set(dynamicName,value);'
        ),
        _runtime_text(
            'const value="', secret,
            '";function reveal({node:{value}}){return {to', 'ken:value};}',
        ),
        _runtime_text(
            'const value="', secret,
            '";function reveal([[value]]){return {to', 'ken:value};}',
        ),
        _runtime_text(
            'const value="', secret,
            '";function reveal({...value}){return {to', 'ken:value};}',
        ),
        _runtime_text(
            'const key=source;const value="', secret,
            '";const payload={[key]:value};',
        ),
        _runtime_text(
            'const key=source;const value="', secret,
            '";config.set(key,value);',
        ),
    )

    assert all(configured_hit(source) for source in unsafe_sources)
    assert all(not configured_hit(source) for source in safe_sources)


def test_javascript_static_analysis_is_bounded_for_large_scope_and_literal_sets():
    sources = (
        "\n".join(
            f"const payload{index}={{value:source{index}}};"
            f"const meta{index}={{field:payload{index}.value}};"
            for index in range(2000)
        ),
        "\n".join(
            f"{{const local{index}=source{index};use(local{index});}}"
            for index in range(2000)
        ),
        "\n".join(
            f"function probe{index}(value{index}){{return value{index};}}"
            for index in range(2000)
        ),
    )
    for source in sources:
        release_scan._javascript_static_analysis.cache_clear()
        started = time.perf_counter()

        release_scan._javascript_static_analysis(source)

        assert time.perf_counter() - started < 3.0


def test_package_lock_path_key_semver_is_the_only_semver_exemption():
    value = _runtime_text('"path-', "k", 'ey": "^3.1.1"')
    assert not release_scan._contains_configured_credential(
        value, source_path=Path("frontend/package-lock.json")
    )
    assert release_scan._contains_configured_credential(value, source_path=Path("config.json"))


@pytest.mark.parametrize("name", [".envrc", ".vault-token", ".pgpass", ".htpasswd"])
def test_release_scan_rejects_additional_private_credential_files(name, monkeypatch):
    snapshots = {
        "index": {Path(name): b"opaque"},
        "worktree": {Path(name): b"opaque"},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    assert any("generated/private path" in item for item in check_sensitive_patterns())


@pytest.mark.parametrize(
    "path",
    [
        "frontend/index.html",
        "frontend/public/favicon.svg",
        "config.ini",
        "script.sh",
        "notes.xml",
        "asset.bin",
    ],
)
def test_release_scan_scans_every_tracked_file_type(path, monkeypatch):
    import scripts.release_scan as release_scan

    marker = _runtime_text("sk-", "Z" * 32).encode("ascii")
    snapshots = {"index": {Path(path): marker}, "worktree": {Path(path): marker}}
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    errors = release_scan.check_sensitive_patterns()

    assert any("blocked pattern secret-api-key" in item for item in errors)


def test_release_scan_uses_bounded_binary_fast_path(monkeypatch):
    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 12_288
    snapshots = {
        "index": {Path("banner.png"): payload},
        "worktree": {Path("banner.png"): payload},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    started = time.perf_counter()
    errors = check_sensitive_patterns()

    assert errors == []
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize(
    ("metadata", "expected_code"),
    [
        (
            ("YEK_IPA_IANEPO"[::-1] + "=opaque_" + "Z" * 32).encode(),
            "configured-api-key",
        ),
        ("1v/1.0.861.291//:sptth"[::-1].encode(), "private-ipv4-endpoint"),
        ("moc.elpmaxe@ssap:resu//:sptth"[::-1].encode(), "url-userinfo"),
    ],
)
def test_release_scan_checks_printable_binary_metadata(metadata, expected_code, monkeypatch):
    padding = bytes(range(256)) * 32
    payload = padding + metadata + padding
    snapshots = {
        "index": {Path("asset.bin"): payload},
        "worktree": {Path("asset.bin"): payload},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    assert any(expected_code in item for item in check_sensitive_patterns())


def test_release_scan_checks_utf16_metadata_inside_binary(monkeypatch):
    text = "YEK_IPA_IANEPO"[::-1] + "=opaque_" + "Z" * 32
    padding = bytes(range(256)) * 32
    payload = padding + text.encode("utf-16-le") + padding
    snapshots = {
        "index": {Path("asset.bin"): payload},
        "worktree": {Path("asset.bin"): payload},
    }
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    assert any("configured-api-key" in item for item in check_sensitive_patterns())


def test_inline_mapping_reference_handling_is_language_aware():
    python_source = _runtime_text(
        "payload = {", "k", "ey: value for key, value in source.items()}"
    )
    javascript_source = _runtime_text("const payload = { to", "ken: configuredToken };")
    json_source = _runtime_text('{"to', 'ken":"opaque_F9k3Lm7Q2xW8v6N4p2Q7"}')

    assert not release_scan._contains_configured_credential(
        python_source, source_path=Path("probe.py")
    )
    assert not release_scan._contains_configured_credential(
        javascript_source, source_path=Path("probe.js")
    )
    assert release_scan._contains_configured_credential(
        json_source, source_path=Path("probe.json")
    )


@pytest.mark.parametrize(
    "payload",
    [
        ("sk" + "\\u002d" + "Z" * 32).encode(),
        ("SEMANTIC_SCHOLAR_API_KEY=" + "".join("\\u0041" for _ in range(24))).encode(),
        ("Authorization" + "\\u003a Basic " + "Q" * 24).encode(),
    ],
)
def test_release_scan_decodes_unicode_escapes_before_secret_matching(payload, monkeypatch):
    snapshots = {"index": {Path("public.txt"): payload}, "worktree": {Path("public.txt"): payload}}
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    assert any("blocked pattern" in item for item in check_sensitive_patterns())


@pytest.mark.parametrize(
    "payload",
    [
        ("sk" + "-" + "ABCD" + "\u200b" + "Z" * 28).encode(),
        ("OPENAI_API" + "\u200b" + "_KEY=" + "opaque_" + "A" * 40).encode(),
        ("Authorization: Bearer " + "opaque_" + "ABCD" + "\u2060" + "B" * 32).encode(),
        ("gh" + "p_" + "ABCD" + "\ufe0f" + "C" * 24).encode(),
    ],
)
def test_release_scan_compacts_default_ignorables_before_secret_matching(payload, monkeypatch):
    snapshots = {"index": {Path("public.txt"): payload}, "worktree": {Path("public.txt"): payload}}
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    assert any("blocked pattern" in item for item in check_sensitive_patterns())


def test_release_scan_repeats_security_transforms_for_combined_encoding(monkeypatch):
    payload = ("OPENAI_API_KEY%3" + "\u200b" + "A" + "opaque_" + "Z" * 40).encode()
    snapshots = {"index": {Path("public.txt"): payload}, "worktree": {Path("public.txt"): payload}}
    monkeypatch.setattr(release_scan, "_read_release_snapshots", lambda: snapshots)
    monkeypatch.setattr(release_scan, "_working_tree_matches_index", lambda: True)
    monkeypatch.setattr(release_scan, "_index_flags_are_safe", lambda: True)

    assert any("blocked pattern" in item for item in check_sensitive_patterns())


def test_release_scan_rejects_untrusted_or_unpinned_lockfile_entries(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    package = {
        "name": "ui",
        "version": "1.0.0",
        "dependencies": {},
        "devDependencies": {},
        "engines": {"node": ">=22.18.0"},
    }
    lock = {
        "name": "ui",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": package,
            "node_modules/example": {
                "version": "1.0.0",
                "resolved": "https://attacker.example/example.tgz",
            },
        },
    }
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = release_scan.check_lockfile_registry()

    assert any("non-official resolved package URL" in item for item in errors)
    assert any("missing a SHA-512 integrity pin" in item for item in errors)


def test_release_scan_rejects_official_tarball_for_a_different_package(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    package = {
        "name": "ui",
        "version": "1.0.0",
        "scripts": release_scan.EXPECTED_FRONTEND_SCRIPTS,
        "dependencies": {},
        "devDependencies": {},
        "engines": {"node": ">=22.18.0"},
    }
    lock = {
        "name": "ui",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {key: value for key, value in package.items() if key != "scripts"},
            "node_modules/@types/react": {
                "version": "19.2.18",
                "resolved": "https://registry.npmjs.org/picocolors/-/picocolors-1.1.1.tgz",
                "integrity": "sha512-" + base64.b64encode(b"A" * 64).decode("ascii"),
            },
        },
    }
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = release_scan.check_lockfile_registry()

    assert any("resolved package name/version" in item for item in errors)


def test_release_scan_rejects_noop_or_redirected_frontend_scripts(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    package = {
        "name": "ui",
        "version": "1.0.0",
        "scripts": {**release_scan.EXPECTED_FRONTEND_SCRIPTS, "test": "true"},
        "dependencies": {},
        "devDependencies": {},
        "engines": {"node": ">=22.18.0"},
    }
    lock = {
        "name": "ui",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {"": {key: value for key, value in package.items() if key != "scripts"}},
    }
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = release_scan.check_lockfile_registry()

    assert any("audited executable gates" in item for item in errors)


@pytest.mark.parametrize(
    "alternate_lock",
    ["npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb"],
)
def test_release_scan_rejects_alternative_frontend_lockfiles(tmp_path, monkeypatch, alternate_lock):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    package = {
        "name": "ui",
        "version": "1.0.0",
        "scripts": release_scan.EXPECTED_FRONTEND_SCRIPTS,
        "dependencies": {},
        "devDependencies": {},
        "engines": {"node": ">=22.18.0"},
    }
    lock = {
        "name": "ui",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {"": {key: value for key, value in package.items() if key != "scripts"}},
    }
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (frontend / alternate_lock).write_bytes(b"alternate")
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)

    errors = release_scan.check_lockfile_registry()

    assert any(alternate_lock in item and "override" in item for item in errors)


@pytest.mark.parametrize("value", ["sha512-A=", "sha512-AAAA", "sha256-" + "A" * 88])
def test_release_scan_rejects_malformed_or_short_integrity_pins(value):
    assert release_scan._valid_sha512_integrity(value) is False


def test_release_scan_accepts_exact_512_bit_integrity_pin():
    value = "sha512-" + base64.b64encode(b"A" * 64).decode("ascii")

    assert release_scan._valid_sha512_integrity(value) is True


def test_release_scan_ci_validation_ignores_comment_decoys_and_rejects_unsafe_yaml():
    workflow = """
permissions: write-all
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - name: Untrusted
        uses: attacker/action@latest
  windows-smoke:
    runs-on: windows-latest
    steps: []
# actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
# actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
# actions/setup-node@820762786026740c76f36085b0efc47a31fe5020
# persist-credentials: false
# node-version: "22.18.0"
# pip>=26.2.1 setuptools>=84.0.0
"""

    errors = release_scan._validate_ci_workflow(workflow)

    assert any("permissions" in item for item in errors)
    assert any("official action allowlist" in item for item in errors)


@pytest.mark.parametrize(
    ("input_name", "input_value"),
    [
        ("persist-credentials", "false"),
        ("python-version", '"3.11"'),
        ("node-version", '"22.18.0"'),
    ],
)
def test_release_scan_ci_requires_action_inputs_under_with(input_name, input_value):
    workflow = _read(".github/workflows/ci.yml")
    original = f"        with:\n          {input_name}: {input_value}"
    mutated = f"        env:\n          {input_name}: {input_value}"
    assert original in workflow

    errors = release_scan._validate_ci_workflow(workflow.replace(original, mutated, 1))

    assert any("with mapping" in item for item in errors)


def test_release_scan_ci_rejects_quoted_job_permissions_key():
    workflow = _read(".github/workflows/ci.yml")
    mutated = workflow.replace(
        "    runs-on: ubuntu-latest",
        '    "permissions": write-all\n    runs-on: ubuntu-latest',
        1,
    )

    errors = release_scan._validate_ci_workflow(mutated)

    assert any("privilege-bearing keys" in item for item in errors)


@pytest.mark.parametrize(
    ("original", "mutated"),
    [
        (
            "          persist-credentials: false",
            "          persist-credentials: false\n          repository: attacker/example",
        ),
        (
            "        run: python scripts/release_scan.py",
            "        continue-on-error: true\n        run: python scripts/release_scan.py",
        ),
        (
            "        run: python scripts/release_scan.py",
            "        if: false\n        run: python scripts/release_scan.py",
        ),
        (
            "        run: python scripts/release_scan.py",
            '        shell: "cmd /c echo {0}"\n        run: python scripts/release_scan.py',
        ),
        (
            "        run: python scripts/release_scan.py",
            "        run: |\n          cat <<'EOF'\n          python scripts/release_scan.py\n          EOF",
        ),
    ],
)
def test_release_scan_ci_rejects_step_execution_bypasses(original, mutated):
    from scripts.release_scan import _validate_ci_workflow

    workflow = (Path.cwd() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert original in workflow

    errors = _validate_ci_workflow(workflow.replace(original, mutated, 1))

    assert any("exactly match the audited job structure" in item for item in errors)


def test_release_scan_ci_rejects_unaudited_root_defaults():
    from scripts.release_scan import _validate_ci_workflow

    workflow = (Path.cwd() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    mutated = workflow.replace(
        "permissions:\n", "defaults:\n  run:\n    shell: false\n\npermissions:\n", 1
    )

    errors = _validate_ci_workflow(mutated)

    assert any("audited root fields" in item for item in errors)


@pytest.mark.parametrize("alias", ["true", "yes", "TRUE", "True", "On", "ON"])
def test_release_scan_ci_requires_exact_lowercase_on_key(alias):
    from scripts.release_scan import _validate_ci_workflow

    workflow = (Path.cwd() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    mutated = workflow.replace("on:", f"{alias}:", 1)

    errors = _validate_ci_workflow(mutated)

    assert any("audited root fields" in item for item in errors)


@pytest.mark.parametrize(
    "mutated",
    [
        "permissions:\n  contents: write\npermissions:\n  contents: read\n",
        (
            "jobs:\n  verify:\n    runs-on: ubuntu-latest\n    timeout-minutes: 20\n"
            "    steps:\n      - uses: attacker/action@latest\n"
            "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        ),
    ],
)
def test_release_scan_ci_rejects_duplicate_yaml_keys(mutated):
    from scripts.release_scan import _validate_ci_workflow

    errors = _validate_ci_workflow("name: CI\n" + mutated)

    assert errors == ["CI workflow must be valid safe YAML"]


def test_release_scan_rejects_additional_tracked_workflow(monkeypatch):
    import scripts.release_scan as release_scan

    monkeypatch.setattr(
        release_scan,
        "_tracked_paths",
        lambda: [Path(".github/workflows/ci.yml"), Path(".github/workflows/extra.yaml")],
    )

    errors = release_scan.check_ci_contract()

    assert any("inventory must contain exactly ci.yml" in item for item in errors)


def test_release_scan_rejects_pytest_addopts_and_nested_lint_config(tmp_path, monkeypatch):
    pyproject = """
[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F"]
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--collect-only"
"""
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    monkeypatch.setattr(release_scan, "ROOT", tmp_path)
    monkeypatch.setattr(
        release_scan,
        "_tracked_paths",
        lambda: (Path("pyproject.toml"), Path("tests/.pytest.ini")),
    )

    errors = release_scan.check_tool_policy()

    assert any("audited pytest policy" in item for item in errors)
    assert any("override configuration" in item for item in errors)


def test_query_response_matches_documented_session_contract():
    response_fields = set(QueryResponse.model_fields)
    assert SESSION_REQUIRED_FIELDS <= response_fields


def test_docs_include_session_artifact_contract_fields():
    combined = "\n".join(
        [
            _read("README.md"),
            _read("AGENTS.md"),
            _read("CLAUDE.md"),
            _read(".codex/skills/weiping-council/SKILL.md"),
        ]
    )
    for field in SESSION_REQUIRED_FIELDS:
        assert field in combined
