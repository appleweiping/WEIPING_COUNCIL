"""Public release guard for WEIPING_COUNCIL."""

from __future__ import annotations

import ast
import base64
import binascii
import hashlib
import heapq
import io
import json
import re
import subprocess
import sys
import tomllib
import tokenize
import unicodedata
import yaml
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "weiping_council.egg-info",
}
TEXT_SUFFIXES = {
    "",
    ".cmd",
    ".css",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
FORBIDDEN_TRACKED_PATHS = {
    Path("backend/memory/tracker.py"),
    Path("data/model_performance.json"),
}
SECRET_PATTERNS = [
    ("secret-api-key", re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{10,}", re.IGNORECASE)),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.I)),
    (
        "authorization-basic",
        re.compile(
            r"\bAuthorization\b(?:\\+)?['\"]?\s*[:=]\s*(?:\\+)?['\"]?Basic\s+"
            r"[A-Za-z0-9+/]{8,}={0,2}(?![A-Za-z0-9+/=])",
            re.I,
        ),
    ),
    (
        "authorization-bearer",
        re.compile(
            r"\bAuthorization\b(?:\\+)?['\"]?\s*[:=]\s*(?:\\+)?['\"]?Bearer\s+"
            r"[A-Za-z0-9._~+/-]{20,}(?![A-Za-z0-9._~+/-])",
            re.I,
        ),
    ),
    (
        "known-provider-token",
        re.compile(
            r"(?<![A-Za-z0-9])(?:"
            r"glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
            r"hf_[A-Za-z0-9]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|"
            r"npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,}|"
            r"AIza[0-9A-Za-z_-]{30,}|hvs\.[A-Za-z0-9_-]{20,}"
            r")(?![A-Za-z0-9])",
            re.I,
        ),
    ),
    (
        "jwt-token",
        re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
    ("aws-access-key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("private-key", re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")),
    (
        "private-ipv4-endpoint",
        re.compile(
            r"(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|169\.254(?:\.\d{1,3}){2}|"
            r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?::\d{1,5})?(?!\d)"
        ),
    ),
    (
        "private-ipv6-endpoint",
        re.compile(r"(?:\[)?f[cd][0-9a-f]{2}:[0-9a-f:]+(?:\])?(?::\d{1,5})?", re.I),
    ),
    (
        "link-local-ipv6-endpoint",
        re.compile(r"(?:\[)?fe[89ab][0-9a-f]:[0-9a-f:]+(?:\])?(?::\d{1,5})?", re.I),
    ),
    (
        "private-dns-endpoint",
        re.compile(
            r"(?<![a-z0-9.-])(?:[a-z0-9-]+\.)+(?:internal|local)"
            r"(?::\d{1,5})?(?![a-z0-9.-])",
            re.I,
        ),
    ),
    (
        "url-userinfo",
        re.compile(
            r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/@?#]+(?::[^\s/@?#]*)?@",
            re.I,
        ),
    ),
    ("retired-" + "-".join(("agent", "hub")), re.compile(r"agent[-]hub", re.IGNORECASE)),
    ("retired-" + "-".join(("memory", "index")), re.compile(r"memory[\\/]INDEX", re.IGNORECASE)),
    (
        "operator-windows-path",
        re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", re.IGNORECASE),
    ),
    (
        "operator-unc-path",
        re.compile(r"\x5c\x5c[A-Z0-9][A-Z0-9._-]{0,62}[\\/][A-Z0-9][^\s]+", re.I),
    ),
    (
        "operator-posix-path",
        re.compile(
            r"(?<![A-Za-z0-9])/(?:home|Users)/[A-Z0-9._-]+(?:/|$)"
            r"|(?<![A-Za-z0-9])/(?:root|tmp/[A-Z0-9._-]+)(?:/|$)"
            r"|(?<![A-Za-z0-9])/mnt/[A-Z]/Users/[A-Z0-9._-]+(?:/|$)",
            re.I,
        ),
    ),
]
STATIC_RECONSTRUCTED_SECRET_CODES = {
    "aws-access-key",
    "github-fine-grained-token",
    "github-token",
    "jwt-token",
    "known-provider-token",
    "private-key",
    "secret-api-key",
}
BINARY_PATTERN_MARKERS = {
    "authorization-basic": (b"authorization",),
    "authorization-bearer": (b"authorization",),
    "aws-access-key": (b"akia",),
    "github-fine-grained-token": (b"github_pat_",),
    "github-token": (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_"),
    "jwt-token": (b"eyj",),
    "known-provider-token": (
        b"glpat-",
        b"xox",
        b"hf_",
        b"sk_live_",
        b"sk_test_",
        b"npm_",
        b"pypi-",
        b"aiza",
        b"hvs.",
    ),
    "link-local-ipv6-endpoint": (b"fe8", b"fe9", b"fea", b"feb"),
    "operator-posix-path": (
        b"/home/",
        b"/users/",
        b"".join((b"/", b"root")),
        b"/tmp/",
        b"/mnt/",
    ),
    "operator-unc-path": (b"\\\\",),
    "operator-windows-path": (b":\\", b":/"),
    "private-key": (b"begin ",),
    "private-dns-endpoint": (b".internal", b".local"),
    "private-ipv4-endpoint": (b"10.", b"192.168", b"169.254", b"172."),
    "private-ipv6-endpoint": (b"fc", b"fd"),
    "retired-" + "-".join(("agent", "hub")): (b"".join((b"agent", b"-hub")),),
    "retired-" + "-".join(("memory", "index")): (
        b"".join((b"memory", b"/", b"index")),
        b"".join((b"memory", b"\\", b"index")),
    ),
    "secret-api-key": (b"sk-",),
    "url-userinfo": (b"://", b"@"),
}
BINARY_CONFIG_MARKERS = (
    b"api",
    b"auth",
    b"cookie",
    b"credential",
    b"dsn",
    b"key",
    b"pass",
    b"secret",
    b"token",
)
BINARY_ASCII_RUN = re.compile(rb"[\t\r\n\x20-\x7e]{8,}")
BINARY_UTF16_LE_RUN = re.compile(rb"(?:[\t\r\n\x20-\x7e]\x00){8,}")
BINARY_UTF16_BE_RUN = re.compile(rb"(?:\x00[\t\r\n\x20-\x7e]){8,}")
JAVASCRIPT_SUFFIXES = {".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
JAVASCRIPT_DECLARATION_START = re.compile(
    r"\b(?P<kind>const|let|var)[ \t]+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:[ \t]*:[ \t]*[A-Za-z_$][A-Za-z0-9_$<>,.\[\] |&?]{0,511})?"
    r"[ \t]*=[ \t]*"
)
JAVASCRIPT_DESTRUCTURING_DECLARATION_START = re.compile(
    r"\b(?P<kind>const|let|var)[ \t]+"
    r"(?P<pattern>\[[^\]\r\n]{1,4096}\]|\{[^{}\r\n]{1,4096}\})"
    r"[ \t]*=[ \t]*"
)
JAVASCRIPT_UNINITIALIZED_DECLARATION = re.compile(
    r"\b(?P<kind>let|var)[ \t]+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:[ \t]*:[ \t]*[A-Za-z_$][A-Za-z0-9_$<>,.\[\] |&?]{0,511})?"
    r"(?![ \t]*=)(?=[ \t]*(?:[;,\r\n)]|$))"
)
JAVASCRIPT_ASSIGNMENT_START = re.compile(
    r"(?<![A-Za-z0-9_$.)\]])(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)[ \t]*=(?!=|>)"
)
JAVASCRIPT_UPDATED_BINDING = re.compile(
    r"(?:(?P<prefix>\+\+|--)[ \t]*(?P<prefix_name>[A-Za-z_$][A-Za-z0-9_$]*)|"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)[ \t]*(?:\+\+|--|[+\-*/%&|^]=))"
)
JAVASCRIPT_FUNCTION_PARAMETERS = re.compile(
    r"\b(?:async[ \t]+)?function\b[^()\r\n]*\((?P<parameters>[^()\r\n]{0,2048})\)"
    r"|\((?P<arrow_parameters>[^()\r\n]{0,2048})\)[ \t]*=>"
)
JAVASCRIPT_METHOD_PARAMETERS = re.compile(
    r"(?m)(?<![A-Za-z0-9_$])(?:async[ \t]+)?"
    r"(?P<method>[A-Za-z_$][A-Za-z0-9_$]*)[ \t]*"
    r"\((?P<parameters>[^()\r\n]{0,2048})\)[ \t]*"
    r"(?:[ \t]*:[ \t]*[A-Za-z_$][A-Za-z0-9_$<>,.\[\] |&?]{0,511})?[ \t]*\{"
)
JAVASCRIPT_SINGLE_ARROW_PARAMETER = re.compile(
    r"(?<![A-Za-z0-9_$])(?P<parameter>[A-Za-z_$][A-Za-z0-9_$]*)[ \t]*=>"
)
JAVASCRIPT_CONDITIONAL_BLOCK = re.compile(
    r"(?<![A-Za-z0-9_$])(?:"
    r"(?:if|for|while|switch|catch|with)[ \t]*\([^{}]{0,65536}\)"
    r"|else(?:[ \t]+if[ \t]*\([^{}]{0,65536}\))?"
    r"|try|finally|do"
    r")[ \t\r\n]*\{"
)
JAVASCRIPT_PARENTHESIZED_CONTROL = re.compile(
    r"(?<![A-Za-z0-9_$.])(?P<control>if|for|while|with)[ \t\r\n]*\("
)
JAVASCRIPT_BARE_CONTROL = re.compile(r"(?<![A-Za-z0-9_$.])(?P<control>else|do)\b")
JAVASCRIPT_MAPPING_REFERENCE = re.compile(
    r"(?P<name_quote>['\"]?)(?P<name>[A-Za-z_$][A-Za-z0-9_$.-]{1,127})"
    r"(?P=name_quote)[ \t]*:[ \t]*(?P<reference>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
JAVASCRIPT_COMPUTED_MAPPING_REFERENCE = re.compile(
    r"\[[ \t]*(?P<key_quote>['\"])(?P<name>[A-Za-z_$][A-Za-z0-9_$.-]{1,127})"
    r"(?P=key_quote)[ \t]*\][ \t]*:[ \t]*(?P<reference>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
JAVASCRIPT_COMPUTED_STATIC_KEY_REFERENCE = re.compile(
    r"\[[ \t]*(?P<name_expression>[^\]\r\n]{1,4096})[ \t]*\]"
    r"[ \t]*:[ \t]*(?P<reference>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
JAVASCRIPT_BRACKET_REFERENCE = re.compile(
    r"(?i)(?:process\.env|headers?|config|settings)[ \t]*\[[ \t]*"
    r"(?P<name_quote>['\"])(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
    r"(?P=name_quote)[ \t]*\][ \t]*=[ \t]*"
    r"(?P<reference>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
JAVASCRIPT_NAMED_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_$.-])(?P<name>[A-Za-z_$][A-Za-z0-9_$.-]{1,127})"
    r"[ \t]*=[ \t]*(?P<reference>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
JAVASCRIPT_SETTER_REFERENCE = re.compile(
    r"(?i)(?<![A-Za-z0-9_$.-])"
    r"(?:headers?|config|configuration|env|options|settings)"
    r"[ \t]*\.[ \t]*(?:append|set)[ \t]*\([ \t]*"
    r"(?P<key_quote>['\"])(?P<name>[A-Za-z_$][A-Za-z0-9_$.-]{1,127})(?P=key_quote)"
    r"[ \t]*,[ \t]*(?P<reference>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
JAVASCRIPT_SETTER_STATIC_KEY_REFERENCE = re.compile(
    r"(?i)(?<![A-Za-z0-9_$.-])"
    r"(?:headers?|config|configuration|env|options|settings)"
    r"[ \t]*\.[ \t]*(?:append|set)[ \t]*\([ \t]*"
    r"(?P<name_expression>[^,\r\n]{1,4096})[ \t]*,[ \t]*"
    r"(?P<reference>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
ALLOWED_ACTIONS = Counter(
    {
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1": 2,
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97": 2,
        "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020": 1,
    }
)
PRIVATE_TRACKED_NAMES = {
    ".envrc",
    ".git-credentials",
    ".htpasswd",
    ".netrc",
    ".pgpass",
    ".vault-token",
    "_netrc",
    "auth.json",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_ecdsa",
    "id_rsa",
    "pip.conf",
    "secrets.json",
}
FORBIDDEN_FRONTEND_LOCKFILES = {
    "bun.lock",
    "bun.lockb",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
PRIVATE_TRACKED_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
PRIVATE_TRACKED_PATHS = {
    ".config/gh/hosts.yml",
    ".docker/config.json",
    ".kube/config",
    ".ssh/config",
}
SESSION_REQUIRED_FIELDS = {
    "id",
    "query",
    "protocol",
    "created_at",
    "stages",
    "final_answer",
    "confidence",
    "dissent",
    "audit_trail",
    "routing",
    "metrics",
    "provider_health",
    "model_call_traces",
    "degraded",
    "warnings",
}
EXPECTED_FRONTEND_SCRIPTS = {
    "build": "vite build",
    "dev": "vite",
    "preview": "vite preview",
    "test": "vitest run",
}
OVERRIDE_CONFIG_NAMES = {
    ".pytest.ini",
    ".pytest.toml",
    ".ruff.toml",
    "pytest.ini",
    "pytest.toml",
    "ruff.toml",
    "setup.cfg",
    "tox.ini",
}
UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
HEX_ESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})")
OCTAL_ESCAPE = re.compile(r"\\([0-7]{1,3})")
CONFIGURED_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_])(?P<name>_*[A-Za-z][A-Za-z0-9_.-]{1,127})"
    r"(?P<key_quote>(?:\\+)?['\"])?\s*[:=]"
    r"(?P<gap>[ \t]*|[ \t]*\r?\n[ \t]*"
    r"(?!(?:\\+)?['\"][A-Za-z_][A-Za-z0-9_.-]*(?:\\+)?['\"][ \t]*[:=])"
    r"(?=(?:\\+)?['\"])|"
    r"[ \t]*\r?\n[ \t]+(?![A-Za-z_][A-Za-z0-9_.-]*[ \t]*[:=])"
    r"(?=[A-Za-z0-9_./:@+-])|"
    r"[ \t]*[|>](?:[1-9][+-]?|[+-][1-9]?)?[ \t]*\r?\n[ \t]+)"
    r"(?:(?P<triple_quote>'''|\"\"\")(?P<triple_value>"
    r"(?:(?!(?P=triple_quote))[^\ufdd0]){4,}?)(?P=triple_quote)|"
    r"(?:\\+)?(?P<value_quote>['\"])(?P<quoted_value>"
    r"(?:\\[^\ufdd0]|(?!(?P=value_quote))[^\ufdd0]){4,}?)(?P=value_quote)|"
    r"(?P<unquoted_value>[^\s#'\"<>{}$\ufdd0]{4,}))",
    re.I,
)
AUTHORIZATION_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9_])authorization(?:\\+)?['\"]?\s*[:=]\s*"
    r"(?:\\+)?['\"]?(?:basic|bearer|digest|token|apikey)\s+"
    r"(?:(?P<credential_quote>['\"])(?P<quoted_credential>"
    r"(?:\\.|[^'\"\r\n]){4,}?)(?P=credential_quote)|"
    r"(?P<credential>[^\s\r\n'\"]{4,}))",
    re.I,
)
INLINE_MAPPING_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)(?=(?<!\$)(?:^|[,{][ \t]*)(?P<name_quote>['\"]?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)[ \t]*:[ \t]*"
    r"(?P<value>(?P<value_quote>['\"])(?:\\.|(?!(?P=value_quote)).){4,}?"
    r"(?P=value_quote)|\$\{[^}\r\n]+\}|[^,}\]\r\n]{4,}))"
)
STRUCTURED_CREDENTIAL_ASSIGNMENTS = (
    re.compile(
        r"(?im)\$env:(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})[ \t]*=[ \t]*"
        r"(?P<value>[^\r\n;#]{4,})"
    ),
    re.compile(
        r"(?im)\$\{env:(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})\}[ \t]*=[ \t]*"
        r"(?P<value>[^\r\n;#]{4,})"
    ),
    re.compile(
        r"(?im)\$env:(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})[ \t]*=[ \t]*"
        r"(?P<value>@(?P<here_quote>['\"])[ \t]*\r?\n[\s\S]*?\r?\n"
        r"(?P=here_quote)@)"
    ),
    re.compile(
        r"(?im)\$\{env:(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})\}[ \t]*=[ \t]*"
        r"(?P<value>@(?P<here_quote>['\"])[ \t]*\r?\n[\s\S]*?\r?\n"
        r"(?P=here_quote)@)"
    ),
    re.compile(
        r"(?im)^[ \t]*ENV[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})[ \t]+"
        r"(?P<value>[^\r\n]{4,})"
    ),
    re.compile(
        r"(?im)^[ \t]*export[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
        r"[ \t]*=[ \t]*(?P<value>[^\r\n;#]{4,})"
    ),
    INLINE_MAPPING_CREDENTIAL_ASSIGNMENT,
    re.compile(
        r"(?i)(?:process\.env|headers?|config|settings|os\.environ)[ \t]*\[[ \t]*"
        r"(?P<name_quote>['\"])(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
        r"(?P=name_quote)[ \t]*\][ \t]*=[ \t]*(?P<value_quote>['\"`])"
        r"(?P<value>(?:\\.|(?!(?P=value_quote)).){4,}?)(?P=value_quote)"
    ),
    re.compile(
        r"(?i)\b(?:os\.)?Setenv[ \t]*\([ \t]*(?P<name_quote>['\"`])"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)[ \t]*,[ \t]*"
        r"(?P<value_quote>['\"`])(?P<value>(?:\\.|(?!(?P=value_quote)).){4,}?)"
        r"(?P=value_quote)"
    ),
    re.compile(
        r"(?im)^[ \t]*-[ \t]*(?:['\"]name['\"]|name):[ \t]*"
        r"(?P<name_quote>['\"]?)"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)[ \t]*\r?\n"
        r"(?:(?:[ \t]*+(?:#[^\r\n]*)?\r?\n)|"
        r"(?:[ \t]++(?!-[ \t]|['\"]?(?:name|value)['\"]?[ \t]*:)"
        r"[^\r\n]++\r?\n)){0,12}"
        r"[ \t]+(?:['\"]value['\"]|value):[ \t]*(?P<value>[^\r\n]{4,})"
    ),
    re.compile(
        r"(?im)^[ \t]*-[ \t]*(?:['\"]value['\"]|value):[ \t]*"
        r"(?P<value>[^\r\n]{4,})\r?\n"
        r"(?:(?:[ \t]*+(?:#[^\r\n]*)?\r?\n)|"
        r"(?:[ \t]++(?!-[ \t]|['\"]?(?:name|value)['\"]?[ \t]*:)"
        r"[^\r\n]++\r?\n)){0,12}"
        r"[ \t]+(?:['\"]name['\"]|name):[ \t]*(?P<name_quote>['\"]?)"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)"
    ),
    re.compile(
        r"(?im)^[ \t]*-[ \t]*\{[^}\r\n]*\b(?:['\"]name['\"]|name)[ \t]*:[ \t]*"
        r"(?P<name_quote>['\"]?)(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
        r"(?P=name_quote)[^}\r\n]*,[^}\r\n]*\b(?:['\"]value['\"]|value)"
        r"[ \t]*:[ \t]*(?P<value>\$\{[^}\r\n]+\}|[^,}\r\n]{4,})[^}\r\n]*\}"
    ),
    re.compile(
        r"(?im)^[ \t]*-[ \t]*\{[^}\r\n]*\b(?:['\"]value['\"]|value)[ \t]*:[ \t]*"
        r"(?P<value>\$\{[^}\r\n]+\}|[^,}\r\n]{4,}),[^}\r\n]*"
        r"\b(?:['\"]name['\"]|name)"
        r"[ \t]*:[ \t]*(?P<name_quote>['\"]?)(?P<name>"
        r"[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)[^}\r\n]*\}"
    ),
    re.compile(
        r"(?i)<(?:add|environmentVariable)\b[^>]*\b(?:name|key)[ \t]*=[ \t]*"
        r"(?P<name_quote>['\"])"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)[^>]*"
        r"\bvalue[ \t]*=[ \t]*(?P<value_quote>['\"])(?P<value>.{4,}?)"
        r"(?P=value_quote)"
    ),
    re.compile(
        r"(?i)<(?:add|environmentVariable)\b[^>]*\bvalue[ \t]*=[ \t]*"
        r"(?P<value_quote>['\"])"
        r"(?P<value>.{4,}?)(?P=value_quote)[^>]*\b(?:name|key)[ \t]*=[ \t]*"
        r"(?P<name_quote>['\"])(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
        r"(?P=name_quote)"
    ),
    re.compile(
        r"(?is)\bSet-Item[\s`]+(?:-(?:Literal)?Path[\s`]+)?(?P<name_quote>['\"]?)"
        r"Env:[\\/]?(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)[\s`]+"
        r"(?:-Value[\s`]+)?(?P<value>(?P<value_quote>['\"])"
        r"(?:`.|(?!(?P=value_quote)).){4,}?(?P=value_quote)|[^\s;#]{4,})"
    ),
    re.compile(
        r"(?is)\bSet-Item[\s`]+-Value[\s`]+(?P<value>(?P<value_quote>['\"])"
        r"(?:`.|(?!(?P=value_quote)).){4,}?(?P=value_quote)|[^\s;#]{4,})[\s`]+"
        r"-(?:Literal)?Path[\s`]+(?P<name_quote>['\"]?)Env:[\\/]?"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})(?P=name_quote)"
    ),
    re.compile(
        r"(?is)\[(?:System\.)?Environment\]::SetEnvironmentVariable[\s`]*\([\s`]*"
        r"(?P<name_quote>['\"])(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
        r"(?P=name_quote)[\s`]*,[\s`]*(?P<value_quote>['\"])"
        r"(?P<value>(?:`.|(?!(?P=value_quote)).){4,}?)(?P=value_quote)"
    ),
    re.compile(
        r"(?is)\[(?:System\.)?Environment\]::SetEnvironmentVariable[\s`]*\([\s`]*"
        r"(?P<name_quote>['\"])(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
        r"(?P=name_quote)[\s`]*,[\s`]*(?P<value>@(?P<here_quote>['\"])"
        r"[ \t]*\r?\n[\s\S]*?\r?\n(?P=here_quote)@)"
    ),
    re.compile(
        r"(?is)\[(?:System\.)?Environment\]::SetEnvironmentVariable[\s`]*\([\s`]*"
        r"(?P<name_quote>['\"])(?P<name>[A-Za-z_][A-Za-z0-9_.-]{1,127})"
        r"(?P=name_quote)[\s`]*,[\s`]*(?P<value>(?P<piece_quote>['\"])"
        r"(?:`.|(?!(?P=piece_quote)).)+?(?P=piece_quote)(?:[\s`]*\+[\s`]*"
        r"(?P<next_quote>['\"])(?:`.|(?!(?P=next_quote)).)+?"
        r"(?P=next_quote))+)"
    ),
)


