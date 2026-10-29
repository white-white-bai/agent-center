import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskOutcome:
    name: str
    status: str
    output: Any = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "SUCCESS"


@dataclass
class ReducedResult:
    outcomes: list[TaskOutcome] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return any(not outcome.ok for outcome in self.outcomes)

    @property
    def failed_names(self) -> list[str]:
        return [outcome.name for outcome in self.outcomes if not outcome.ok]

    def outputs(self) -> dict[str, Any]:
        return {outcome.name: outcome.output for outcome in self.outcomes if outcome.ok}

    def summary(self) -> dict:
        return {
            "results": self.outputs(),
            "failed": self.failed_names,
            "partial": self.partial,
        }


async def fan_out(
    tasks: dict[str, Callable[[], Awaitable[Any]]],
    *,
    timeout_ms: int = 10000,
    max_concurrency: int = 4,
    read_only: bool = True,
) -> ReducedResult:
    """并行执行只读子任务，单个失败不影响其他结果。"""
    if not read_only:
        raise ValueError("Fan-out 只允许只读子任务")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run(name: str, task: Callable[[], Awaitable[Any]]) -> TaskOutcome:
        async with semaphore:
            try:
                output = await asyncio.wait_for(task(), timeout=timeout_ms / 1000)
                return TaskOutcome(name=name, status="SUCCESS", output=output)
            except asyncio.TimeoutError:
                return TaskOutcome(name=name, status="TIMEOUT", error_code="AC.TASK.TIMEOUT")
            except Exception as exc:  # noqa: BLE001 - 子任务失败统一收敛
                return TaskOutcome(
                    name=name,
                    status="FAILED",
                    error_code="AC.TASK.FAILED",
                    error_message=str(exc),
                )

    outcomes = await asyncio.gather(*(_run(name, task) for name, task in tasks.items()))
    return ReducedResult(outcomes=list(outcomes))


def reduce_outcomes(result: ReducedResult) -> dict:
    """Reduce 节点统一汇总，部分失败时标注缺失信息。"""
    summary = result.summary()
    if summary["partial"]:
        summary["note"] = "部分信息获取失败：" + "、".join(summary["failed"])
    return summary
