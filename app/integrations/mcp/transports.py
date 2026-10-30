import asyncio
import json
import os
import shlex
from typing import Any
from urllib.parse import urljoin

import httpx


class MCPError(Exception):
    pass


def iter_sse_events(text: str):
    event = "message"
    data: list[str] = []
    for line in text.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].lstrip())
        elif line == "":
            if data:
                yield event, "\n".join(data)
            event = "message"
            data = []
    if data:
        yield event, "\n".join(data)


class HTTPTransport:
    """JSON-RPC over HTTP，兼容直接 JSON 与 SSE 响应。"""

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        httpx_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers or {},
            timeout=timeout,
            transport=httpx_transport,
        )

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post("", json=payload)
        response.raise_for_status()
        if "text/event-stream" in response.headers.get("content-type", ""):
            for _, data in iter_sse_events(response.text):
                body = json.loads(data)
                if body.get("id") == payload.get("id"):
                    return body
            raise MCPError("SSE 响应中没有匹配的 JSON-RPC 结果")
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()


class SSETransport:
    """MCP HTTP+SSE 传输：GET 建立事件流，POST 到 endpoint 发送请求。"""

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        httpx_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._httpx_transport = httpx_transport
        self._stream_client = httpx.AsyncClient(
            headers=self.headers, transport=httpx_transport, timeout=None
        )
        self._post_client = httpx.AsyncClient(
            headers=self.headers, transport=httpx_transport, timeout=timeout
        )
        self._endpoint: str | None = None
        self._ready = asyncio.Event()
        self._pending: dict[int, asyncio.Future] = {}
        self._task: asyncio.Task | None = None
        self._closed = False
        self._error: str | None = None

    async def _ensure_started(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._ready.wait(), self.timeout)

    async def _run(self) -> None:
        try:
            async with self._stream_client.stream("GET", self.url) as response:
                response.raise_for_status()
                event = "message"
                data: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event = line[len("event:") :].strip()
                    elif line.startswith("data:"):
                        data.append(line[len("data:") :].lstrip())
                    elif line == "":
                        if data:
                            self._dispatch(event, "\n".join(data))
                        event = "message"
                        data = []
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 连接异常统一转为 MCPError
            self._fail(f"SSE 连接失败: {exc}")
        finally:
            if not self._closed:
                self._fail("SSE 连接已关闭")

    def _dispatch(self, event: str, data: str) -> None:
        if event == "endpoint":
            self._endpoint = urljoin(self.url, data)
            self._ready.set()
            return
        if event != "message":
            return
        try:
            body = json.loads(data)
        except json.JSONDecodeError:
            return
        request_id = body.get("id")
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        if "error" in body:
            future.set_exception(MCPError(body["error"].get("message", "MCP 调用失败")))
        else:
            future.set_result(body)

    def _fail(self, message: str) -> None:
        self._error = message
        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPError(message))
        self._pending.clear()
        if not self._ready.is_set():
            self._ready.set()

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_started()
        if self._error:
            raise MCPError(self._error)
        if self._endpoint is None:
            raise MCPError("SSE 未返回 endpoint")
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[payload["id"]] = future
        try:
            response = await self._post_client.post(self._endpoint, json=payload)
            if response.status_code >= 400:
                raise MCPError(f"MCP endpoint 返回 {response.status_code}")
            if "application/json" in response.headers.get("content-type", ""):
                body = response.json()
                if body.get("id") == payload.get("id"):
                    return body
            return await asyncio.wait_for(future, self.timeout)
        finally:
            self._pending.pop(payload["id"], None)

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._fail("SSE 连接已关闭")
        await self._stream_client.aclose()
        await self._post_client.aclose()


class StdioTransport:
    """MCP stdio 传输：子进程 stdin/stdout 上按行收发 JSON-RPC。"""

    def __init__(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not command or not all(isinstance(item, str) and item for item in command):
            raise MCPError("stdio MCP 需要非空 command 列表")
        self.command = command
        self.env = env or {}
        self.cwd = cwd
        self.timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._stderr_tail = ""
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

    async def _ensure_started(self) -> None:
        if self._process is not None:
            return
        merged_env = {**os.environ, **self.env}
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            cwd=self.cwd,
        )
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            try:
                body = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            future = self._pending.get(body.get("id"))
            if future is None or future.done():
                continue
            if "error" in body:
                future.set_exception(MCPError(body["error"].get("message", "MCP 调用失败")))
            else:
                future.set_result(body)
        self._fail(self._exit_message())

    async def _read_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            self._stderr_tail = (self._stderr_tail + line.decode("utf-8", errors="replace"))[-2000:]

    def _exit_message(self) -> str:
        detail = self._stderr_tail.strip()
        return f"MCP stdio 进程已退出{': ' + detail if detail else ''}"

    def _fail(self, message: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPError(message))
        self._pending.clear()

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_started()
        assert self._process is not None and self._process.stdin is not None
        if self._process.returncode is not None:
            raise MCPError(self._exit_message())
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[payload["id"]] = future
        try:
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            async with self._write_lock:
                self._process.stdin.write(line.encode("utf-8"))
                await self._process.stdin.drain()
            return await asyncio.wait_for(future, self.timeout)
        finally:
            self._pending.pop(payload["id"], None)

    async def close(self) -> None:
        self._closed = True
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._stdout_task, self._stderr_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *[task for task in (self._stdout_task, self._stderr_task) if task is not None],
            return_exceptions=True,
        )
        self._fail("MCP stdio 连接已关闭")