class _UniqueSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys at every mapping depth."""


_UniqueSafeLoader.yaml_implicit_resolvers = {
    key: list(resolvers) for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _resolver_key, _resolvers in _UniqueSafeLoader.yaml_implicit_resolvers.items():
    _UniqueSafeLoader.yaml_implicit_resolvers[_resolver_key] = [
        (tag, pattern) for tag, pattern in _resolvers if tag != "tag:yaml.org,2002:bool"
    ]
_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.I),
    list("tTfF"),
)


def _construct_unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _json(relative: str) -> dict:
    return json.loads(_read(relative))


def _app_version() -> str:
    tree = ast.parse(_read("backend/config.py"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        has_target = any(
            isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets
        )
        if has_target and isinstance(node.value, ast.Constant):
            return str(node.value.value)
    raise AssertionError("APP_VERSION not found in backend/config.py")


def _tracked_paths() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("git ls-files failed")
    paths = []
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        name = raw_name.decode("utf-8", errors="strict")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or any(ord(char) < 32 for char in name):
            raise RuntimeError("git returned an unsafe tracked path")
        paths.append(relative)
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


def _read_tracked_snapshot() -> dict[Path, bytes]:
    snapshot = {}
    for relative in _tracked_paths():
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"tracked path is not a regular file: {relative.as_posix()}")
        snapshot[relative] = path.read_bytes()
    return snapshot


def _read_index_snapshot() -> dict[Path, bytes]:
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--stage", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listing.returncode != 0:
        raise RuntimeError("git ls-files --stage failed")
    entries: list[tuple[Path, bytes]] = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            _mode, object_id, stage = metadata.split()
            relative = Path(raw_path.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise RuntimeError("invalid staged index entry") from exc
        if stage != b"0":
            raise RuntimeError("unmerged staged index entry")
        entries.append((relative, object_id))

    batch = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        input=b"".join(object_id + b"\n" for _, object_id in entries),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if batch.returncode != 0:
        raise RuntimeError("git cat-file --batch failed")
    snapshot: dict[Path, bytes] = {}
    cursor = 0
    for relative, expected_id in entries:
        line_end = batch.stdout.find(b"\n", cursor)
        if line_end < 0:
            raise RuntimeError("truncated git cat-file header")
        header = batch.stdout[cursor:line_end].split()
        if len(header) != 3 or header[0] != expected_id or header[1] != b"blob":
            raise RuntimeError("unexpected staged object type")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise RuntimeError("invalid staged object size") from exc
        start = line_end + 1
        end = start + size
        if end >= len(batch.stdout) or batch.stdout[end : end + 1] != b"\n":
            raise RuntimeError("truncated staged object")
        snapshot[relative] = batch.stdout[start:end]
        cursor = end + 1
    if cursor != len(batch.stdout):
        raise RuntimeError("unexpected trailing staged object data")
    return snapshot


def _read_release_snapshots() -> dict[str, dict[Path, bytes]]:
    return {
        "index": _read_index_snapshot(),
        "worktree": _read_tracked_snapshot(),
    }


def _working_tree_matches_index() -> bool:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", "--no-ext-diff", "--"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("git diff failed")
    return result.returncode == 0


def _index_flags_are_safe() -> bool:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-v", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("git ls-files flags failed")
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        tag = chr(entry[0])
        if tag == "S" or tag.islower():
            return False
    return True


def _scan_views(raw: bytes) -> tuple[str, ...]:
    views = []
    encodings = ["utf-8-sig", "latin-1"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    elif raw.count(b"\0") >= max(2, len(raw) // 10):
        encodings.extend(("utf-16-le", "utf-16-be"))
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        decoded = unicodedata.normalize("NFKC", text)
        views.extend(_unicode_escape_views(decoded))
        for _ in range(8):
            candidate = unicodedata.normalize("NFKC", unquote(decoded))
            if candidate == decoded:
                break
            decoded = candidate
        views.extend(_unicode_escape_views(decoded))
        if _is_probably_text(raw):
            views.append(_fixed_point_security_view(text))
    unique = list(dict.fromkeys(views))
    return tuple(dict.fromkeys(unique))


def _binary_metadata_views(raw: bytes) -> tuple[str, ...]:
    """Extract bounded text metadata without feeding random bytes to semantic regexes."""
    pieces = [match.group().decode("ascii") for match in BINARY_ASCII_RUN.finditer(raw)]
    pieces.extend(
        match.group().decode("utf-16-le") for match in BINARY_UTF16_LE_RUN.finditer(raw)
    )
    pieces.extend(
        match.group().decode("utf-16-be") for match in BINARY_UTF16_BE_RUN.finditer(raw)
    )
    if not pieces:
        return ()
    text = "\n".join(dict.fromkeys(pieces))
    views = [text]
    if "%" in text or "\\" in text:
        views.extend(_scan_views(text.encode("utf-8")))
    return tuple(dict.fromkeys(views))


def _binary_pattern_candidates(views: tuple[str, ...]) -> frozenset[str]:
    """Prefilter extracted metadata before running the full signature set."""
    lowered = "\n".join(views).casefold().encode("utf-8")
    return frozenset(
        code
        for code, markers in BINARY_PATTERN_MARKERS.items()
        if any(marker in lowered for marker in markers)
    )


def _binary_may_contain_configured_credential(views: tuple[str, ...]) -> bool:
    lowered = "\n".join(views).casefold().encode("utf-8")
    return any(marker in lowered for marker in BINARY_CONFIG_MARKERS)


def _configured_credential_views(
    raw: bytes, source_path: Path, all_views: tuple[str, ...]
) -> tuple[tuple[str, Path | None], ...]:
    """Keep Python syntax parseable while decoding strings/comments as untrusted data."""
    suffix = source_path.suffix.casefold()
    if suffix in JAVASCRIPT_SUFFIXES:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        text = unicodedata.normalize("NFKC", text)
        views = [(view, source_path) for view in all_views]
        views.extend((view, None) for view in _javascript_static_configured_views(text))
        return tuple(dict.fromkeys(views))
    if suffix != ".py":
        return tuple((view, source_path) for view in all_views)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    text = unicodedata.normalize("NFKC", text)
    views: list[tuple[str, Path | None]] = []
    views.extend((view, None) for view in _python_ast_configured_views(text))
    untrusted_tokens: list[str] = []
    masked = list(text)
    line_offsets = [0]
    line_offsets.extend(match.end() for match in re.finditer(r"\n", text))
    tokenized = False
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type not in {tokenize.STRING, tokenize.COMMENT}:
                continue
            tokenized = True
            untrusted_tokens.append(token.string)
            start = line_offsets[token.start[0] - 1] + token.start[1]
            end = line_offsets[token.end[0] - 1] + token.end[1]
            for index in range(start, min(end, len(masked))):
                if masked[index] not in {"\r", "\n"}:
                    masked[index] = " "
            if token.type == tokenize.STRING and start + 1 < min(end, len(masked)):
                masked[start] = '"'
                masked[start + 1] = '"'
    except (IndentationError, SyntaxError, tokenize.TokenError):
        pass
    try:
        ast.parse(text)
    except (SyntaxError, TypeError, ValueError):
        views.insert(0, ("".join(masked) if tokenized else text, source_path))
    for untrusted_token in dict.fromkeys(untrusted_tokens):
        views.extend((view, None) for view in _scan_views(untrusted_token.encode("utf-8")))
    return tuple(dict.fromkeys(views))


def _unicode_escape_views(text: str) -> tuple[str, ...]:
    views = [text]
    decoded = text
    for _ in range(4):
        candidate = UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), decoded)
        candidate = HEX_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), candidate)
        candidate = OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), candidate)
        if candidate == decoded:
            break
        decoded = unicodedata.normalize("NFKC", candidate)
        views.append(decoded)
    return tuple(views)


def _fixed_point_security_view(text: str) -> str:
    """Compose bounded decoders until transform order can no longer hide a match."""
    decoded = text
    for _ in range(12):
        candidate = UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), decoded)
        candidate = HEX_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), candidate)
        candidate = OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), candidate)
        candidate = unicodedata.normalize("NFKC", candidate)
        candidate = re.sub(r"\\\r?\n[ \t]*", "", candidate)
        candidate = re.sub(r"\\(['\"])", r"\1", candidate)
        candidate = "".join(
            character
            for character in candidate
            if character in {"\r", "\n"} or not _is_default_ignorable(character)
        )
        candidate = unicodedata.normalize("NFKC", unquote(candidate))
        if candidate == decoded:
            break
        decoded = candidate
    return decoded


def _is_default_ignorable(character: str) -> bool:
    codepoint = ord(character)
    return (
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        or codepoint in {0x034F, 0x3164, 0xFEFF, 0xFFA0}
        or 0x115F <= codepoint <= 0x1160
        or 0x17B4 <= codepoint <= 0x17B5
        or 0x180B <= codepoint <= 0x180F
        or 0x2060 <= codepoint <= 0x206F
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xFFF0 <= codepoint <= 0xFFF8
        or 0x1BCA0 <= codepoint <= 0x1BCA3
        or 0x1D173 <= codepoint <= 0x1D17A
        or 0xE0000 <= codepoint <= 0xE0FFF
    )


def _is_sensitive_config_name(value: str) -> bool:
    words = [word for word in re.split(r"[^a-z0-9]+", value.casefold()) if word]
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    if not words:
        return False
    if normalized.endswith("publickey"):
        return False
    if normalized in {
        "auth",
        "authorization",
        "cookie",
        "key",
        "password",
        "secret",
        "token",
    } or normalized.endswith(
        (
            "accesskey",
            "apikey",
            "clientsecret",
            "connectionstring",
            "credential",
            "credentials",
            "cookievalue",
            "databaseurl",
            "dburl",
            "dsn",
            "githubpat",
            "gitlabpat",
            "mongodburl",
            "mysqlurl",
            "passphrase",
            "password",
            "passwd",
            "postgresurl",
            "privatekey",
            "redisurl",
            "secret",
            "token",
            "authorizationvalue",
            "webhookurl",
        )
    ):
        return True
    if words[-1] in {
        "auth",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "dsn",
        "key",
        "password",
        "passwd",
        "passphrase",
        "pat",
        "secret",
        "token",
    }:
        return True
    if words[-2:] in (
        ["client", "secret"],
        ["connection", "string"],
        ["private", "key"],
        ["webhook", "url"],
    ):
        return True
    if words[-1] == "url" and words[-2:-1] in (
        ["database"],
        ["db"],
        ["mongodb"],
        ["mysql"],
        ["postgres"],
        ["redis"],
    ):
        return True
    if normalized.endswith(
        (
            "apikeybase",
            "apikeyconfig",
            "apikeyfile",
            "apikeyvalue",
            "authconfig",
            "secretkeybase",
            "tokenvalue",
        )
    ):
        return True
    if words[-1] in {"base", "config", "file", "value"}:
        stem = words[:-1]
        return bool(stem) and (
            stem[-1] in {"auth", "credential", "credentials", "secret", "token"}
            or stem[-2:] in (["api", "key"], ["secret", "key"])
        )
    return False


def _configured_value_is_placeholder(value: str) -> bool:
    value = re.sub(r"(?:\\[rnt])+$", "", value.strip(), flags=re.I)
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return not normalized or normalized in {
        "api_key_placeholder",
        "change_me",
        "changeme",
        "configured",
        "enter_api_key_here",
        "example",
        "false",
        "insert_api_key_here",
        "none",
        "null",
        "placeholder",
        "redacted",
        "redacted_redacted_redacted",
        "replace_me_with_your_api_key",
        "replace_with_your_api_key",
        "sample",
        "test",
        "test_key",
        "todo",
        "true",
        "unset",
        "yes",
        "no",
        "your_api_key",
    }


def _static_security_value_rank(value: str) -> tuple[bool, bool, int, str]:
    return (
        any(pattern.search(value) for _, pattern in SECRET_PATTERNS),
        not _configured_value_is_placeholder(value),
        len(value),
        value,
    )


def _select_static_security_value(values: Iterable[str | None]) -> str | None:
    candidates = {
        value
        for value in values
        if value is not None and not _structured_value_is_reference(value)
    }
    return max(candidates, key=_static_security_value_rank) if candidates else None


def _structured_value_is_reference(value: str) -> bool:
    if re.fullmatch(
        r"(?:\$(?:env:)?[A-Za-z_][A-Za-z0-9_]*|\$\{env:[A-Za-z_][A-Za-z0-9_]*\}|"
        r"%[A-Za-z_][A-Za-z0-9_]*%|"
        r"\$\([^)]+\))",
        value,
    ):
        return True
    expansion = re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::[-+?=](?P<fallback>[^}]*))?\}", value)
    if expansion is None:
        return False
    fallback = expansion.group("fallback")
    return fallback in {None, ""} or fallback.casefold() in {
        "change_me",
        "changeme",
        "default",
        "fallback",
        "placeholder",
        "redacted",
        "unset",
    }


def _ast_offset(text: str, line_offsets: list[int], lineno: int, byte_offset: int) -> int:
    """Translate CPython's UTF-8 AST column offsets into character offsets."""
    line_start = line_offsets[lineno - 1]
    line_end = text.find("\n", line_start)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    prefix = line.encode("utf-8")[:byte_offset].decode("utf-8", errors="ignore")
    return line_start + len(prefix)


