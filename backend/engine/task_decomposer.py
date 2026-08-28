"""
Task Decomposer: CrewAI-inspired hierarchical task breakdown.
Complex queries are split into sub-tasks, assigned to specialists,
executed in dependency order, then synthesized.
"""

import asyncio
from dataclasses import dataclass, field
from ..config import CouncilConfig, ModelConfig
from ..providers.router import ModelRouter, is_provider_error_result


@dataclass
class SubTask:
    id: int
    description: str
    assigned_to: str  # model id
    depends_on: list[int] = field(default_factory=list)
    result: str = ""
    status: str = "pending"  # pending, running, done, failed


@dataclass
class DecompositionResult:
    original_query: str
    subtasks: list[SubTask]
    synthesis: str
    was_decomposed: bool


class TaskDecomposer:
    """Breaks complex queries into sub-tasks and delegates to specialists."""

    def __init__(self, config: CouncilConfig, router: ModelRouter):
        self.config = config
        self.router = router
        self.decomposition_threshold = 0.6  # Only decompose if complexity > this

    async def process(
        self,
        query: str,
        difficulty: float,
        context: str = "",
    ) -> DecompositionResult:
        """Decompose if complex, otherwise return as single task."""
        if difficulty < self.decomposition_threshold:
            return DecompositionResult(
                original_query=query, subtasks=[], synthesis="", was_decomposed=False
            )

        # Step 1: Decompose into sub-tasks
        subtasks = await self._decompose(query, context)

        if len(subtasks) <= 1:
            return DecompositionResult(
                original_query=query, subtasks=subtasks, synthesis="", was_decomposed=False
            )

        # Step 2: Assign to specialists based on task content
        for task in subtasks:
            task.assigned_to = self._assign_specialist(task.description)

        # Step 3: Execute in dependency order
        await self._execute_tasks(query, subtasks, context)

        # Step 4: Synthesize results
        synthesis = await self._synthesize(query, subtasks, context)

        return DecompositionResult(
            original_query=query, subtasks=subtasks, synthesis=synthesis, was_decomposed=True
        )

    async def _decompose(self, query: str, context: str = "") -> list[SubTask]:
        """Use architect model to break query into sub-tasks."""
        architect = self._get_architect()
        prompt = f"""Break this complex query into 2-5 independent sub-tasks that can be answered separately and then combined.

QUERY: {query}

For each sub-task, provide:
- A clear, self-contained question
- Which sub-tasks it depends on (by number), or "none"

Format (one per line):
1. [question] | depends: none
2. [question] | depends: 1
3. [question] | depends: none

Only decompose if the query genuinely has multiple parts. If it's a single coherent question, respond with just:
1. [the original question] | depends: none"""

        response = await self.router.query(
            architect,
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            context=context,
        )

        subtasks = []
        for line in response.strip().split("\n"):
            if len(subtasks) >= 5:
                break
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            try:
                # Parse "1. [question] | depends: none"
                parts = line.split("|")
                desc = parts[0].split(".", 1)[1].strip() if "." in parts[0] else parts[0].strip()
                deps = []
                if len(parts) > 1 and "depends:" in parts[1]:
                    dep_str = parts[1].split("depends:")[1].strip()
                    if dep_str.lower() != "none":
                        candidates = [
                            int(d.strip()) - 1 for d in dep_str.split(",") if d.strip().isdigit()
                        ]
                        deps = sorted({dep for dep in candidates if 0 <= dep < len(subtasks)})
                subtasks.append(
                    SubTask(id=len(subtasks), description=desc, assigned_to="", depends_on=deps)
                )
            except (ValueError, IndexError):
                continue

        return subtasks if subtasks else [SubTask(id=0, description=query, assigned_to="")]

    def _assign_specialist(self, task_description: str) -> str:
        """Match task to best model based on keywords and roles."""
        task_lower = task_description.lower()

        # Keyword-based routing
        if any(kw in task_lower for kw in ["code", "implement", "algorithm", "function", "class"]):
            role = "implementer"
        elif any(kw in task_lower for kw in ["review", "evaluate", "compare", "critique"]):
            role = "reviewer"
        elif any(kw in task_lower for kw in ["research", "literature", "paper", "study"]):
            role = "architect"
        elif any(kw in task_lower for kw in ["translate", "chinese", "format", "convert"]):
            role = "bulk-worker"
        else:
            role = "coordinator"

        for m in self.config.models:
            if m.role == role:
                return m.id
        return self.config.models[0].id

    async def _execute_tasks(
        self,
        original_query: str,
        subtasks: list[SubTask],
        context: str = "",
    ):
        """Execute sub-tasks respecting dependencies, running ready tasks in parallel."""
        completed = set()

        while len(completed) < len(subtasks):
            ready = [
                t
                for t in subtasks
                if t.id not in completed and all(d in completed for d in t.depends_on)
            ]

            if not ready:
                break  # Circular dependency or error

            async def run_task(task: SubTask):
                task.status = "running"
                if any(subtasks[dependency].status == "failed" for dependency in task.depends_on):
                    task.result = "Skipped because a required dependency failed."
                    task.status = "failed"
                    return
                model = next(
                    (m for m in self.config.models if m.id == task.assigned_to),
                    self.config.models[0],
                )
                dependency_context = ""
                if task.depends_on:
                    deps_results = [
                        subtasks[d].result for d in task.depends_on if subtasks[d].result
                    ]
                    dependency_context = "\nContext from previous steps:\n" + "\n".join(
                        deps_results
                    )

                prompt = f"""Answer this specific sub-question as part of a larger query.

Original query: {original_query}
Your sub-task: {task.description}{dependency_context}

Provide a focused, thorough answer to your specific sub-task."""

                task.result = await self.router.query(
                    model,
                    [{"role": "user", "content": prompt}],
                    context=context,
                )
                task.status = "failed" if is_provider_error_result(task.result) else "done"

            await asyncio.gather(*[run_task(t) for t in ready])
            completed.update(t.id for t in ready)

    async def _synthesize(
        self,
        query: str,
        subtasks: list[SubTask],
        context: str = "",
    ) -> str:
        """Combine sub-task results into a coherent final answer."""
        architect = self._get_architect()
        parts = "\n\n".join(
            f"Sub-task {t.id + 1}: {t.description}\nStatus: {t.status}\nAnswer: {t.result}"
            for t in subtasks
        )

        prompt = f"""You decomposed this query into sub-tasks and got answers for each.
Now synthesize them into one coherent, comprehensive final answer.

ORIGINAL QUERY: {query}

SUB-TASK RESULTS:
{parts}

Produce a unified answer that integrates all sub-task results naturally.
Do not just concatenate them — synthesize into a flowing, complete response."""

        return await self.router.query(
            architect,
            [{"role": "user", "content": prompt}],
            context=context,
        )

    def _get_architect(self) -> ModelConfig:
        for m in self.config.models:
            if m.role == "architect":
                return m
        return self.config.models[0]
