"""agentmemory context loader for Weiping Council."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..runtime import (
    PUBLIC_REDACTED,
    agentmemory_auth_headers,
    merged_runtime_env,
    project_public_text,
)
from ..safe_json import sanitize_unicode_scalar


MAX_CONTEXT_SNIPPET_CHARS = 4_000
MAX_CONTEXT_CHARS = 12_000
MAX_CONTEXT_PROJECTS = 20
MAX_CONTEXT_RULES = 20


def _bounded_context_sections(sections: list[str]) -> str:
    """Fit complete context sections under one Unicode-scalar character budget."""
    safe_sections = [sanitize_unicode_scalar(section) for section in sections if section]
    if not safe_sections:
        return ""
    separator = "\n\n"
    remaining = MAX_CONTEXT_CHARS - len(separator) * (len(safe_sections) - 1)
    allocations = [0] * len(safe_sections)
    pending = set(range(len(safe_sections)))
    while pending:
        share = remaining // len(pending)
        fitting = [index for index in pending if len(safe_sections[index]) <= share]
        if fitting:
            for index in fitting:
                allocations[index] = len(safe_sections[index])
                remaining -= allocations[index]
                pending.remove(index)
            continue
        for offset, index in enumerate(sorted(pending)):
            allocations[index] = share + (1 if offset < remaining % len(pending) else 0)
        break
    return separator.join(
        section[: allocations[index]] for index, section in enumerate(safe_sections)
    )


@dataclass
class SharedMemoryContext:
    projects: list[dict] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    projects_available: bool = False
    rules_available: bool = False
    raw_summary: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_context_block(self) -> str:
        sections = []
        if self.raw_summary.strip():
            sections.append("=== Recalled Agentmemory Context ===\n" + self.raw_summary.strip())
        if self.projects:
            lines = ["=== Active Projects ==="]
            for project in self.projects:
                lines.append(
                    f"[P{project.get('priority', '?')}] "
                    f"{project.get('name', 'unknown')}: "
                    f"{project.get('direction', '')} | {project.get('status', '')[:60]}"
                )
            sections.append("\n".join(lines))
        if self.rules:
            sections.append(
                "=== Key Rules ===\n" + "\n".join(f"- {rule}" for rule in self.rules[:5])
            )
        return _bounded_context_sections(sections)

    def find_project(self, query: str) -> dict | None:
        q = query.lower()
        for project in self.projects:
            name = str(project.get("name", "")).lower()
            if name and (name in q or any(part in q for part in name.split())):
                return project
        return None


@dataclass
class AgentMemorySearchResult:
    snippets: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    projects_available: bool = False
    rules_available: bool = False
    warnings: list[str] = field(default_factory=list)


class AgentMemoryClient:
    """Small HTTP client for the active agentmemory service."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        dotenv_path: str | Path | None = None,
        secret: str | None = None,
    ):
        env = (
            merged_runtime_env(dotenv_path=dotenv_path)
            if base_url is None or secret is None
            else {}
        )
        if base_url is not None:
            configured_url = base_url
        elif "AGENTMEMORY_URL" in env:
            configured_url = env["AGENTMEMORY_URL"]
        else:
            configured_url = "http://localhost:3111"
        self.base_url = (
            configured_url.strip().rstrip("/") if isinstance(configured_url, str) else ""
        )
        configured_secret = env.get("AGENTMEMORY_SECRET", "") if secret is None else secret
        self._secret = configured_secret.strip() if isinstance(configured_secret, str) else ""
        self.timeout = timeout
        self.transport = transport

    def _auth_headers(self) -> dict[str, str]:
        return agentmemory_auth_headers(self.base_url, self._secret)

    def smart_search(self, query: str, limit: int = 5) -> list[str]:
        """Compatibility text-only view of a structured smart-search response."""
        return self.search_context(query=query, limit=limit).snippets

    def search_context(self, query: str, limit: int = 5) -> AgentMemorySearchResult:
        """Fetch full observations plus bounded project and lesson metadata."""
        with httpx.Client(
            timeout=self.timeout,
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = client.post(
                f"{self.base_url}/agentmemory/search",
                headers=self._auth_headers(),
                json={
                    "query": query,
                    "limit": limit,
                    "format": "full",
                },
            )
            response.raise_for_status()
            data = response.json()
            result = self._extract_context(data)
            self._load_project_metadata(client, result)
            self._load_rule_metadata(client, result)
        return result

    def health(self) -> dict:
        with httpx.Client(
            timeout=self.timeout,
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = client.get(
                f"{self.base_url}/agentmemory/health",
                headers=self._auth_headers(),
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _result_items(data) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("results") or data.get("memories") or data.get("items") or []
            return items if isinstance(items, list) else []
        return []

    def _extract_texts(self, data) -> list[str]:
        items = self._result_items(data)

        texts = []
        for item in items:
            if isinstance(item, str):
                raw_parts = [item]
            elif isinstance(item, dict):
                containers = [item]
                for container_field in ("observation", "memory"):
                    nested = item.get(container_field)
                    if isinstance(nested, dict):
                        containers.append(nested)
                raw_parts: list[str] = []
                for container in containers:
                    primary = next(
                        (
                            container.get(field_name)
                            for field_name in ("narrative", "content", "text", "summary")
                            if isinstance(container.get(field_name), str)
                            and container.get(field_name).strip()
                        ),
                        "",
                    )
                    if primary:
                        raw_parts.append(primary)
                    facts = container.get("facts", [])
                    if isinstance(facts, list):
                        raw_parts.extend(value for value in facts if isinstance(value, str))
            else:
                raw_parts = []
            safe_parts: list[str] = []
            for raw_part in raw_parts:
                for line in sanitize_unicode_scalar(raw_part).splitlines():
                    bounded = line.strip()[:MAX_CONTEXT_SNIPPET_CHARS]
                    projected = project_public_text(
                        bounded,
                        default="",
                        maximum=MAX_CONTEXT_SNIPPET_CHARS,
                    )
                    if projected:
                        safe_parts.append(projected)
            if safe_parts:
                texts.append("\n".join(safe_parts)[:MAX_CONTEXT_SNIPPET_CHARS])
        return texts

    @staticmethod
    def _structured_containers(data) -> list[dict]:
        containers = [data] if isinstance(data, dict) else []
        if isinstance(data, dict) and isinstance(data.get("context"), dict):
            containers.append(data["context"])
        for item in AgentMemoryClient._result_items(data):
            if not isinstance(item, dict):
                continue
            if "projects" in item or "rules" in item:
                containers.append(item)
            for container_field in ("context", "memory", "metadata", "observation"):
                nested = item.get(container_field)
                if not isinstance(nested, dict):
                    continue
                if "projects" in nested or "rules" in nested:
                    containers.append(nested)
                if isinstance(nested.get("context"), dict):
                    containers.append(nested["context"])
        return containers

    @staticmethod
    def _safe_project_name(value: object) -> str:
        if not isinstance(value, str):
            return ""
        basename = value.strip().replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        return project_public_text(basename, default="", maximum=128)

    def _load_project_metadata(
        self,
        client: httpx.Client,
        result: AgentMemorySearchResult,
    ) -> None:
        if result.projects_available:
            return
        try:
            response = client.get(
                f"{self.base_url}/agentmemory/sessions",
                headers=self._auth_headers(),
            )
            response.raise_for_status()
            payload = response.json()
            sessions = payload.get("sessions") if isinstance(payload, dict) else None
            if not isinstance(sessions, list):
                raise ValueError("agentmemory sessions response schema was invalid")
        except Exception as exc:
            result.warnings.append(
                f"agentmemory project metadata unavailable: {type(exc).__name__}"
            )
            return

        grouped: dict[str, dict[str, object]] = {}
        for session in sessions[:1_000]:
            if not isinstance(session, dict):
                continue
            name = self._safe_project_name(session.get("project"))
            status = session.get("status")
            if (
                not name
                or name == PUBLIC_REDACTED
                or status not in {"active", "completed", "abandoned"}
            ):
                continue
            record = grouped.setdefault(name, {"count": 0, "active": False, "status": status})
            record["count"] = int(record["count"]) + 1
            if status == "active":
                record["active"] = True
                record["status"] = "active"

        ordered = sorted(
            grouped.items(),
            key=lambda item: (
                not bool(item[1]["active"]),
                -int(item[1]["count"]),
                item[0].lower(),
            ),
        )
        result.projects = [
            {
                "priority": index,
                "name": name,
                "direction": f"{record['count']} recorded session(s)",
                "status": str(record["status"]),
            }
            for index, (name, record) in enumerate(
                ordered[:MAX_CONTEXT_PROJECTS],
                start=1,
            )
        ]
        result.projects_available = True

    def _load_rule_metadata(
        self,
        client: httpx.Client,
        result: AgentMemorySearchResult,
    ) -> None:
        if result.rules_available:
            return
        try:
            response = client.get(
                f"{self.base_url}/agentmemory/lessons",
                headers=self._auth_headers(),
                params={"limit": MAX_CONTEXT_RULES},
            )
            response.raise_for_status()
            payload = response.json()
            lessons = payload.get("lessons") if isinstance(payload, dict) else None
            if not isinstance(lessons, list):
                raise ValueError("agentmemory lessons response schema was invalid")
        except Exception as exc:
            result.warnings.append(f"agentmemory rule metadata unavailable: {type(exc).__name__}")
            return

        for lesson in lessons[:100]:
            content = lesson.get("content") if isinstance(lesson, dict) else None
            clean_content = (
                " ".join(sanitize_unicode_scalar(content).splitlines())
                if isinstance(content, str)
                else ""
            )
            projected = project_public_text(clean_content, default="", maximum=1_000)
            if (
                projected
                and projected != PUBLIC_REDACTED
                and projected not in result.rules
                and len(result.rules) < MAX_CONTEXT_RULES
            ):
                result.rules.append(projected)
        result.rules_available = True

    @staticmethod
    def _project_record(value: object) -> dict | None:
        if not isinstance(value, dict):
            return None
        name = project_public_text(value.get("name"), default="", maximum=128)
        if not name:
            return None
        priority = value.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100:
            return None
        return {
            "priority": priority,
            "name": name,
            "direction": project_public_text(value.get("direction", ""), maximum=1_000),
            "status": project_public_text(value.get("status", ""), maximum=1_000),
        }

    def _extract_context(self, data) -> AgentMemorySearchResult:
        result = AgentMemorySearchResult(snippets=self._extract_texts(data))
        for container in self._structured_containers(data):
            if "projects" in container:
                result.projects_available = True
                projects = container["projects"]
                if not isinstance(projects, list):
                    result.warnings.append("agentmemory structured projects field was invalid")
                else:
                    for value in projects[:100]:
                        projected = self._project_record(value)
                        if (
                            projected is not None
                            and projected not in result.projects
                            and len(result.projects) < MAX_CONTEXT_PROJECTS
                        ):
                            result.projects.append(projected)
            if "rules" in container:
                result.rules_available = True
                rules = container["rules"]
                if not isinstance(rules, list):
                    result.warnings.append("agentmemory structured rules field was invalid")
                else:
                    for value in rules[:100]:
                        projected = project_public_text(value, default="", maximum=1_000)
                        if (
                            projected
                            and projected != PUBLIC_REDACTED
                            and projected not in result.rules
                            and len(result.rules) < MAX_CONTEXT_RULES
                        ):
                            result.rules.append(projected)
        result.warnings = sorted(set(result.warnings))
        return result


def load_shared_memory(
    query: str = "active project context and durable rules",
    client: AgentMemoryClient | None = None,
) -> SharedMemoryContext:
    ctx = SharedMemoryContext()
    memory_client = client or AgentMemoryClient()
    if not memory_client.base_url:
        return ctx
    try:
        if hasattr(memory_client, "search_context"):
            recalled = memory_client.search_context(query=query, limit=5)
        else:
            recalled = AgentMemorySearchResult(
                snippets=memory_client.smart_search(query=query, limit=5)
            )
    except Exception as exc:
        ctx.warnings.append(f"agentmemory context unavailable: {type(exc).__name__}")
        return ctx

    ctx.raw_summary = sanitize_unicode_scalar("\n".join(recalled.snippets[:5]))[:MAX_CONTEXT_CHARS]
    ctx.projects = recalled.projects
    ctx.rules = recalled.rules
    ctx.projects_available = recalled.projects_available
    ctx.rules_available = recalled.rules_available
    ctx.warnings.extend(recalled.warnings)
    return ctx