def _assignment_target_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Attribute):
        return (target.attr,)
    if isinstance(target, ast.Starred):
        return _assignment_target_names(target.value)
    if isinstance(target, (ast.List, ast.Tuple)):
        return tuple(name for item in target.elts for name in _assignment_target_names(item))
    if isinstance(target, ast.Subscript):
        key = _static_python_text(target.slice)
        return (key,) if key is not None else ()
    return ()


def _static_python_text(
    node: ast.AST,
    bindings: dict[str, str] | None = None,
    *,
    depth: int = 0,
) -> str | None:
    if depth > 64:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            return node.value.decode("utf-8", errors="replace")
        return None
    if isinstance(node, ast.Name) and bindings is not None:
        return bindings.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_python_text(node.left, bindings, depth=depth + 1)
        right = _static_python_text(node.right, bindings, depth=depth + 1)
        if left is not None and right is not None and len(left) + len(right) <= 1_000_000:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            part = _static_python_text(value, bindings, depth=depth + 1)
            if part is None:
                return None
            parts.append(part)
        candidate = "".join(parts)
        return candidate if len(candidate) <= 1_000_000 else None
    return None


def _static_python_security_text(
    node: ast.AST,
    bindings: dict[str, str] | None = None,
    *,
    depth: int = 0,
) -> str | None:
    """Recover additional constant-only string forms for signature scanning."""
    if depth > 64:
        return None
    direct = _static_python_text(node, bindings, depth=depth)
    if direct is not None:
        return direct
    if isinstance(node, ast.FormattedValue):
        if node.conversion != -1 or node.format_spec is not None:
            return None
        return _static_python_security_text(node.value, bindings, depth=depth + 1)
    if isinstance(node, ast.JoinedStr):
        parts = [
            _static_python_security_text(value, bindings, depth=depth + 1)
            for value in node.values
        ]
        if any(part is None for part in parts):
            return None
        candidate = "".join(part for part in parts if part is not None)
        return candidate if len(candidate) <= 1_000_000 else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_python_security_text(node.left, bindings, depth=depth + 1)
        right = _static_python_security_text(node.right, bindings, depth=depth + 1)
        if left is not None and right is not None and len(left) + len(right) <= 1_000_000:
            return left + right
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int):
            value = _static_python_security_text(node.left, bindings, depth=depth + 1)
            count = node.right.value
        elif isinstance(node.left, ast.Constant) and isinstance(node.left.value, int):
            value = _static_python_security_text(node.right, bindings, depth=depth + 1)
            count = node.left.value
        else:
            return None
        if value is not None and 0 <= count <= 1_000_000 and len(value) * count <= 1_000_000:
            return value * count
    if isinstance(node, ast.IfExp):
        return _select_static_security_value(
            _static_python_security_text(value, bindings, depth=depth + 1)
            for value in (node.body, node.orelse)
        )
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _select_static_security_value(
            _static_python_security_text(value, bindings, depth=depth + 1)
            for value in node.values
        )
    if isinstance(node, ast.Call):
        function_name = ""
        if isinstance(node.func, ast.Name):
            function_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr
        if function_name in {"get", "getenv", "setdefault"}:
            defaults: list[ast.AST] = list(node.args[1:2])
            defaults.extend(
                keyword.value
                for keyword in node.keywords
                if keyword.arg in {"default", "fallback"}
            )
            return _select_static_security_value(
                _static_python_security_text(value, bindings, depth=depth + 1)
                for value in defaults
            )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], (ast.List, ast.Tuple))
    ):
        separator = _static_python_security_text(node.func.value, bindings, depth=depth + 1)
        parts = [
            _static_python_security_text(item, bindings, depth=depth + 1)
            for item in node.args[0].elts
        ]
        if separator is not None and all(part is not None for part in parts):
            candidate = separator.join(part for part in parts if part is not None)
            return candidate if len(candidate) <= 1_000_000 else None
    return None


PYTHON_COMPREHENSION_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
PYTHON_SCOPE_NODES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    *PYTHON_COMPREHENSION_NODES,
)


def _python_static_binding_snapshots(tree: ast.AST) -> dict[int, dict[str, str]]:
    """Resolve immutable, single-binding strings within their lexical Python scope."""
    snapshots: dict[int, dict[str, str]] = {}

    def scope_children(scope: ast.AST) -> tuple[ast.AST, ...]:
        if isinstance(scope, ast.Lambda):
            return (scope.body,)
        return tuple(getattr(scope, "body", ()))

    def direct_walk(scope: ast.AST) -> tuple[ast.AST, ...]:
        nodes: list[ast.AST] = []

        def visit(node: ast.AST) -> None:
            nodes.append(node)
            for child in ast.iter_child_nodes(node):
                if isinstance(child, PYTHON_SCOPE_NODES):
                    nodes.append(child)
                    continue
                visit(child)

        for child in scope_children(scope):
            visit(child)
        return tuple(nodes)

    def build(scope: ast.AST, inherited: dict[str, str]) -> None:
        direct_nodes = direct_walk(scope)
        counts: Counter[str] = Counter()
        candidates: list[tuple[str, ast.AST]] = []

        def local_target_names(target: ast.AST) -> tuple[str, ...]:
            if isinstance(target, ast.Name):
                return (target.id,)
            if isinstance(target, ast.Starred):
                return local_target_names(target.value)
            if isinstance(target, (ast.List, ast.Tuple)):
                return tuple(
                    name for item in target.elts for name in local_target_names(item)
                )
            return ()

        def bind_target(target: ast.AST) -> tuple[str, ...]:
            names = local_target_names(target)
            counts.update(names)
            return names

        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = scope.args
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ):
                counts[argument.arg] += 1
            if arguments.vararg is not None:
                counts[arguments.vararg.arg] += 1
            if arguments.kwarg is not None:
                counts[arguments.kwarg.arg] += 1

        for node in direct_nodes:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in bind_target(target):
                        candidates.append((name, node.value))
            elif isinstance(node, ast.AnnAssign):
                for name in bind_target(node.target):
                    if node.value is not None:
                        candidates.append((name, node.value))
            elif isinstance(node, ast.NamedExpr):
                for name in bind_target(node.target):
                    candidates.append((name, node.value))
            elif isinstance(node, ast.AugAssign):
                bind_target(node.target)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                bind_target(node.target)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        bind_target(item.optional_vars)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                counts[node.name] += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                counts[node.name] += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    counts[alias.asname or alias.name.split(".", 1)[0]] += 1
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                for name in node.names:
                    counts[name] += 2

        local_names = set(counts)
        resolved = {name: value for name, value in inherited.items() if name not in local_names}
        pending = [(name, value) for name, value in candidates if counts[name] == 1]
        for _ in range(len(pending) + 1):
            changed = False
            for name, value_node in pending:
                if name in resolved:
                    continue
                value = _static_python_security_text(value_node, resolved)
                if value is not None and len(value) <= 1_000_000:
                    resolved[name] = value
                    changed = True
            if not changed:
                break

        snapshots[id(scope)] = dict(resolved)
        for node in direct_nodes:
            snapshots[id(node)] = dict(resolved)
        for node in direct_nodes:
            if isinstance(node, PYTHON_SCOPE_NODES) and node is not scope:
                build(node, resolved)

    if isinstance(tree, PYTHON_SCOPE_NODES):
        build(tree, {})
    return snapshots


def _python_flow_binding_snapshots(tree: ast.AST) -> dict[int, dict[str, str]]:
    """Track definite static strings at each Python use site without crossing scopes."""
    snapshots: dict[int, dict[str, str]] = {}

    def target_names(target: ast.AST) -> tuple[str, ...]:
        if isinstance(target, ast.Name):
            return (target.id,)
        if isinstance(target, ast.Starred):
            return target_names(target.value)
        if isinstance(target, (ast.List, ast.Tuple)):
            return tuple(name for item in target.elts for name in target_names(item))
        return ()

    def local_names(scope: ast.AST) -> set[str]:
        names: set[str] = set()

        def visit(node: ast.AST) -> None:
            if node is not scope and isinstance(node, PYTHON_SCOPE_NODES):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                return
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                names.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                names.add(node.name)
            for child in ast.iter_child_nodes(node):
                visit(child)

        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = scope.args
            names.update(
                argument.arg
                for argument in (
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                )
            )
            if arguments.vararg is not None:
                names.add(arguments.vararg.arg)
            if arguments.kwarg is not None:
                names.add(arguments.kwarg.arg)
        if isinstance(scope, PYTHON_COMPREHENSION_NODES):
            for generator in scope.generators:
                names.update(target_names(generator.target))
        for child in (
            (scope.body,) if isinstance(scope, ast.Lambda) else tuple(getattr(scope, "body", ()))
        ):
            visit(child)
        return names

    def match_capture_names(pattern: ast.pattern) -> tuple[str, ...]:
        names: list[str] = []
        for node in ast.walk(pattern):
            if isinstance(node, ast.MatchAs) and node.name:
                names.append(node.name)
            elif isinstance(node, ast.MatchStar) and node.name:
                names.append(node.name)
            elif isinstance(node, ast.MatchMapping) and node.rest:
                names.append(node.rest)
        return tuple(dict.fromkeys(names))

    def merge_environments(environments: list[dict[str, str]]) -> dict[str, str]:
        if not environments:
            return {}

        # This is a release-time leak detector, so bindings are deliberately
        # "may be static" rather than compiler-style definite assignments. If
        # any executable path can carry a static value to a later credential
        # sink, retain a representative value and block the release. A later
        # unconditional dynamic assignment still removes the binding in
        # update_assignment(), which keeps the analysis useful without making
        # branch order a bypass.
        merged: dict[str, str] = {}
        for name in set().union(*(environment.keys() for environment in environments)):
            candidates = {
                environment[name] for environment in environments if name in environment
            }
            if not candidates:
                continue
            selected = _select_static_security_value(candidates)
            if selected is not None:
                merged[name] = selected
        return merged

    active_scope: ast.AST | None = None
    active_child_scopes: list[tuple[ast.AST, dict[str, str]]] | None = None

    def record(node: ast.AST, environment: dict[str, str]) -> None:
        snapshots[id(node)] = dict(environment)
        if node is not active_scope and isinstance(node, PYTHON_SCOPE_NODES):
            if active_child_scopes is not None:
                active_child_scopes.append((node, dict(environment)))
            return
        for child in ast.iter_child_nodes(node):
            record(child, environment)

    def assignment_values(
        target: ast.AST,
        value_node: ast.AST | None,
        environment: dict[str, str],
        *,
        depth: int = 0,
    ) -> tuple[tuple[str, str | None], ...]:
        """Resolve bounded literal unpacking while preserving dynamic shadowing."""
        if depth > 64:
            return tuple((name, None) for name in target_names(target))
        if isinstance(target, ast.Name):
            value = (
                _static_python_security_text(value_node, environment)
                if value_node is not None
                else None
            )
            return ((target.id, value),)
        if (
            isinstance(target, (ast.List, ast.Tuple))
            and isinstance(value_node, (ast.List, ast.Tuple))
            and len(target.elts) == len(value_node.elts)
            and len(target.elts) <= 1024
            and not any(isinstance(item, ast.Starred) for item in target.elts)
        ):
            return tuple(
                pair
                for target_item, value_item in zip(target.elts, value_node.elts, strict=True)
                for pair in assignment_values(
                    target_item,
                    value_item,
                    environment,
                    depth=depth + 1,
                )
            )
        return tuple((name, None) for name in target_names(target))

    def update_assignment(
        environment: dict[str, str], targets: tuple[ast.AST, ...], value_node: ast.AST | None
    ) -> None:
        for target in targets:
            for name, value in assignment_values(target, value_node, environment):
                if value is None:
                    environment.pop(name, None)
                else:
                    environment[name] = value

    def process_block(statements: tuple[ast.stmt, ...], incoming: dict[str, str]) -> dict[str, str]:
        environment = dict(incoming)
        for statement in statements:
            record(statement, environment)
            if isinstance(statement, ast.Assign):
                update_assignment(environment, tuple(statement.targets), statement.value)
            elif isinstance(statement, ast.AnnAssign):
                update_assignment(environment, (statement.target,), statement.value)
            elif isinstance(statement, ast.AugAssign):
                for name in target_names(statement.target):
                    environment.pop(name, None)
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    environment.pop(alias.asname or alias.name.split(".", 1)[0], None)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                environment.pop(statement.name, None)
            elif isinstance(statement, ast.If):
                body = process_block(tuple(statement.body), environment)
                otherwise = process_block(tuple(statement.orelse), environment)
                environment = merge_environments([body, otherwise])
            elif isinstance(statement, (ast.For, ast.AsyncFor)):
                loop_environment = dict(environment)
                for name in target_names(statement.target):
                    loop_environment.pop(name, None)
                body = process_block(tuple(statement.body), loop_environment)
                otherwise = process_block(tuple(statement.orelse), environment)
                environment = merge_environments([environment, body, otherwise])
            elif isinstance(statement, ast.While):
                body = process_block(tuple(statement.body), environment)
                otherwise = process_block(tuple(statement.orelse), environment)
                environment = merge_environments([environment, body, otherwise])
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                with_environment = dict(environment)
                for item in statement.items:
                    if item.optional_vars is not None:
                        for name in target_names(item.optional_vars):
                            with_environment.pop(name, None)
                environment = process_block(tuple(statement.body), with_environment)
            elif isinstance(statement, ast.Try):
                paths = [process_block(tuple(statement.body), environment)]
                for handler in statement.handlers:
                    handler_environment = dict(environment)
                    if handler.name:
                        handler_environment.pop(handler.name, None)
                    paths.append(process_block(tuple(handler.body), handler_environment))
                if statement.orelse:
                    paths.append(process_block(tuple(statement.orelse), paths[0]))
                if statement.finalbody:
                    paths = [process_block(tuple(statement.finalbody), path) for path in paths]
                environment = merge_environments(paths)
            elif isinstance(statement, ast.Match):
                paths = [environment]
                for case in statement.cases:
                    case_environment = dict(environment)
                    for name in match_capture_names(case.pattern):
                        case_environment.pop(name, None)
                    paths.append(process_block(tuple(case.body), case_environment))
                environment = merge_environments(paths)
        return environment

    def build_scope(
        scope: ast.AST,
        inherited: dict[str, str],
        *,
        closure_inherited: dict[str, str] | None = None,
        definition_inherited: dict[str, str] | None = None,
    ) -> None:
        nonlocal active_child_scopes, active_scope
        child_scopes: list[tuple[ast.AST, dict[str, str]]] = []
        active_scope = scope
        active_child_scopes = child_scopes

        environment = {
            name: value for name, value in inherited.items() if name not in local_names(scope)
        }
        definition_environment = (
            definition_inherited if definition_inherited is not None else inherited
        )
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            positional = (*scope.args.posonlyargs, *scope.args.args)
            for argument, default in zip(
                positional[len(positional) - len(scope.args.defaults) :],
                scope.args.defaults,
                strict=True,
            ):
                value = _static_python_security_text(default, definition_environment)
                if value is not None:
                    environment[argument.arg] = value
            for argument, default in zip(
                scope.args.kwonlyargs,
                scope.args.kw_defaults,
                strict=True,
            ):
                if default is None:
                    continue
                value = _static_python_security_text(default, definition_environment)
                if value is not None:
                    environment[argument.arg] = value
        snapshots[id(scope)] = dict(environment)
        if isinstance(scope, PYTHON_COMPREHENSION_NODES):
            for generator in scope.generators:
                record(generator.iter, environment)
                values_by_name: dict[str, list[str | None]] = {
                    name: [] for name in target_names(generator.target)
                }
                if (
                    isinstance(generator.iter, (ast.List, ast.Tuple, ast.Set))
                    and len(generator.iter.elts) <= 1024
                ):
                    for item in generator.iter.elts:
                        for name, value in assignment_values(
                            generator.target,
                            item,
                            environment,
                        ):
                            values_by_name.setdefault(name, []).append(value)
                for name, values in values_by_name.items():
                    value = _select_static_security_value(values)
                    if value is None:
                        environment.pop(name, None)
                    else:
                        environment[name] = value
                record(generator.target, environment)
                for condition in generator.ifs:
                    record(condition, environment)
            if isinstance(scope, ast.DictComp):
                record(scope.key, environment)
                record(scope.value, environment)
            else:
                record(scope.elt, environment)
        elif isinstance(scope, ast.Lambda):
            record(scope.body, environment)
        else:
            environment = process_block(tuple(getattr(scope, "body", ())), environment)

        # Python functions and lambdas resolve free variables when invoked, not
        # when their definition is encountered. Feed children the parent's
        # final may-static bindings so a later credential assignment cannot
        # bypass the release gate. Lexically local names and parameters are
        # removed by local_names() before the child is analyzed.
        late_environment = dict(environment)
        outer_closure = closure_inherited if closure_inherited is not None else late_environment
        for child, definition_environment in child_scopes:
            if isinstance(child, ast.ClassDef):
                build_scope(
                    child,
                    definition_environment,
                    closure_inherited=outer_closure,
                )
            elif isinstance(child, PYTHON_COMPREHENSION_NODES):
                build_scope(child, definition_environment)
            elif isinstance(scope, ast.ClassDef):
                # A method does not close over class attributes. It can still
                # close over the function/module environment surrounding the
                # class definition.
                build_scope(
                    child,
                    outer_closure,
                    definition_inherited=definition_environment,
                )
            else:
                build_scope(
                    child,
                    late_environment,
                    definition_inherited=definition_environment,
                )

    if isinstance(tree, PYTHON_SCOPE_NODES):
        build_scope(tree, {})
    return snapshots


