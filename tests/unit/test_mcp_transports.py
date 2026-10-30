import asyncio
import json
import sys

import httpx

from app.integrations.mcp.client import MCPClient
from app.integrations.mcp.transports import SSETransport, StdioTransport


class _QueueStream(httpx.AsyncByteStream):
    def __init__(self, queue: asyncio.Queue) -> None:
        self.queue = queue

    async def __aiter__(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item


async def test_sse_transport_lists_and_calls_tools() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(b"event: endpoint\ndata: /messages\n\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_QueueStream(queue),
            )
        payload = json.loads(request.content)
        if payload["method"] == "tools/list":
            result = {"tools": [{"name": "search"}]}
        else:
            result = {"content": [{"type": "text", "text": "ok"}]}
        queue.put_nowait(
            f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': payload['id'], 'result': result})}\n\n".encode()
        )
        return httpx.Response(202)

    client = MCPClient(
        mcp_transport=SSETransport(
            "http://mcp.local/sse", httpx_transport=httpx.MockTransport(handler)
        )
    )
    tools = await client.list_tools()
    result = await client.call_tool("search", {"q": "政策"})
    await client.close()

    assert tools == [{"name": "search"}]
    assert result["content"][0]["text"] == "ok"


async def test_stdio_transport_lists_and_calls_tools() -> None:
    script = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    if not line.strip():\n"
        "        continue\n"
        "    msg = json.loads(line)\n"
        "    if msg['method'] == 'tools/list':\n"
        "        result = {'tools': [{'name': 'echo'}]}\n"
        "    else:\n"
        "        result = {'content': [{'type': 'text', 'text': msg['params']['arguments'].get('q', '')}]}\n"
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    client = MCPClient(
        mcp_transport=StdioTransport(
            [sys.executable, "-u", "-c", script], env={"PYTHONIOENCODING": "utf-8"}
        )
    )
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"q": "政策"})
    await client.close()

    assert tools == [{"name": "echo"}]
    assert result["content"][0]["text"] == "政策"


async def test_http_transport_accepts_sse_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        body = {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {"tools": [{"name": "search"}]},
        }
        return httpx.Response(
            200,
            text=f"event: message\ndata: {json.dumps(body)}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    client = MCPClient("http://mcp.local", transport=httpx.MockTransport(handler))
    tools = await client.list_tools()
    await client.close()

    assert tools == [{"name": "search"}]
