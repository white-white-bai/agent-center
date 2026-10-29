class RunRegistry:
    """进程内 Run 中断登记表。

    多实例部署需改为 Redis 发布订阅，见 docs/open-questions.md。
    """

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._interrupted: set[str] = set()

    def register(self, run_id: str) -> None:
        self._active.add(run_id)
        self._interrupted.discard(run_id)

    def finish(self, run_id: str) -> None:
        self._active.discard(run_id)
        self._interrupted.discard(run_id)

    def request_interrupt(self, run_id: str) -> bool:
        if run_id not in self._active:
            return False
        self._interrupted.add(run_id)
        return True

    def is_interrupted(self, run_id: str) -> bool:
        return run_id in self._interrupted

    def is_active(self, run_id: str) -> bool:
        return run_id in self._active


run_registry = RunRegistry()