def _javascript_split_top_level(value: str, delimiter: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    quote = ""
    escaped = False
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    for index, character in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in {'"', "'", "`"}:
            quote = character
            continue
        if character in depths:
            depths[character] += 1
            continue
        if character in closing:
            opener = closing[character]
            if depths[opener] > 0:
                depths[opener] -= 1
            continue
        if character == delimiter and not any(depths.values()):
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return tuple(parts)


def _javascript_top_level_operators(
    value: str, operators: tuple[str, ...]
) -> tuple[tuple[int, str], ...]:
    positions: list[tuple[int, str]] = []
    ordered = tuple(sorted(operators, key=len, reverse=True))
    quote = ""
    escaped = False
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if character in depths:
            depths[character] += 1
            index += 1
            continue
        if character in closing:
            opener = closing[character]
            if depths[opener] > 0:
                depths[opener] -= 1
            index += 1
            continue
        if not any(depths.values()):
            matched = next((operator for operator in ordered if value.startswith(operator, index)), None)
            if matched is not None:
                positions.append((index, matched))
                index += len(matched)
                continue
        index += 1
    return tuple(positions)


def _javascript_may_static_alternatives(expression: str) -> tuple[str, ...]:
    operators = _javascript_top_level_operators(expression, ("??", "||", "?", ":"))
    question = next((index for index, operator in operators if operator == "?"), None)
    if question is not None:
        nested = 0
        for index, operator in operators:
            if index <= question:
                continue
            if operator == "?":
                nested += 1
            elif operator == ":":
                if nested == 0:
                    return (expression[question + 1 : index], expression[index + 1 :])
                nested -= 1

    fallback_operators = [
        (index, operator) for index, operator in operators if operator in {"??", "||"}
    ]
    if not fallback_operators:
        return ()
    alternatives: list[str] = []
    start = 0
    for index, operator in fallback_operators:
        alternatives.append(expression[start:index])
        start = index + len(operator)
    alternatives.append(expression[start:])
    return tuple(alternatives)


def _decode_javascript_quoted_literal(value: str) -> str | None:
    value = value.strip()
    if len(value) < 2 or value[0] not in {'"', "'"} or value[-1] != value[0]:
        return None
    body = value[1:-1]
    decoded: list[str] = []
    index = 0
    simple_escapes = {
        "0": "\0",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }
    while index < len(body):
        character = body[index]
        if character != "\\":
            if character == value[0] or character in "\r\n":
                return None
            decoded.append(character)
            index += 1
            continue
        index += 1
        if index >= len(body):
            return None
        escape = body[index]
        if escape in "\r\n":
            if escape == "\r" and index + 1 < len(body) and body[index + 1] == "\n":
                index += 1
            index += 1
            continue
        if escape == "u" and index + 4 < len(body):
            digits = body[index + 1 : index + 5]
            if re.fullmatch(r"[0-9A-Fa-f]{4}", digits):
                decoded.append(chr(int(digits, 16)))
                index += 5
                continue
        if escape == "x" and index + 2 < len(body):
            digits = body[index + 1 : index + 3]
            if re.fullmatch(r"[0-9A-Fa-f]{2}", digits):
                decoded.append(chr(int(digits, 16)))
                index += 3
                continue
        decoded.append(simple_escapes.get(escape, escape))
        index += 1
    candidate = "".join(decoded)
    return candidate if len(candidate) <= 1_000_000 else None


def _strip_javascript_comments(value: str) -> str:
    output: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            output.append(character)
            index += 1
            continue
        if value.startswith("//", index):
            end = value.find("\n", index + 2)
            if end < 0:
                break
            output.append("\n")
            index = end + 1
            continue
        if value.startswith("/*", index):
            end = value.find("*/", index + 2)
            if end < 0:
                break
            output.append(" ")
            output.extend(character for character in value[index:end] if character in "\r\n")
            index = end + 2
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _javascript_static_expression(
    expression: str,
    bindings: dict[str, str],
    *,
    depth: int = 0,
) -> str | None:
    if depth > 64 or len(expression) > 1_000_000:
        return None
    expression = _strip_javascript_comments(expression).strip()
    while expression.startswith("(") and expression.endswith(")"):
        inner = expression[1:-1].strip()
        if not inner:
            break
        expression = inner
    literal = _decode_javascript_quoted_literal(expression)
    if literal is not None:
        return literal
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", expression):
        return bindings.get(expression)

    alternatives = _javascript_may_static_alternatives(expression)
    if alternatives:
        return _select_static_security_value(
            _javascript_static_expression(value, bindings, depth=depth + 1)
            for value in alternatives
        )

    parts = _javascript_split_top_level(expression, "+")
    if len(parts) > 1:
        resolved = [
            _javascript_static_expression(part, bindings, depth=depth + 1) for part in parts
        ]
        if all(part is not None for part in resolved):
            candidate = "".join(part for part in resolved if part is not None)
            return candidate if len(candidate) <= 1_000_000 else None

    join_match = re.fullmatch(
        r"\[(?P<items>[\s\S]{0,1000000})\][ \t]*\.join\([ \t]*"
        r"(?P<separator>[\s\S]{1,4096})[ \t]*\)",
        expression,
    )
    if join_match is not None:
        items = _javascript_split_top_level(join_match.group("items"), ",")
        separator = _javascript_static_expression(
            join_match.group("separator"), bindings, depth=depth + 1
        )
        resolved = [
            _javascript_static_expression(item, bindings, depth=depth + 1)
            for item in items
            if item
        ]
        if separator is not None and resolved and all(item is not None for item in resolved):
            candidate = separator.join(item for item in resolved if item is not None)
            return candidate if len(candidate) <= 1_000_000 else None

    if expression.startswith("`") and expression.endswith("`"):
        body = expression[1:-1]
        pieces: list[str] = []
        cursor = 0
        while cursor < len(body):
            marker = body.find("${", cursor)
            if marker < 0:
                tail = _decode_javascript_quoted_literal('"' + body[cursor:] + '"')
                if tail is None:
                    return None
                pieces.append(tail)
                break
            prefix = _decode_javascript_quoted_literal('"' + body[cursor:marker] + '"')
            if prefix is None:
                return None
            pieces.append(prefix)
            end = body.find("}", marker + 2)
            if end < 0:
                return None
            interpolation = _javascript_static_expression(
                body[marker + 2 : end], bindings, depth=depth + 1
            )
            if interpolation is None:
                return None
            pieces.append(interpolation)
            cursor = end + 1
        candidate = "".join(pieces)
        return candidate if len(candidate) <= 1_000_000 else None
    return None


def _mask_javascript_structure(text: str) -> str:
    masked = list(text)
    # Contexts are either template text or executable code. Interpolation
    # delimiters are masked while the code inside `${...}` remains visible.
    contexts: list[tuple[str, int]] = [("code", -1)]

    def blank(position: int) -> None:
        if masked[position] not in "\r\n":
            masked[position] = " "

    def regex_can_start(position: int) -> bool:
        previous = position - 1
        while previous >= 0 and (masked[previous].isspace() or masked[previous] == " "):
            previous -= 1
        if previous < 0:
            return True
        if masked[previous] in "=([{,:;!?&|+-*%^~<>":
            return True
        if masked[previous].isalnum() or masked[previous] in "_$":
            end = previous + 1
            while previous >= 0 and (masked[previous].isalnum() or masked[previous] in "_$"):
                previous -= 1
            return "".join(masked[previous + 1 : end]) in {
                "await",
                "case",
                "delete",
                "in",
                "instanceof",
                "new",
                "of",
                "return",
                "throw",
                "typeof",
                "void",
                "yield",
            }
        return False

    index = 0
    while index < len(text):
        mode, brace_depth = contexts[-1]
        character = text[index]
        if mode == "template":
            blank(index)
            if character == "\\":
                index += 1
                if index < len(text):
                    blank(index)
            elif character == "`":
                contexts.pop()
            elif text.startswith("${", index):
                if index + 1 < len(text):
                    blank(index + 1)
                contexts.append(("code", 0))
                index += 1
            index += 1
            continue

        if brace_depth >= 0 and character == "}":
            if brace_depth == 0:
                blank(index)
                contexts.pop()
            else:
                contexts[-1] = ("code", brace_depth - 1)
            index += 1
            continue
        if brace_depth >= 0 and character == "{":
            contexts[-1] = ("code", brace_depth + 1)
            index += 1
            continue
        if character in {'"', "'"}:
            quote = character
            blank(index)
            index += 1
            escaped = False
            while index < len(text):
                current = text[index]
                blank(index)
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    index += 1
                    break
                index += 1
            continue
        if character == "`":
            blank(index)
            contexts.append(("template", -1))
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            end = len(text) if end < 0 else end
            for position in range(index, end):
                blank(position)
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) - 2 if end < 0 else end
            for position in range(index, min(len(text), end + 2)):
                blank(position)
            index = min(len(text), end + 2)
            continue
        if character == "/" and regex_can_start(index):
            blank(index)
            index += 1
            escaped = False
            character_class = False
            while index < len(text):
                current = text[index]
                blank(index)
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == "[":
                    character_class = True
                elif current == "]" and character_class:
                    character_class = False
                elif current == "/" and not character_class:
                    index += 1
                    while index < len(text) and text[index].isalpha():
                        blank(index)
                        index += 1
                    break
                elif current in "\r\n":
                    break
                index += 1
            continue
        index += 1
    return "".join(masked)


def _javascript_expression_end(text: str, start: int) -> int:
    limit = min(len(text), start + 1_000_000)
    continuation_before_characters = {
        "+",
        "-",
        "*",
        "/",
        "%",
        "&",
        "|",
        "^",
        "?",
        ":",
        ",",
        ".",
        "(",
        "=",
        "[",
        "{",
    }
    continuation_after_characters = {
        "+",
        "-",
        "*",
        "/",
        "%",
        "&",
        "|",
        "^",
        "?",
        ":",
        ",",
        ".",
    }
    quote = ""
    escaped = False
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    index = start
    while index < limit:
        character = text[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            if end < 0:
                return index
            before = text[start:index].rstrip()
            next_index = end + 1
            while next_index < limit and text[next_index] in " \t\r\n":
                next_index += 1
            if (
                before
                and before[-1] not in continuation_before_characters
                and text[next_index : next_index + 1] not in continuation_after_characters
            ):
                return index
            index = end + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                return index
            after_comment = end + 2
            next_index = after_comment
            while next_index < limit and text[next_index] in " \t\r\n":
                next_index += 1
            crossed_line = any(
                character in "\r\n" for character in text[after_comment:next_index]
            )
            before = text[start:index].rstrip()
            if (
                crossed_line
                and before
                and before[-1] not in continuation_before_characters
                and text[next_index : next_index + 1] not in continuation_after_characters
            ):
                return index
            index = after_comment
            continue
        if character in {'"', "'", "`"}:
            quote = character
        elif character in depths:
            depths[character] += 1
        elif character in closing:
            opener = closing[character]
            if depths[opener] > 0:
                depths[opener] -= 1
        elif not any(depths.values()):
            if character == ";":
                return index
            if character in "\r\n":
                before = text[start:index].rstrip()
                next_index = index + 1
                if character == "\r" and next_index < limit and text[next_index] == "\n":
                    next_index += 1
                while next_index < limit and text[next_index] in " \t\r\n":
                    next_index += 1
                next_character = text[next_index : next_index + 1]
                continuation_before = before[-1:] in continuation_before_characters
                continuation_after = next_character in continuation_after_characters
                if before and not continuation_before and not continuation_after:
                    return index
        index += 1
    return limit


def _javascript_matching_brace(text: str, opening: int) -> int | None:
    depth = 0
    quote = ""
    escaped = False
    index = opening
    while index < len(text):
        character = text[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        if character in {'"', "'", "`"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _javascript_parameter_names(parameters: str) -> frozenset[str]:
    names: set[str] = set()
    for item in _javascript_split_top_level(parameters, ","):
        candidate = item.strip()
        if not candidate:
            continue
        if candidate[:1] in {"{", "["}:
            names.update(_javascript_destructuring_target_names(candidate))
            continue
        candidate = candidate.split("=", 1)[0].strip()
        candidate = re.sub(
            r"^(?:(?:public|private|protected|readonly|override)[ \t]+)+",
            "",
            candidate,
        )
        match = re.match(r"(?:\.\.\.[ \t]*)?([A-Za-z_$][A-Za-z0-9_$]*)", candidate)
        if match is not None:
            names.add(match.group(1))
    return frozenset(names)


def _javascript_function_scopes(
    text: str,
) -> tuple[tuple[int, int, frozenset[str], int, str], ...]:
    scopes: dict[tuple[int, int], tuple[frozenset[str], int, str]] = {}
    masked = _mask_javascript_structure(text)

    def add_scope(start: int, end: int, parameters: str, anchor: int) -> None:
        names = _javascript_parameter_names(parameters)
        previous = scopes.get((start, end))
        if previous is None:
            scopes[(start, end)] = (names, anchor, parameters)
            return
        scopes[(start, end)] = (
            previous[0] | names,
            min(previous[1], anchor),
            previous[2] if len(previous[2]) >= len(parameters) else parameters,
        )

    def add_braced_scope(opening: int, parameters: str, anchor: int) -> None:
        closing = _javascript_matching_brace(text, opening)
        if closing is not None:
            add_scope(opening + 1, closing, parameters, anchor)

    def add_arrow_scope(body_start: int, parameters: str, anchor: int) -> None:
        while body_start < len(masked) and masked[body_start] in " \t\r\n":
            body_start += 1
        if body_start >= len(masked):
            return
        if masked[body_start] == "{":
            add_braced_scope(body_start, parameters, anchor)
            return
        end = _javascript_expression_end(text, body_start)
        if end > body_start:
            add_scope(body_start, end, parameters, anchor)

    for match in JAVASCRIPT_FUNCTION_PARAMETERS.finditer(masked):
        parameters = match.group("parameters")
        if parameters is not None:
            parameter_start, parameter_end = match.span("parameters")
            parameters = text[parameter_start:parameter_end]
            opening = masked.find("{", match.end(), min(len(masked), match.end() + 2048))
            if opening >= 0:
                add_braced_scope(opening, parameters, match.start())
            continue
        parameter_start, parameter_end = match.span("arrow_parameters")
        add_arrow_scope(
            match.end(),
            text[parameter_start:parameter_end],
            match.start(),
        )

    control_words = {"catch", "for", "if", "switch", "while", "with"}
    for match in JAVASCRIPT_METHOD_PARAMETERS.finditer(masked):
        if match.group("method") in control_words:
            continue
        opening = masked.rfind("{", match.start(), match.end())
        if opening >= 0:
            parameter_start, parameter_end = match.span("parameters")
            add_braced_scope(
                opening,
                text[parameter_start:parameter_end],
                match.start(),
            )

    for match in JAVASCRIPT_SINGLE_ARROW_PARAMETER.finditer(masked):
        add_arrow_scope(match.end(), match.group("parameter"), match.start())

    return tuple(
        (start, end, names, anchor, parameters)
        for (start, end), (names, anchor, parameters) in sorted(
            scopes.items(), key=lambda item: (item[0][0], -item[0][1])
        )
    )


def _javascript_brace_scopes(
    text: str,
    declaration_positions: Iterable[int] | None = None,
) -> tuple[tuple[int, int], ...]:
    """Return braces that directly enclose lexical declarations.

    Object literals do not create lexical environments. Selecting only the
    innermost brace active at a declaration keeps both semantics and runtime
    linear on source files containing thousands of ordinary object literals.
    """
    masked = _mask_javascript_structure(text)
    openings: list[int] = []
    closing_by_opening: dict[int, int] = {}
    selected_openings: set[int] = set()
    requested = iter(sorted(set(declaration_positions or ())))
    next_position = next(requested, None)
    for position, character in enumerate(masked):
        while next_position is not None and next_position == position:
            if openings:
                selected_openings.add(openings[-1])
            next_position = next(requested, None)
        if character == "{":
            openings.append(position)
        elif character == "}" and openings:
            opening = openings.pop()
            closing_by_opening[opening] = position
    return tuple(
        sorted(
            (
                (opening + 1, closing_by_opening[opening])
                for opening in selected_openings
                if opening in closing_by_opening
            ),
            key=lambda item: (item[0], -item[1]),
        )
    )


def _javascript_matching_parenthesis(masked: str, opening: int) -> int | None:
    depth = 0
    for position in range(opening, min(len(masked), opening + 1_000_000)):
        character = masked[position]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return position
    return None


def _javascript_statement_scope(text: str, masked: str, start: int) -> tuple[int, int] | None:
    while start < len(masked) and masked[start] in " \t\r\n":
        start += 1
    if start >= len(masked) or masked[start] == "{":
        return None
    end = _javascript_expression_end(text, start)
    if end <= start:
        return None
    return (start, min(len(text), end + (text[end : end + 1] == ";")))


def _javascript_for_lexical_scopes(
    text: str,
) -> tuple[tuple[tuple[int, int], tuple[int, int] | None], ...]:
    """Return `for (let/const ...)` scopes and classic-loop update ranges."""
    masked = _mask_javascript_structure(text)
    results: list[tuple[tuple[int, int], tuple[int, int] | None]] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_$.])for[ \t\r\n]*\(", masked):
        opening = masked.find("(", match.start(), match.end())
        closing = _javascript_matching_parenthesis(masked, opening)
        if closing is None:
            continue
        body_start = closing + 1
        while body_start < len(masked) and masked[body_start] in " \t\r\n":
            body_start += 1
        if body_start >= len(masked):
            continue
        if masked[body_start] == "{":
            body_closing = _javascript_matching_brace(text, body_start)
            body_end = body_closing + 1 if body_closing is not None else None
        else:
            statement = _javascript_statement_scope(text, masked, body_start)
            body_end = statement[1] if statement is not None else None
        if body_end is None:
            continue

        header = masked[opening + 1 : closing]
        declaration = re.match(r"[ \t\r\n]*(?:let|const)\b", header)
        if declaration is None:
            continue
        separators = _javascript_top_level_operators(header, (";",))
        update_range = None
        if len(separators) == 2:
            update_start = opening + 1 + separators[1][0] + 1
            if update_start < closing:
                update_range = (update_start, closing)
        results.append(((opening + 1, body_end), update_range))
    return tuple(results)


def _javascript_catch_bindings(
    text: str,
) -> tuple[tuple[tuple[int, int], frozenset[str]], ...]:
    """Return catch-block ranges and their lexically scoped parameter names."""
    masked = _mask_javascript_structure(text)
    bindings: list[tuple[tuple[int, int], frozenset[str]]] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_$.])catch[ \t\r\n]*\(", masked):
        opening = masked.find("(", match.start(), match.end())
        closing = _javascript_matching_parenthesis(masked, opening)
        if closing is None:
            continue
        body_opening = closing + 1
        while body_opening < len(masked) and masked[body_opening] in " \t\r\n":
            body_opening += 1
        if body_opening >= len(masked) or masked[body_opening] != "{":
            continue
        body_closing = _javascript_matching_brace(text, body_opening)
        if body_closing is None:
            continue
        names = _javascript_parameter_names(masked[opening + 1 : closing])
        if names:
            bindings.append(((body_opening + 1, body_closing), names))
    return tuple(bindings)


def _javascript_conditional_scopes(text: str) -> tuple[tuple[int, int], ...]:
    masked = _mask_javascript_structure(text)
    scopes: set[tuple[int, int]] = set()
    for match in JAVASCRIPT_CONDITIONAL_BLOCK.finditer(masked):
        opening = masked.rfind("{", match.start(), match.end())
        if opening < 0:
            continue
        closing = _javascript_matching_brace(text, opening)
        if closing is not None:
            scopes.add((opening + 1, closing))
    for match in JAVASCRIPT_PARENTHESIZED_CONTROL.finditer(masked):
        opening = masked.find("(", match.start(), match.end())
        closing = _javascript_matching_parenthesis(masked, opening)
        if closing is None:
            continue
        scope = _javascript_statement_scope(text, masked, closing + 1)
        if scope is not None:
            scopes.add(scope)
    for match in JAVASCRIPT_BARE_CONTROL.finditer(masked):
        body_start = match.end()
        if match.group("control") == "else":
            probe = body_start
            while probe < len(masked) and masked[probe] in " \t\r\n":
                probe += 1
            if re.match(r"if\b", masked[probe:]) is not None:
                continue
        scope = _javascript_statement_scope(text, masked, body_start)
        if scope is not None:
            scopes.add(scope)
    for _, update_scope in _javascript_for_lexical_scopes(text):
        if update_scope is not None:
            scopes.add(update_scope)
    return tuple(sorted(scopes))


def _prefer_static_security_value(first: str, second: str) -> str:
    selected = _select_static_security_value((first, second))
    return selected if selected is not None else first


def _javascript_pattern_default(pattern: str) -> tuple[str, str | None]:
    operators = _javascript_top_level_operators(pattern, ("=",))
    if not operators:
        return pattern.strip(), None
    position = operators[0][0]
    return pattern[:position].strip(), pattern[position + 1 :].strip() or None


def _javascript_destructuring_target_names(
    pattern: str,
    *,
    depth: int = 0,
) -> tuple[str, ...]:
    """Extract every binding introduced by a bounded JS binding pattern."""
    if depth > 64 or len(pattern) > 1_000_000:
        return ()
    candidate, _ = _javascript_pattern_default(
        _strip_javascript_comments(pattern).strip()
    )
    if candidate.startswith("..."):
        return _javascript_destructuring_target_names(
            candidate[3:], depth=depth + 1
        )
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", candidate):
        return (candidate,)
    if (
        len(candidate) < 2
        or candidate[0] not in "[{"
        or candidate[-1] != ({"[": "]", "{": "}"})[candidate[0]]
    ):
        return ()

    names: list[str] = []
    items = _javascript_split_top_level(candidate[1:-1], ",")
    if len(items) > 1024:
        return ()
    for item in items:
        target = item.strip()
        if not target:
            continue
        if candidate[0] == "{":
            operators = _javascript_top_level_operators(target, (":",))
            if operators:
                target = target[operators[0][0] + 1 :].strip()
        names.extend(
            _javascript_destructuring_target_names(target, depth=depth + 1)
        )
    return tuple(dict.fromkeys(names))


def _javascript_parameter_defaults(parameters: str) -> tuple[tuple[str, str], ...]:
    defaults: list[tuple[str, str]] = []
    for item in _javascript_split_top_level(parameters, ","):
        operators = _javascript_top_level_operators(item, ("=",))
        if not operators:
            candidate = item.strip()
            if candidate[:1] in {"{", "["}:
                # Nested binding defaults can apply even when the parameter
                # pattern itself has no top-level default expression.
                defaults.append((candidate, ""))
            continue
        position = operators[0][0]
        target = item[:position].strip()
        expression = item[position + 1 :].strip()
        if not target or not expression:
            continue
        if target[:1] not in {"{", "["}:
            target = target.split(":", 1)[0].strip()
        defaults.append((target, expression))
    return tuple(defaults)


def _javascript_for_binding_events(
    text: str,
) -> tuple[tuple[int, int, str, str, str], ...]:
    masked = _mask_javascript_structure(text)
    events: list[tuple[int, int, str, str, str]] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_$.])for[ \t\r\n]*\(", masked):
        opening = masked.find("(", match.start(), match.end())
        closing = _javascript_matching_parenthesis(masked, opening)
        if closing is None:
            continue
        header = text[opening + 1 : closing]
        declaration = re.match(
            r"[ \t\r\n]*(?P<kind>let|const|var)[ \t]+",
            header,
        )
        if declaration is None:
            continue
        target_start = declaration.end()
        target_opening = header[target_start : target_start + 1]
        if target_opening and target_opening in "[{":
            stack: list[str] = [header[target_start]]
            delimiter_pairs = {"}": "{", "]": "[", ")": "("}
            target_end = None
            for position in range(target_start + 1, min(len(header), target_start + 1_000_000)):
                character = header[position]
                if character in "[{(":
                    stack.append(character)
                elif character in delimiter_pairs:
                    if not stack or stack[-1] != delimiter_pairs[character]:
                        break
                    stack.pop()
                    if not stack:
                        target_end = position + 1
                        break
            if target_end is None:
                continue
        else:
            target_match = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", header[target_start:])
            if target_match is None:
                continue
            target_end = target_start + target_match.end()
        operator = re.match(r"[ \t\r\n]+(?P<operator>of|in)\b", header[target_end:])
        if operator is None:
            continue
        expression_start = target_end + operator.end()
        expression = header[expression_start:].strip()
        if not expression:
            continue
        start = opening + 1 + declaration.start("kind")
        events.append(
            (
                start,
                closing,
                f"for-{operator.group('operator')}-{declaration.group('kind')}",
                header[target_start:target_end],
                expression,
            )
        )
    return tuple(events)


def _javascript_property_key(value: str) -> str | None:
    value = value.strip()
    literal = _decode_javascript_quoted_literal(value)
    if literal is not None:
        return literal
    return value if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value) else None


def _javascript_destructured_values(
    pattern: str,
    expression: str,
    bindings: dict[str, str],
    *,
    depth: int = 0,
) -> tuple[tuple[str, str | None], ...]:
    """Resolve bounded nested JS binding patterns and their may-defaults."""
    if depth > 64 or len(pattern) + len(expression) > 1_000_000:
        return ()
    pattern = _strip_javascript_comments(pattern).strip()
    expression = _strip_javascript_comments(expression).strip()
    names = _javascript_destructuring_target_names(pattern)
    if not names:
        return ()

    def merge(
        *groups: Iterable[tuple[str, str | None]],
    ) -> tuple[tuple[str, str | None], ...]:
        candidates: dict[str, list[str | None]] = {name: [] for name in names}
        for group in groups:
            for name, value in group:
                candidates.setdefault(name, []).append(value)
        return tuple(
            (name, _select_static_security_value(candidates.get(name, ())))
            for name in names
        )

    target, default_expression = _javascript_pattern_default(pattern)
    if target.startswith("..."):
        # Rest creates a binding but its aggregate value is not itself a
        # scalar credential. It must still shadow every outer binding.
        return tuple((name, None) for name in names)
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", target):
        return (
            (
                target,
                _select_static_security_value(
                    (
                        _javascript_static_expression(expression, bindings)
                        if expression
                        else None,
                        _javascript_static_expression(default_expression, bindings)
                        if default_expression
                        else None,
                    )
                ),
            ),
        )

    defaults: tuple[tuple[str, str | None], ...] = ()
    if default_expression:
        defaults = _javascript_destructured_values(
            target,
            default_expression,
            bindings,
            depth=depth + 1,
        )

    if target.startswith("["):
        targets = _javascript_split_top_level(target[1:-1], ",")
        if len(targets) > 1024:
            return merge(defaults)
        values = (
            _javascript_split_top_level(expression[1:-1], ",")
            if expression.startswith("[") and expression.endswith("]")
            else ()
        )
        resolved: list[tuple[str, str | None]] = []
        for index, nested_target in enumerate(targets):
            if not nested_target.strip():
                continue
            nested_expression = values[index] if index < len(values) else ""
            resolved.extend(
                _javascript_destructured_values(
                    nested_target,
                    nested_expression,
                    bindings,
                    depth=depth + 1,
                )
            )
        return merge(resolved, defaults)

    if not target.startswith("{"):
        return merge(defaults)
    source_values: dict[str, str] = {}
    if expression.startswith("{") and expression.endswith("}"):
        source_items = _javascript_split_top_level(expression[1:-1], ",")
        if len(source_items) <= 1024:
            for item in source_items:
                operators = _javascript_top_level_operators(item, (":",))
                if operators:
                    position = operators[0][0]
                    key = _javascript_property_key(item[:position])
                    value = item[position + 1 :]
                else:
                    key = _javascript_property_key(item)
                    value = item
                if key is not None:
                    source_values[key] = value

    resolved = []
    items = _javascript_split_top_level(target[1:-1], ",")
    if len(items) > 1024:
        return merge(defaults)
    for item in items:
        candidate = item.strip()
        if not candidate:
            continue
        if candidate.startswith("..."):
            resolved.extend((name, None) for name in _javascript_destructuring_target_names(candidate))
            continue
        operators = _javascript_top_level_operators(candidate, (":",))
        if operators:
            position = operators[0][0]
            key = _javascript_property_key(candidate[:position])
            nested_target = candidate[position + 1 :]
        else:
            binding_target, _ = _javascript_pattern_default(candidate)
            key = _javascript_property_key(binding_target)
            nested_target = candidate
        resolved.extend(
            _javascript_destructured_values(
                nested_target,
                source_values.get(key, "") if key is not None else "",
                bindings,
                depth=depth + 1,
            )
        )
    return merge(resolved, defaults)


def _javascript_for_iteration_values(
    target: str,
    expression: str,
    operator: str,
    bindings: dict[str, str],
) -> tuple[tuple[str, str | None], ...]:
    expression = _strip_javascript_comments(expression).strip()
    names = (
        _javascript_destructuring_target_names(target)
        if target[:1] in "[{"
        else (target,)
    )
    candidates: list[str] = []
    if operator == "of" and expression.startswith("[") and expression.endswith("]"):
        candidates.extend(_javascript_split_top_level(expression[1:-1], ",")[:1024])
    elif operator == "in" and expression.startswith("{") and expression.endswith("}"):
        for item in _javascript_split_top_level(expression[1:-1], ",")[:1024]:
            positions = _javascript_top_level_operators(item, (":",))
            key = _javascript_property_key(item[: positions[0][0]] if positions else item)
            if key is not None:
                candidates.append(repr(key))
    if not candidates:
        return tuple((name, None) for name in names)

    values_by_name: dict[str, list[str | None]] = {name: [] for name in names}
    for candidate in candidates:
        values = (
            _javascript_destructured_values(target, candidate, bindings)
            if target[:1] in "[{"
            else ((target, _javascript_static_expression(candidate, bindings)),)
        )
        for name, value in values:
            values_by_name.setdefault(name, []).append(value)
    return tuple(
        (name, _select_static_security_value(values))
        for name, values in values_by_name.items()
    )


def _javascript_destructuring_declaration_events(
    text: str,
    masked: str,
) -> tuple[tuple[int, int, str, str, str, int, int], ...]:
    """Parse balanced declaration patterns that the shallow regex cannot."""
    events: list[tuple[int, int, str, str, str, int, int]] = []
    for match in re.finditer(
        r"\b(?P<kind>const|let|var)[ \t]+(?P<opening>[\[{])",
        masked,
    ):
        opening = match.start("opening")
        stack: list[str] = [masked[opening]]
        closing = {"}": "{", "]": "[", ")": "("}
        pattern_end = None
        for position in range(opening + 1, min(len(masked), opening + 1_000_000)):
            character = masked[position]
            if character in "[{(":
                stack.append(character)
            elif character in closing:
                if not stack or stack[-1] != closing[character]:
                    break
                stack.pop()
                if not stack:
                    pattern_end = position + 1
                    break
        if pattern_end is None:
            continue
        expression_start = pattern_end
        while expression_start < len(masked) and masked[expression_start] in " \t":
            expression_start += 1
        if masked[expression_start : expression_start + 1] != "=":
            continue
        expression_start += 1
        while expression_start < len(masked) and masked[expression_start] in " \t":
            expression_start += 1
        end = _javascript_expression_end(text, expression_start)
        events.append(
            (
                match.start(),
                end,
                match.group("kind"),
                text[opening:pattern_end],
                text[expression_start:end],
                opening,
                pattern_end,
            )
        )
    return tuple(events)


def _javascript_assignment_events(
    text: str,
) -> tuple[tuple[int, int, str, str, str | None], ...]:
    masked = _mask_javascript_structure(text)
    events: list[tuple[int, int, str, str, str | None]] = []
    declaration_equals: set[int] = set()
    destructuring_pattern_spans: list[tuple[int, int]] = []
    for match in JAVASCRIPT_DECLARATION_START.finditer(masked):
        end = _javascript_expression_end(text, match.end())
        declaration_equals.add(match.end())
        events.append(
            (
                match.start(),
                end,
                match.group("kind"),
                match.group("name"),
                text[match.end() : end],
            )
        )
    for (
        start,
        end,
        kind,
        pattern,
        expression,
        pattern_start,
        pattern_end,
    ) in _javascript_destructuring_declaration_events(text, masked):
        expression_start = end - len(expression)
        declaration_equals.add(expression_start)
        destructuring_pattern_spans.append((pattern_start, pattern_end))
        events.append((start, end, kind, pattern, expression))
    for match in JAVASCRIPT_UNINITIALIZED_DECLARATION.finditer(masked):
        events.append(
            (
                match.start(),
                match.end(),
                match.group("kind"),
                match.group("name"),
                None,
            )
        )
    events.extend(_javascript_for_binding_events(text))
    for match in JAVASCRIPT_ASSIGNMENT_START.finditer(masked):
        if match.end() in declaration_equals or any(
            start <= match.start() < end for start, end in destructuring_pattern_spans
        ):
            continue
        end = _javascript_expression_end(text, match.end())
        events.append((match.start(), end, "assign", match.group("name"), text[match.end() : end]))
    for match in JAVASCRIPT_UPDATED_BINDING.finditer(masked):
        name = match.group("prefix_name") or match.group("name")
        events.append((match.start(), match.end(), "assign", name, None))
    return tuple(sorted(events, key=lambda item: (item[0], item[1])))


@lru_cache(maxsize=8)
def _javascript_static_analysis(
    text: str,
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    syntax = _mask_javascript_structure(text)
    function_scopes = _javascript_function_scopes(text)
    assignment_events = tuple(
        event
        for event in _javascript_assignment_events(text)
        if not any(anchor <= event[0] < start for start, _, _, anchor, _ in function_scopes)
    )
    quoted_mapping_matches: list[tuple[int, re.Match[str]]] = []
    for match in JAVASCRIPT_MAPPING_REFERENCE.finditer(text):
        if not match.group("name_quote"):
            continue
        colon = text.find(":", match.end("name"), match.start("reference"))
        if (
            colon >= 0
            and syntax[colon : colon + 1] == ":"
            and syntax[match.start("reference") : match.end("reference")]
            == match.group("reference")
        ):
            quoted_mapping_matches.append((match.start(), match))
    quoted_bracket_matches: list[tuple[int, re.Match[str]]] = []
    for match in JAVASCRIPT_BRACKET_REFERENCE.finditer(text):
        equals = text.find("=", match.end("name"), match.start("reference"))
        if (
            equals >= 0
            and syntax[equals : equals + 1] == "="
            and syntax[match.start("reference") : match.end("reference")]
            == match.group("reference")
        ):
            quoted_bracket_matches.append((match.start(), match))
    sink_matches = sorted(
        tuple(
            (match.start(), match)
            for pattern in (
                JAVASCRIPT_MAPPING_REFERENCE,
                JAVASCRIPT_BRACKET_REFERENCE,
                JAVASCRIPT_NAMED_REFERENCE,
            )
            for match in pattern.finditer(syntax)
        )
        + tuple(
            (match.start(), ("static-key", match))
            for pattern in (
                JAVASCRIPT_COMPUTED_STATIC_KEY_REFERENCE,
                JAVASCRIPT_SETTER_STATIC_KEY_REFERENCE,
            )
            for match in pattern.finditer(text)
            if syntax[match.start() : match.start() + 1].strip()
            and syntax[match.start("reference") : match.end("reference")]
            == match.group("reference")
        )
        + tuple(quoted_mapping_matches)
        + tuple(quoted_bracket_matches),
        key=lambda item: item[0],
    )
    catch_bindings = _javascript_catch_bindings(text)
    lexical_declaration_positions = (
        event[0]
        for event in assignment_events
        if event[2].rsplit("-", 1)[-1] in {"const", "let"}
    )
    brace_scopes = tuple(
        sorted(
            {
                *_javascript_brace_scopes(text, lexical_declaration_positions),
                *(scope for scope, _ in _javascript_for_lexical_scopes(text)),
                *(scope for scope, _ in catch_bindings),
            },
            key=lambda item: (item[0], -item[1]),
        )
    )
    conditional_scopes = _javascript_conditional_scopes(text)
    function_ids = {
        ("function", start, end): (parameters, anchor, parameter_source)
        for start, end, parameters, anchor, parameter_source in function_scopes
    }
    block_ids = {("block", start, end) for start, end in brace_scopes}
    scope_ids = set(function_ids) | block_ids

    def interval_lookup(
        candidates: Iterable[tuple[str, int, int]],
        positions: Iterable[int],
    ) -> dict[int, tuple[str, int, int] | None]:
        ordered_scopes = sorted(candidates, key=lambda scope: (scope[1], -scope[2]))
        ordered_positions = sorted(set(positions))
        active: list[tuple[int, int, int, tuple[str, int, int]]] = []
        cursor = 0
        found: dict[int, tuple[str, int, int] | None] = {}
        for position in ordered_positions:
            while cursor < len(ordered_scopes) and ordered_scopes[cursor][1] <= position:
                scope = ordered_scopes[cursor]
                heapq.heappush(
                    active,
                    (-scope[1], scope[2], 0 if scope[0] == "block" else 1, scope),
                )
                cursor += 1
            while active and active[0][1] <= position:
                heapq.heappop(active)
            found[position] = active[0][3] if active else None
        return found

    parents: dict[tuple[str, int, int], tuple[str, int, int] | None] = {}
    functions_by_range = {(scope[1], scope[2]): scope for scope in function_ids}
    parent_positions = {
        scope: anchor for scope, (_, anchor, _) in function_ids.items()
    }
    parent_positions.update(
        {
            scope: scope[1] - 1
            for scope in block_ids
            if (scope[1], scope[2]) not in functions_by_range
        }
    )
    parent_at = interval_lookup(scope_ids, parent_positions.values())
    for scope, (_, anchor, _) in function_ids.items():
        parents[scope] = parent_at.get(anchor)
    for scope in block_ids:
        same_function = functions_by_range.get((scope[1], scope[2]))
        parents[scope] = (
            same_function
            if same_function is not None
            else parent_at.get(scope[1] - 1)
        )

    query_positions = [event[0] for event in assignment_events]
    query_positions.extend(start for start, _ in sink_matches)
    functions_at = interval_lookup(function_ids, query_positions)
    blocks_at = interval_lookup(block_ids, query_positions)

    def function_at(position: int) -> tuple[str, int, int] | None:
        return functions_at.get(position)

    def lexical_scope_at(position: int) -> tuple[str, int, int] | None:
        block = blocks_at.get(position)
        return block if block is not None else function_at(position)

    @lru_cache(maxsize=None)
    def scope_chain(position: int) -> tuple[tuple[str, int, int] | None, ...]:
        chain: list[tuple[str, int, int] | None] = []
        scope = lexical_scope_at(position)
        seen: set[tuple[str, int, int]] = set()
        while scope is not None and scope not in seen:
            seen.add(scope)
            chain.append(scope)
            scope = parents.get(scope)
        chain.append(None)
        return tuple(chain)

    scope_bindings: dict[tuple[str, int, int] | None, dict[str, str | None]] = {
        None: {}
    }
    for scope in scope_ids:
        scope_bindings[scope] = {}
    for scope, (parameters, _, _) in function_ids.items():
        scope_bindings[scope].update({name: None for name in parameters})
    for (start, end), names in catch_bindings:
        catch_scope = ("block", start, end)
        if catch_scope in scope_bindings:
            scope_bindings[catch_scope].update({name: None for name in names})

    event_scopes: list[dict[str, tuple[str, int, int] | None]] = []
    for start, _, kind, target, _ in assignment_events:
        names = (
            _javascript_destructuring_target_names(target)
            if target[:1] in "[{"
            else (target,)
        )
        declaration_kind = kind.rsplit("-", 1)[-1]
        if declaration_kind in {"const", "let"}:
            declaration_scope = blocks_at.get(start) or function_at(start)
        elif declaration_kind == "var":
            declaration_scope = function_at(start)
        else:
            declaration_scope = None
        mapping: dict[str, tuple[str, int, int] | None] = {}
        if kind != "assign":
            for name in names:
                mapping[name] = declaration_scope
                scope_bindings[declaration_scope][name] = None
        event_scopes.append(mapping)

    # Resolve ordinary writes after all lexical declarations are known. A write
    # without a declaration in the current execution scope is treated as local
    # to that function/module, matching the scanner's conservative shadowing
    # contract without mutating an enclosing closure during static analysis.
    for index, event in enumerate(assignment_events):
        start, _, kind, target, _ = event
        if kind != "assign":
            continue
        execution_scope = function_at(start)
        names = (
            _javascript_destructuring_target_names(target)
            if target[:1] in "[{"
            else (target,)
        )
        for name in names:
            selected: tuple[str, int, int] | None = None
            for scope in scope_chain(start):
                if name in scope_bindings[scope]:
                    selected = scope
                    break
                if scope == execution_scope:
                    break
            if selected is None:
                selected = execution_scope
                scope_bindings[selected][name] = None
            event_scopes[index][name] = selected

    def visible_bindings(position: int, expression: str) -> dict[str, str]:
        wanted = set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", expression))
        visible: dict[str, str] = {}
        shadowed: set[str] = set()
        for scope in scope_chain(position):
            for name in wanted - shadowed:
                if name not in scope_bindings[scope]:
                    continue
                value = scope_bindings[scope][name]
                if name in shadowed:
                    continue
                shadowed.add(name)
                if value is not None:
                    visible[name] = value
        return visible

    timeline_by_function: dict[
        tuple[str, int, int] | None,
        list[tuple[int, int, int, object]],
    ] = {None: []}
    for index, event in enumerate(assignment_events):
        timeline_by_function.setdefault(function_at(event[0]), []).append(
            (event[0], 0, index, event)
        )
    for start, match in sink_matches:
        timeline_by_function.setdefault(function_at(start), []).append((start, 1, -1, match))
    for timeline in timeline_by_function.values():
        timeline.sort(key=lambda item: (item[0], item[1]))

    child_functions: dict[
        tuple[str, int, int] | None,
        list[tuple[str, int, int]],
    ] = {}
    for scope in function_ids:
        parent = parents.get(scope)
        while parent is not None and parent[0] != "function":
            parent = parents.get(parent)
        child_functions.setdefault(parent, []).append(scope)
    for children in child_functions.values():
        children.sort(key=lambda scope: scope[1])

    security_views: list[str] = []
    configured_views: list[str] = []

    def record_static_value(name: str, value: str) -> None:
        security_views.append(value)
        if (
            len(value.strip()) >= 4
            and _is_sensitive_config_name(name)
            and (
                not _is_generic_sensitive_config_name(name)
                or not _generic_python_key_value_is_semantic(name, value)
            )
            and not _configured_value_is_placeholder(value)
            and not _structured_value_is_reference(value)
        ):
            configured_views.append(f"{name}=static-javascript-credential")

    def initialize_parameter_defaults(scope: tuple[str, int, int]) -> None:
        _, _, parameters = function_ids[scope]
        for target, expression in _javascript_parameter_defaults(parameters):
            wanted = set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", expression))
            bindings: dict[str, str] = {}
            shadowed: set[str] = set()
            parameter_scope: tuple[str, int, int] | None = scope
            while True:
                for name in wanted - shadowed:
                    if name not in scope_bindings[parameter_scope]:
                        continue
                    value = scope_bindings[parameter_scope][name]
                    shadowed.add(name)
                    if value is not None:
                        bindings[name] = value
                if parameter_scope is None:
                    break
                parameter_scope = parents.get(parameter_scope)
            for name, value in (
                _javascript_destructured_values(target, expression, bindings)
                if target[:1] in "[{"
                else ((target, _javascript_static_expression(expression, bindings)),)
            ):
                if value is not None:
                    scope_bindings[scope][name] = value
                    record_static_value(name, value)

    def analyze(execution_scope: tuple[str, int, int] | None) -> None:
        if execution_scope is not None:
            initialize_parameter_defaults(execution_scope)
        for position, item_kind, event_index, payload in timeline_by_function.get(
            execution_scope, ()
        ):
            if item_kind == 0:
                _, _, event_kind, target, expression = payload
                bindings = visible_bindings(position, (expression or "") + target)
                values = (
                    _javascript_for_iteration_values(
                        target,
                        expression or "",
                        event_kind.split("-", 2)[1],
                        bindings,
                    )
                    if event_kind.startswith("for-")
                    else
                    _javascript_destructured_values(target, expression or "", bindings)
                    if target[:1] in "[{"
                    else ((target, _javascript_static_expression(expression, bindings)),)
                    if expression is not None
                    else ((target, None),)
                )
                conditional = any(
                    start <= position < end for start, end in conditional_scopes
                )
                for name, value in values:
                    binding_scope = event_scopes[event_index].get(name, execution_scope)
                    previous = scope_bindings[binding_scope].get(name)
                    if value is None:
                        if not conditional:
                            scope_bindings[binding_scope][name] = None
                        continue
                    scope_bindings[binding_scope][name] = (
                        _prefer_static_security_value(previous, value)
                        if conditional and previous is not None
                        else value
                    )
                    record_static_value(name, value)
                continue
            if isinstance(payload, tuple):
                _, match = payload
                reference = match.group("reference")
                key_expression = match.group("name_expression")
                bindings = visible_bindings(position, f"{reference} {key_expression}")
                literal = bindings.get(reference)
                name = _javascript_static_expression(key_expression, bindings)
            else:
                match = payload
                reference = match.group("reference")
                literal = visible_bindings(position, reference).get(reference)
                name = match.group("name")
            if (
                name is not None
                and
                literal is not None
                and len(literal.strip()) >= 4
                and _is_sensitive_config_name(name)
                and (
                    not _is_generic_sensitive_config_name(name)
                    or not _generic_python_key_value_is_semantic(name, literal)
                )
                and not _configured_value_is_placeholder(literal)
                and not _structured_value_is_reference(literal)
            ):
                configured_views.append(f"{name}=static-javascript-credential")
        for child in child_functions.get(execution_scope, ()):
            analyze(child)

    analyze(None)
    return (
        {name: value for name, value in scope_bindings[None].items() if value is not None},
        tuple(dict.fromkeys(security_views)),
        tuple(dict.fromkeys(configured_views)),
    )


def _javascript_static_bindings(text: str) -> dict[str, str]:
    return _javascript_static_analysis(text)[0]


def _javascript_static_security_views(text: str) -> tuple[str, ...]:
    return _javascript_static_analysis(text)[1]


def _javascript_static_configured_views(text: str) -> tuple[str, ...]:
    return _javascript_static_analysis(text)[2]


def _python_call_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _python_call_path(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _resolve_python_call_path(path: str, aliases: dict[str, str]) -> str:
    resolved = path
    for _ in range(8):
        head, separator, tail = resolved.partition(".")
        replacement = aliases.get(head)
        if replacement is None:
            break
        candidate = replacement + (separator + tail if separator else "")
        if candidate == resolved:
            break
        resolved = candidate
    return resolved


def _python_call_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".", 1)[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name != "*":
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    for _ in range(8):
        changed = False
        for node in assignments:
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            path = _python_call_path(node.value)
            if not path:
                continue
            resolved = _resolve_python_call_path(path, aliases)
            if aliases.get(node.targets[0].id) != resolved:
                aliases[node.targets[0].id] = resolved
                changed = True
        if not changed:
            break
    return aliases


def _python_call_alias_snapshots(tree: ast.AST) -> dict[int, dict[str, str]]:
    """Resolve aliases at each call site so later rebindings cannot hide an earlier sink."""
    events: list[tuple[int, int, int, ast.AST]] = []
    for node in ast.walk(tree):
        position = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            events.append((*position, 0, node))
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) for target in node.targets
        ):
            events.append((*position, 1, node))
        elif isinstance(node, ast.Call):
            events.append((*position, 2, node))

    aliases: dict[str, str] = {}
    snapshots: dict[int, dict[str, str]] = {}
    for _, _, _, node in sorted(events, key=lambda event: event[:3]):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".", 1)[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name != "*":
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
        elif isinstance(node, ast.Assign):
            path = _python_call_path(node.value)
            resolved = _resolve_python_call_path(path, aliases) if path else ""
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                existing = aliases.get(target.id, "")
                if _python_path_is_sensitive_setter(
                    existing
                ) and not _python_path_is_sensitive_setter(resolved):
                    continue
                if resolved:
                    aliases[target.id] = resolved
                else:
                    aliases.pop(target.id, None)
        elif isinstance(node, ast.Call):
            snapshots[id(node)] = dict(aliases)
    return snapshots


def _python_path_is_sensitive_setter(path: str) -> bool:
    folded = path.casefold()
    if folded in {"os.putenv", "putenv", "os.setenv", "setenv", "set_key"}:
        return True
    if folded.endswith((".putenv", ".setenv", ".set_key")):
        return True
    if folded.endswith(".setdefault"):
        return folded.rsplit(".", 2)[-2] in {
            "config",
            "env",
            "environ",
            "headers",
            "settings",
        }
    if folded.endswith(".set"):
        return folded.rsplit(".", 2)[-2] in {
            "config",
            "configuration",
            "env",
            "headers",
            "options",
            "settings",
        }
    return False


def _python_target_has_config_context(target: ast.AST) -> bool:
    if not isinstance(target, (ast.Attribute, ast.Subscript)):
        return False
    path = _python_call_path(target.value).casefold()
    return any(
        part
        in {
            "config",
            "configuration",
            "credentials",
            "env",
            "environ",
            "headers",
            "secrets",
            "settings",
        }
        for part in path.split(".")
    )


def _is_generic_sensitive_config_name(value: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", value.casefold()) in {
        "auth",
        "authorization",
        "cookie",
        "key",
        "password",
        "secret",
        "token",
    }


def _generic_python_key_value_is_semantic(name: str, literal: str) -> bool:
    if not _is_generic_sensitive_config_name(name):
        return False
    semantic_suffixes = {
        "attribute",
        "column",
        "description",
        "field",
        "format",
        "id",
        "index",
        "kind",
        "label",
        "method",
        "metric",
        "name",
        "path",
        "policy",
        "property",
        "role",
        "status",
        "strategy",
        "title",
        "type",
    }
    if literal.casefold() in semantic_suffixes:
        return True
    if any(character.isdigit() for character in literal) or len(literal) > 64:
        return False
    separated = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", literal)
    words = [word.casefold() for word in re.split(r"[_-]+", separated) if word]
    semantic_components = semantic_suffixes | {
        "access",
        "account",
        "agent",
        "analysis",
        "artifact",
        "auth",
        "authorization",
        "claim",
        "client",
        "customer",
        "credential",
        "cookie",
        "dataset",
        "display",
        "document",
        "event",
        "experiment",
        "feature",
        "finding",
        "group",
        "job",
        "key",
        "model",
        "object",
        "organization",
        "output",
        "password",
        "project",
        "provider",
        "primary",
        "record",
        "request",
        "research",
        "result",
        "run",
        "schema",
        "secret",
        "session",
        "source",
        "stage",
        "task",
        "team",
        "tenant",
        "tool",
        "token",
        "trace",
        "user",
        "version",
        "workspace",
    }
    return (
        2 <= len(words) <= 4
        and all(word in semantic_components for word in words)
        and words[-1] in semantic_suffixes
    )


def _python_call_static_credentials(
    node: ast.Call,
    aliases: dict[str, str] | None = None,
    bindings: dict[str, str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Recover literal credentials passed to common environment/config setters."""
    path = _resolve_python_call_path(_python_call_path(node.func), aliases or {}).casefold()
    pairs: list[tuple[ast.AST, ast.AST]] = []
    keywords = {item.arg.casefold(): item.value for item in node.keywords if item.arg is not None}
    if path in {"os.putenv", "putenv"} and len(node.args) >= 2:
        pairs.append((node.args[0], node.args[1]))
    elif path in {"os.putenv", "putenv"} and {"key", "value"} <= keywords.keys():
        pairs.append((keywords["key"], keywords["value"]))
    elif path.endswith(".setdefault"):
        receiver = path.rsplit(".", 1)[0].rsplit(".", 1)[-1]
        if receiver in {"config", "env", "environ", "headers", "settings"}:
            if len(node.args) >= 2:
                pairs.append((node.args[0], node.args[1]))
            elif {"key", "default"} <= keywords.keys():
                pairs.append((keywords["key"], keywords["default"]))
    elif path == "set_key" or path.endswith(".set_key"):
        if len(node.args) >= 3:
            pairs.append((node.args[1], node.args[2]))
        else:
            name_node = keywords.get("key_to_set") or keywords.get("key") or keywords.get("name")
            value_node = keywords.get("value_to_set") or keywords.get("value")
            if name_node is not None and value_node is not None:
                pairs.append((name_node, value_node))
    elif path.endswith(".set"):
        receiver = path.rsplit(".", 1)[0].rsplit(".", 1)[-1]
        if receiver in {"config", "configuration", "env", "headers", "options", "settings"}:
            if len(node.args) >= 2:
                pairs.append((node.args[0], node.args[1]))
            if len(node.args) >= 3:
                pairs.append((node.args[-2], node.args[-1]))
            name_node = keywords.get("option") or keywords.get("key") or keywords.get("name")
            value_node = keywords.get("value")
            if name_node is not None and value_node is not None:
                pairs.append((name_node, value_node))

    recovered: list[tuple[str, str]] = []
    for name_node, value_node in pairs:
        name = _static_python_security_text(name_node, bindings)
        literal = _static_python_security_text(value_node, bindings)
        if name is not None and literal is not None:
            recovered.append((name, literal))
    return tuple(dict.fromkeys(recovered))


def _python_ast_configured_views(text: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, TypeError, ValueError):
        return ()
    alias_snapshots = _python_call_alias_snapshots(tree)
    binding_snapshots = _python_flow_binding_snapshots(tree)
    reconstructed: list[str] = []
    for node in ast.walk(tree):
        bindings = binding_snapshots.get(id(node), {})
        value: ast.AST | None = None
        targets: tuple[ast.AST, ...] = ()
        if isinstance(node, ast.Assign):
            value = node.value
            targets = tuple(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            value = node.value
            targets = (node.target,)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            value = node.value
            targets = (node,)
        if value is not None:
            literal = _static_python_security_text(value, bindings)
            if (
                literal is not None
                and len(literal) >= 4
                and not _structured_value_is_reference(literal)
            ):
                if _contains_configured_credential(literal):
                    reconstructed.append(literal)
                for target in targets:
                    names = (
                        (node.arg,)
                        if isinstance(node, ast.keyword) and node.arg is not None
                        else _assignment_target_names(target)
                    )
                    for name in names:
                        if (
                            _is_sensitive_config_name(name)
                            and (
                                not _is_generic_sensitive_config_name(name)
                                or _python_target_has_config_context(target)
                                or not _generic_python_key_value_is_semantic(name, literal)
                            )
                            and not _configured_value_is_placeholder(literal)
                        ):
                            reconstructed.append(f"{name}=static-python-credential")

        if isinstance(node, ast.Dict):
            for key, item_value in zip(node.keys, node.values, strict=True):
                if key is None:
                    continue
                name = _static_python_security_text(key, bindings)
                literal = _static_python_security_text(item_value, bindings)
                if (
                    name is not None
                    and literal is not None
                    and len(literal) >= 4
                    and not _structured_value_is_reference(literal)
                    and _is_sensitive_config_name(name)
                    and (
                        not _is_generic_sensitive_config_name(name)
                        or not _generic_python_key_value_is_semantic(name, literal)
                    )
                    and not _configured_value_is_placeholder(literal)
                ):
                    reconstructed.append(f"{name}=static-python-credential")
        if isinstance(node, ast.Call):
            for name, literal in _python_call_static_credentials(
                node,
                alias_snapshots.get(id(node), {}),
                bindings,
            ):
                if (
                    len(literal.strip()) >= 4
                    and not _structured_value_is_reference(literal)
                    and _is_sensitive_config_name(name)
                    and not _configured_value_is_placeholder(literal)
                ):
                    reconstructed.append(f"{name}=static-python-credential")
    return tuple(dict.fromkeys(reconstructed))


def _python_ast_security_views(text: str) -> tuple[str, ...]:
    """Reconstruct static Python strings before applying high-confidence signatures."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, TypeError, ValueError):
        return ()
    binding_snapshots = _python_flow_binding_snapshots(tree)
    reconstructed: list[str] = []
    for node in ast.walk(tree):
        bindings = binding_snapshots.get(id(node), {})
        candidates: tuple[ast.AST, ...] = ()
        if isinstance(node, ast.Assign):
            candidates = (node.value,)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            candidates = (node.value,)
        elif isinstance(node, ast.keyword):
            candidates = (node.value,)
        elif isinstance(node, ast.Dict):
            candidates = tuple(node.values)
        elif isinstance(node, ast.Call):
            candidates = tuple(node.args) + tuple(item.value for item in node.keywords)
        elif isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            candidates = tuple(node.elts)
        elif isinstance(node, (ast.BinOp, ast.JoinedStr)):
            candidates = (node,)
        for candidate in candidates:
            literal = _static_python_text(candidate, bindings)
            if literal is None:
                extended = _static_python_security_text(candidate, bindings)
                if extended is not None and any(
                    code in STATIC_RECONSTRUCTED_SECRET_CODES and pattern.search(extended)
                    for code, pattern in SECRET_PATTERNS
                ):
                    literal = extended
            if literal is not None and len(literal) >= 4:
                reconstructed.append(literal)
    return tuple(dict.fromkeys(reconstructed))


def _python_reference_assignment_spans(text: str) -> tuple[tuple[int, int, str | None], ...]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, TypeError, ValueError):
        return ()
    line_offsets = [0]
    line_offsets.extend(match.end() for match in re.finditer(r"\n", text))
    spans: list[tuple[int, int, str | None]] = []
    for node in ast.walk(tree):
        value: ast.AST | None = None
        targets: tuple[ast.AST, ...] = ()
        names: tuple[str, ...] = ()
        wildcard_name = False
        if isinstance(node, ast.Assign):
            value = node.value
            targets = tuple(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            value = node.value
            targets = (node.target,)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            value = node.value
            names = (node.arg,)
            targets = (node,)
        elif isinstance(node, ast.DictComp):
            value = node.value
            targets = (node.key,)
            wildcard_name = True
        elif isinstance(node, ast.Dict):
            for key, item_value in zip(node.keys, node.values, strict=True):
                if key is None or isinstance(item_value, (ast.Constant, ast.JoinedStr)):
                    continue
                key_start = _ast_offset(text, line_offsets, key.lineno, key.col_offset)
                value_start = _ast_offset(
                    text, line_offsets, item_value.lineno, item_value.col_offset
                )
                spans.append((key_start, value_start, None))
            continue
        if value is None or isinstance(value, (ast.Constant, ast.JoinedStr)):
            continue
        value_start = _ast_offset(text, line_offsets, value.lineno, value.col_offset)
        for target in targets:
            target_start = _ast_offset(text, line_offsets, target.lineno, target.col_offset)
            target_names = names or _assignment_target_names(target)
            if wildcard_name:
                spans.append((target_start, value_start, None))
            else:
                spans.extend((target_start, value_start, name.casefold()) for name in target_names)
    return tuple(spans)


def _match_is_python_reference(
    match: re.Match[str],
    text: str,
    source_path: Path | None,
    spans: tuple[tuple[int, int, str | None], ...] | None,
) -> tuple[bool, tuple[tuple[int, int, str | None], ...]]:
    resolved = spans or ()
    if source_path is None or source_path.suffix.casefold() != ".py":
        return False, resolved
    if spans is None:
        resolved = _python_reference_assignment_spans(text)
    start = match.start("name")
    end = match.end()
    name = match.group("name").casefold()
    return (
        any(
            span_start <= start < value_start <= end
            and (
                expected_name is None or expected_name == name or name.endswith("." + expected_name)
            )
            for span_start, value_start, expected_name in resolved
        ),
        resolved,
    )


def _match_is_k8s_reference_key(match: re.Match[str], text: str) -> bool:
    if re.sub(r"[^a-z0-9]", "", match.group("name").casefold()) != "key":
        return False
    line_start = text.rfind("\n", 0, match.start("name")) + 1
    current_line = text[line_start : match.start("name")]
    current_indent = len(current_line.expandtabs(8)) - len(current_line.lstrip().expandtabs(8))
    if current_indent == 0:
        return False
    for line in reversed(text[:line_start].splitlines()):
        if not line.strip():
            continue
        indent = len(line.expandtabs(8)) - len(line.lstrip().expandtabs(8))
        if indent < current_indent:
            return (
                re.fullmatch(r"(?:secretKeyRef|configMapKeyRef)[ \t]*:", line.strip(), re.I)
                is not None
            )
    return False


def _contains_configured_credential(text: str, *, source_path: Path | None = None) -> bool:
    if any(
        not _configured_value_is_placeholder(
            match.group("quoted_credential") or match.group("credential") or ""
        )
        for match in AUTHORIZATION_CREDENTIAL.finditer(text)
    ):
        return True
    structured_reference_spans: list[tuple[int, int]] = []
    for pattern in STRUCTURED_CREDENTIAL_ASSIGNMENTS:
        if (
            pattern is INLINE_MAPPING_CREDENTIAL_ASSIGNMENT
            and source_path is not None
            and source_path.suffix.casefold() == ".py"
        ):
            # Python mappings are parsed by _python_ast_configured_views. Scanning
            # their source text would mistake ordinary dynamic mappings and
            # comprehensions for static credentials.
            continue
        for match in pattern.finditer(text):
            value = match.group("value").strip().rstrip(",/>")
            was_quoted = value[:1] in {'"', "'", "`"} and value[-1:] == value[:1]
            if was_quoted:
                value = value[1:-1].strip()
            is_reference = _structured_value_is_reference(value)
            if (
                not is_reference
                and pattern is INLINE_MAPPING_CREDENTIAL_ASSIGNMENT
                and source_path is not None
                and source_path.suffix.casefold()
                in {".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
                and not was_quoted
                and re.fullmatch(
                    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\??\.[A-Za-z_$][A-Za-z0-9_$]*)*",
                    value,
                )
            ):
                is_reference = True
            bare_authorization_scheme = re.sub(
                r"[^a-z0-9]", "", match.group("name").casefold()
            ) == "authorization" and re.sub(r"[^a-z0-9]", "", value.casefold()) in {
                "apikey",
                "basic",
                "bearer",
                "digest",
                "token",
            }
            package_lock_semver = (
                source_path is not None
                and source_path.name.casefold() == "package-lock.json"
                and re.sub(r"[^a-z0-9]", "", match.group("name").casefold()) == "pathkey"
                and re.fullmatch(r"[~^]?\d+(?:\.\d+){1,3}(?:-[0-9A-Za-z.-]+)?", value)
                is not None
            )
            if is_reference:
                structured_reference_spans.append((match.start(), match.end()))
            if (
                _is_sensitive_config_name(match.group("name"))
                and len(value) >= 4
                and not is_reference
                and not _configured_value_is_placeholder(value)
                and not bare_authorization_scheme
                and not package_lock_semver
            ):
                return True
    reference_spans: tuple[tuple[int, int, str | None], ...] | None = None
    for match in CONFIGURED_CREDENTIAL_ASSIGNMENT.finditer(text):
        if any(
            start <= match.start("name") and match.end() <= end
            for start, end in structured_reference_spans
        ):
            continue
        triple = match.group("triple_value")
        quoted = match.group("quoted_value")
        unquoted = match.group("unquoted_value")
        value = triple or quoted or unquoted or ""
        package_lock_semver = (
            source_path is not None
            and source_path.name.casefold() == "package-lock.json"
            and match.group("name").casefold() == "path-key"
            and re.fullmatch(r"[~^]?\d+(?:\.\d+){1,3}(?:-[0-9A-Za-z.-]+)?", value) is not None
        )
        k8s_reference_key = _match_is_k8s_reference_key(match, text)
        normalized_name = re.sub(r"[^a-z0-9]", "", match.group("name").casefold())
        generic_name = normalized_name in {
            "auth",
            "authorization",
            "cookie",
            "key",
            "password",
            "secret",
            "token",
        }
        python_source = source_path is not None and source_path.suffix.casefold() == ".py"
        generic_python_semantic = (
            python_source
            and generic_name
            and _generic_python_key_value_is_semantic(match.group("name"), value)
        )
        is_reference = False
        if unquoted is not None:
            is_reference, reference_spans = _match_is_python_reference(
                match, text, source_path, reference_spans
            )
        if (
            unquoted is not None
            and "\n" in match.group("gap")
            and source_path is not None
            and source_path.suffix.casefold() == ".py"
        ):
            continue
        if (
            _is_sensitive_config_name(match.group("name"))
            and (
                not generic_name
                or (python_source and not generic_python_semantic)
                or (
                    not python_source
                    and not any(
                        character.isalnum() or character == "_"
                        for character in text[
                            text.rfind("\n", 0, match.start("name")) + 1 : match.start("name")
                        ]
                    )
                )
            )
            and not _configured_value_is_placeholder(value)
            and not package_lock_semver
            and not k8s_reference_key
            and not (
                re.sub(r"[^a-z0-9]", "", match.group("name").casefold()) == "authorization"
                and re.sub(r"[^a-z0-9]", "", value.casefold())
                in {"apikey", "basic", "bearer", "digest", "token"}
            )
            and not is_reference
        ):
            return True
        javascript_source = (
            source_path is not None
            and source_path.suffix.casefold() in JAVASCRIPT_SUFFIXES
        )
        nested_path = source_path if unquoted is not None or javascript_source else None
        if ("=" in value or ":" in value) and _contains_configured_credential(
            value, source_path=nested_path
        ):
            return True
    return False


def _is_probably_text(raw: bytes) -> bool:
    """Allow path heuristics only on text-like bytes; secret signatures still scan all bytes."""
    if not raw or raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    sample = raw[:16_384]
    if b"\0" in sample:
        paired = sample[: len(sample) - (len(sample) % 2)]
        if paired:
            even_nulls = paired[0::2].count(0) / max(1, len(paired[0::2]))
            odd_nulls = paired[1::2].count(0) / max(1, len(paired[1::2]))
            if max(even_nulls, odd_nulls) >= 0.30 and min(even_nulls, odd_nulls) <= 0.05:
                return True
        return False
    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        printable = sum(byte in b"\t\n\r" or 32 <= byte <= 126 for byte in sample)
        return printable / max(1, len(sample)) >= 0.90
    controls = sum(ord(char) < 32 and char not in "\t\n\r" for char in decoded)
    return controls / max(1, len(decoded)) < 0.01


def check_versions() -> list[str]:
    errors = []
    app_version = _app_version()
    pyproject = tomllib.loads(_read("pyproject.toml"))
    package = _json("frontend/package.json")
    lock = _json("frontend/package-lock.json")
    cli = _read("vc.py")

    expected = {
        "pyproject.toml": pyproject["project"]["version"],
        "frontend/package.json": package["version"],
        "frontend/package-lock.json": lock["version"],
        "frontend/package-lock root": lock["packages"][""]["version"],
    }
    for source, version in expected.items():
        if version != app_version:
            errors.append(
                f"{source} version {version!r} does not match APP_VERSION {app_version!r}"
            )
    if package.get("engines", {}).get("node") != ">=22.18.0":
        errors.append("frontend/package.json must require Node >=22.18.0")
    if lock.get("packages", {}).get("", {}).get("engines", {}).get("node") != ">=22.18.0":
        errors.append("frontend/package-lock.json must preserve the Node >=22.18.0 floor")

    cli_tree = ast.parse(cli)
    imports_shared_version = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "backend.config"
        and any(alias.name == "APP_VERSION" for alias in node.names)
        for node in cli_tree.body
    )
    short = ".".join(app_version.split(".")[:2])
    if not imports_shared_version and f"v{short}" not in cli and app_version not in cli:
        errors.append("vc.py does not use or display the current app version")
    return errors


def check_lockfile_registry() -> list[str]:
    text = _read("frontend/package-lock.json")
    errors = []
    for name in sorted(FORBIDDEN_FRONTEND_LOCKFILES):
        if (ROOT / "frontend" / name).exists():
            errors.append(f"frontend/{name} can override the audited package-lock.json")
    if "registry.npmmirror.com" in text:
        errors.append("frontend/package-lock.json contains registry.npmmirror.com URLs")
    try:
        lock = json.loads(text)
        package = _json("frontend/package.json")
    except json.JSONDecodeError:
        return errors + ["frontend/package-lock.json is invalid JSON"]

    packages = lock.get("packages")
    if package.get("scripts") != EXPECTED_FRONTEND_SCRIPTS:
        errors.append(
            "frontend/package.json scripts must exactly match the audited executable gates"
        )
    root_package = packages.get("", {}) if isinstance(packages, dict) else {}
    for field in ("name", "version", "dependencies", "devDependencies", "engines"):
        if root_package.get(field) != package.get(field):
            errors.append(f"frontend/package-lock.json root {field} does not match package.json")
    if lock.get("lockfileVersion") != 3 or lock.get("requires") is not True:
        errors.append("frontend/package-lock.json must use lockfileVersion 3 with requires=true")
    if not isinstance(packages, dict):
        return errors + ["frontend/package-lock.json packages must be an object"]
    for name, metadata in packages.items():
        if not name:
            continue
        if not isinstance(metadata, dict):
            errors.append("frontend/package-lock.json contains invalid package metadata")
            continue
        resolved = metadata.get("resolved")
        integrity = metadata.get("integrity")
        try:
            parsed = urlsplit(resolved) if isinstance(resolved, str) else None
        except (TypeError, UnicodeError, ValueError):
            parsed = None
        if (
            parsed is None
            or parsed.scheme != "https"
            or parsed.netloc != "registry.npmjs.org"
            or not parsed.path.startswith("/")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            errors.append("frontend/package-lock.json contains a non-official resolved package URL")
        elif not _resolved_package_matches_lock_entry(name, metadata, parsed.path):
            errors.append(
                "frontend/package-lock.json resolved package name/version does not match its entry"
            )
        if not _valid_sha512_integrity(integrity):
            errors.append("frontend/package-lock.json package is missing a SHA-512 integrity pin")
    return errors


def _resolved_package_matches_lock_entry(
    entry_name: str, metadata: dict, resolved_path: str
) -> bool:
    marker = "node_modules/"
    if marker not in entry_name:
        return False
    package_name = entry_name.rsplit(marker, 1)[-1]
    version = metadata.get("version")
    if (
        not package_name
        or not isinstance(version, str)
        or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,127}", version)
    ):
        return False
    basename = package_name.rsplit("/", 1)[-1]
    expected_path = f"/{package_name}/-/{basename}-{version}.tgz"
    try:
        return unquote(resolved_path) == expected_path
    except (TypeError, UnicodeError, ValueError):
        return False


def _valid_sha512_integrity(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha512-"):
        return False
    try:
        digest = base64.b64decode(value.removeprefix("sha512-"), validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(digest) == 64


def check_sensitive_patterns() -> list[str]:
    try:
        before = _read_release_snapshots()
        tree_matches_index = _working_tree_matches_index()
        index_flags_safe = _index_flags_are_safe()
    except (OSError, RuntimeError, UnicodeError) as exc:
        return [f"tracked source snapshot failed closed: {type(exc).__name__}"]

    errors = []
    snapshots_match = before.get("index") == before.get("worktree")
    if not tree_matches_index or not snapshots_match:
        errors.append("tracked index and worktree differ; stage or revert changes before release")
    if not index_flags_safe:
        errors.append("tracked files must not use assume-unchanged or skip-worktree flags")

    skipped_parts = {part.casefold() for part in SKIP_DIRS}
    forbidden_paths = {path.as_posix().casefold() for path in FORBIDDEN_TRACKED_PATHS}
    for source, snapshot in before.items():
        for relative, raw in snapshot.items():
            folded_parts = tuple(part.casefold() for part in relative.parts)
            folded_path = relative.as_posix().casefold()
            path_views = _path_scan_views(relative)
            blocked_path_codes = {
                code
                for code, pattern in SECRET_PATTERNS
                if any(pattern.search(view) for view in path_views)
            }
            label = "<redacted-path>" if blocked_path_codes else relative.as_posix()
            for code in sorted(blocked_path_codes):
                errors.append(f"{source}: tracked path contains blocked pattern {code}")
            if (
                folded_path in forbidden_paths
                or any(part in skipped_parts for part in folded_parts)
                or (folded_parts and folded_parts[0] in {"data", "sessions"})
                or _is_private_tracked_path(relative)
            ):
                errors.append(f"{source}: tracked generated/private path is forbidden: {label}")
                continue
            text_like = _is_probably_text(raw)
            views = _scan_views(raw) if text_like else _binary_metadata_views(raw)
            binary_codes = frozenset() if text_like else _binary_pattern_candidates(views)
            signature_views = views
            if text_like and relative.suffix.casefold() == ".py":
                try:
                    python_text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    python_text = raw.decode("latin-1")
                signature_views = tuple(
                    dict.fromkeys(
                        (
                            *views,
                            *_python_ast_security_views(unicodedata.normalize("NFKC", python_text)),
                        )
                    )
                )
            elif text_like and relative.suffix.casefold() in JAVASCRIPT_SUFFIXES:
                try:
                    javascript_text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    javascript_text = raw.decode("latin-1")
                signature_views = tuple(
                    dict.fromkeys(
                        (
                            *views,
                            *_javascript_static_security_views(
                                unicodedata.normalize("NFKC", javascript_text)
                            ),
                        )
                    )
                )
            if text_like or _binary_may_contain_configured_credential(views):
                configured_views = (
                    _configured_credential_views(raw, relative, views)
                    if text_like
                    else tuple((view, relative) for view in views)
                )
                if any(
                    _contains_configured_credential(view, source_path=semantic_path)
                    for view, semantic_path in configured_views
                ):
                    errors.append(f"{source}:{label}: blocked pattern configured-api-key")
            for code, pattern in SECRET_PATTERNS:
                if not text_like and code not in binary_codes:
                    continue
                if any(pattern.search(view) for view in signature_views):
                    errors.append(f"{source}:{label}: blocked pattern {code}")

    try:
        after = _read_release_snapshots()
    except (OSError, RuntimeError, UnicodeError) as exc:
        errors.append(f"tracked source resnapshot failed closed: {type(exc).__name__}")
    else:
        if before != after:
            errors.append("tracked sources changed during release scan")
    return sorted(set(errors))


def _path_scan_views(relative: Path) -> tuple[str, ...]:
    value = relative.as_posix()
    views = [value, value.replace("/", "\\")]
    decoded = value
    for _ in range(3):
        candidate = unquote(decoded)
        if candidate == decoded:
            break
        decoded = candidate
        views.extend((decoded, decoded.replace("/", "\\")))
    return tuple(dict.fromkeys(views))


def _is_private_tracked_path(relative: Path) -> bool:
    name = relative.name.casefold()
    folded_path = relative.as_posix().casefold()
    private_env = name == ".env" or (name.startswith(".env.") and name != ".env.example")
    return (
        private_env
        or name in PRIVATE_TRACKED_NAMES
        or folded_path in PRIVATE_TRACKED_PATHS
        or any(folded_path.endswith(f"/{path}") for path in PRIVATE_TRACKED_PATHS)
        or any(name.endswith(suffix) for suffix in PRIVATE_TRACKED_SUFFIXES)
    )


def check_session_contract_docs() -> list[str]:
    combined = "\n".join(
        [
            _read("README.md"),
            _read("AGENTS.md"),
            _read("CLAUDE.md"),
            _read(".codex/skills/weiping-council/SKILL.md"),
        ]
    )
    missing = [field for field in sorted(SESSION_REQUIRED_FIELDS) if field not in combined]
    if missing:
        return [f"session artifact contract missing documented fields: {', '.join(missing)}"]
    return []


def check_tool_policy() -> list[str]:
    errors = []
    pyproject = tomllib.loads(_read("pyproject.toml"))
    tool = pyproject.get("tool", {})
    expected_ruff = {"line-length": 100, "lint": {"select": ["E4", "E7", "E9", "F"]}}
    if tool.get("ruff") != expected_ruff:
        errors.append("pyproject.toml must exactly pin the audited Ruff policy")
    if tool.get("pytest", {}).get("ini_options") != {"testpaths": ["tests"]}:
        errors.append("pyproject.toml must exactly pin the audited pytest policy")
    try:
        tracked = _tracked_paths()
    except (OSError, RuntimeError, UnicodeError):
        return errors + ["tracked test/lint configuration inventory could not be verified"]
    for relative in tracked:
        name = relative.name.casefold()
        if name in OVERRIDE_CONFIG_NAMES or (
            name == "pyproject.toml" and relative != Path("pyproject.toml")
        ):
            errors.append("tracked test/lint override configuration is forbidden")
    return errors


def check_ci_contract() -> list[str]:
    try:
        workflows = {
            path.as_posix()
            for path in _tracked_paths()
            if len(path.parts) >= 3
            and path.parts[0].casefold() == ".github"
            and path.parts[1].casefold() == "workflows"
        }
    except (OSError, RuntimeError, UnicodeError):
        return ["tracked CI workflow inventory could not be verified"]
    errors = []
    if workflows != {".github/workflows/ci.yml"}:
        errors.append("tracked CI workflow inventory must contain exactly ci.yml")
    return errors + _validate_ci_workflow(_read(".github/workflows/ci.yml"))


def _validate_ci_workflow(workflow: str) -> list[str]:
    errors: list[str] = []
    try:
        document = yaml.load(workflow, Loader=_UniqueSafeLoader)
    except (yaml.YAMLError, TypeError, ValueError):
        return ["CI workflow must be valid safe YAML"]
    if not isinstance(document, dict):
        return ["CI workflow root must be a mapping"]
    expected_root_fields = {"name", "on", "permissions", "concurrency", "jobs"}
    if set(document) != expected_root_fields:
        errors.append("CI workflow must contain exactly the audited root fields")
    if document.get("name") != "CI":
        errors.append("CI workflow name must be CI")
    if document.get("on") != {"push": None, "pull_request": None}:
        errors.append("CI triggers must contain exactly push and pull_request")
    if document.get("permissions") != {"contents": "read"}:
        errors.append("CI permissions must contain only contents: read")
    if document.get("concurrency") != {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": True,
    }:
        errors.append("CI concurrency must match the audited cancellation policy")
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != {"verify", "windows-smoke"}:
        errors.append("CI jobs must contain exactly verify and windows-smoke")
        return errors
    all_steps: list[dict] = []
    for name, expected_runner in (("verify", "ubuntu-latest"), ("windows-smoke", "windows-latest")):
        job = jobs[name]
        if not isinstance(job, dict):
            errors.append(f"CI {name} job must be a mapping")
            continue
        if set(job) - {"runs-on", "timeout-minutes", "steps"}:
            errors.append(f"CI {name} job contains unsupported privilege-bearing keys")
        if job.get("runs-on") != expected_runner:
            errors.append(f"CI {name} job must use {expected_runner}")
        steps = job.get("steps")
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            errors.append(f"CI {name} steps must be a list of mappings")
            continue
        all_steps.extend(steps)

    expected_job_digests = {
        "verify": "78ef851fbb19edc9b4d0ba3904679551fde3cddb8136dc491690b652235f1764",
        "windows-smoke": "37e0460d7200e33615a5cf4f84f39e8ad0b00d5aef426bf4b879ae7d3fadf7f1",
    }
    for name, expected_digest in expected_job_digests.items():
        encoded = json.dumps(
            jobs[name], sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != expected_digest:
            errors.append(f"CI {name} job must exactly match the audited job structure")

    action_steps = [step for step in all_steps if "uses" in step]
    if not all(isinstance(step.get("uses"), str) for step in action_steps):
        return errors + ["CI action references must be strings"]
    if Counter(step.get("uses") for step in action_steps) != ALLOWED_ACTIONS:
        errors.append("CI uses directives must exactly match the pinned official action allowlist")

    checkout_action = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    python_action = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    node_action = "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020"
    for step in action_steps:
        if set(step) - {"name", "uses", "with"}:
            errors.append("CI action step contains unsupported keys")
        action = step.get("uses")
        inputs = step.get("with")
        if not isinstance(inputs, dict):
            errors.append("every CI action step must use a with mapping")
            continue
        if action == checkout_action and inputs.get("persist-credentials") is not False:
            errors.append("every CI checkout must disable persisted credentials")
        if action == python_action and inputs.get("python-version") != "3.11":
            errors.append("CI setup-python must pin Python 3.11")
        if action == node_action and inputs.get("node-version") != "22.18.0":
            errors.append("CI setup-node must pin Node 22.18.0")
    active_run_lines = {
        line.strip()
        for step in all_steps
        if isinstance(step.get("run"), str)
        for line in step["run"].splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_commands = {
        'python -m pip install --upgrade "pip>=26.2.1" "setuptools>=84.0.0"',
        'python -m pip install -e ".[dev]"',
        "python -m pip check",
        "python -m pip_audit",
        "python -m pytest -q -p no:cacheprovider",
        "python -m ruff check .",
        "python scripts/release_scan.py",
        "npm ci",
        "npm run build",
        "npm test",
        "npm audit --audit-level=low --registry=https://registry.npmjs.org",
    }
    if not required_commands <= active_run_lines:
        errors.append("CI workflow is missing an exact required install or verification command")
    if re.search(r"\$\{\{\s*secrets\.", workflow, flags=re.IGNORECASE):
        errors.append("CI workflow must not reference repository secrets")
    return errors


def main() -> int:
    errors = []
    try:
        release_before = _read_release_snapshots()
    except (OSError, RuntimeError, UnicodeError) as exc:
        errors.append(f"release snapshot failed closed: {type(exc).__name__}")
        release_before = None
    for check in [
        check_versions,
        check_lockfile_registry,
        check_sensitive_patterns,
        check_session_contract_docs,
        check_tool_policy,
        check_ci_contract,
    ]:
        errors.extend(check())
    if release_before is not None:
        try:
            release_after = _read_release_snapshots()
            tree_matches_index = _working_tree_matches_index()
            index_flags_safe = _index_flags_are_safe()
        except (OSError, RuntimeError, UnicodeError) as exc:
            errors.append(f"release resnapshot failed closed: {type(exc).__name__}")
        else:
            if release_before != release_after:
                errors.append("tracked sources changed during the complete release gate")
            if not tree_matches_index or release_after.get("index") != release_after.get(
                "worktree"
            ):
                errors.append("tracked index and worktree differ after the complete release gate")
            if not index_flags_safe:
                errors.append(
                    "tracked files gained unsafe index visibility flags during release gate"
                )
    if errors:
        print("Release scan failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Release scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
