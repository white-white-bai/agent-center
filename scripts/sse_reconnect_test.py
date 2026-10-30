"""A5 SSE 断线续流与网关重启演练。

前置：
    docker compose -f docker-compose.yml -f docker-compose.observability.yml \
      --profile gateway up -d gateway

用法：
    python scripts/sse_reconnect_test.py --app-url http://127.0.0.1:8000 \
        --gateway-url http://127.0.0.1:8080 --restart-container agent-center-app
"""

import argparse
import asyncio
import json
import subprocess
import time
from datetime import datetime

import httpx

HEADERS = {
    "X-User-Id": "sse_reconnect",
    "X-Roles": "admin",
    "Accept": "text/event-stream",
}


def parse_blocks(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        event = {"id": "", "event": None, "data": None}
        for line in block.splitlines():
            if line.startswith("id: "):
                event["id"] = line[4:]
            elif line.startswith("event: "):
                event["event"] = line[7:]
            elif line.startswith("data: "):
                event["data"] = json.loads(line[6:])
        if event["event"]:
            events.append(event)
    return events


async def read_stream(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    params: dict | None = None,
    max_events: int | None = None,
) -> list[dict]:
    events: list[dict] = []
    async with client.stream("GET", url, headers=headers, params=params) as response:
        response.raise_for_status()
        buffer: list[str] = []
        event = {"id": "", "event": None, "data": None}
        async for line in response.aiter_lines():
            if line:
                buffer.append(line)
                continue
            if not buffer:
                continue
            event = {"id": "", "event": None, "data": None}
            for item in buffer:
                if item.startswith("id: "):
                    event["id"] = item[4:]
                elif item.startswith("event: "):
                    event["event"] = item[7:]
                elif item.startswith("data: "):
                    event["data"] = json.loads(item[6:])
            buffer = []
            if event["event"]:
                events.append(event)
                if max_events is not None and len(events) >= max_events:
                    break
            if event["event"] == "stream.end":
                break
    return events


async def wait_run_events(
    client: httpx.AsyncClient,
    app_url: str,
    session_id: int,
    run_id: str,
    headers: dict,
) -> list[dict]:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = await client.get(
            f"{app_url}/api/v1/chat/sessions/{session_id}/runs/{run_id}/events",
            headers=headers,
            params={"limit": 500},
        )
        response.raise_for_status()
        events = response.json()["data"]
        if any(item["event"] == "message.end" for item in events):
            return events
        await asyncio.sleep(0.5)
    raise TimeoutError("Run 事件未在 90s 内完成")


async def prepare(
    client: httpx.AsyncClient, app_url: str, tenant: str
) -> tuple[int, str, list[dict]]:
    agent = (
        await client.post(
            f"{app_url}/api/v1/admin/agents",
            headers={**HEADERS, "X-Tenant-Id": tenant},
            json={"code": "sse_reconnect_agent", "name": "sse", "domain_code": "district_service"},
        )
    ).json()["data"]
    version = (
        await client.post(
            f"{app_url}/api/v1/admin/agents/{agent['id']}/versions",
            headers={**HEADERS, "X-Tenant-Id": tenant},
            json={"role": "sse", "model_policy": {"max_steps": 2}},
        )
    ).json()["data"]
    await client.post(
        f"{app_url}/api/v1/admin/agents/{agent['id']}/publish",
        headers={**HEADERS, "X-Tenant-Id": tenant},
        json={"version_id": version["id"]},
    )
    session_id = (
        await client.post(
            f"{app_url}/api/v1/chat/sessions",
            headers={**HEADERS, "X-Tenant-Id": tenant},
            json={"channel": "web"},
        )
    ).json()["data"]["sessionId"]
    return session_id, tenant, []


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://127.0.0.1:8000")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8080")
    parser.add_argument("--tenant", default=f"sse_reconnect_{int(time.time())}")
    parser.add_argument("--restart-container", default="")
    parser.add_argument("--output", default="sse_reconnect_result.json")
    args = parser.parse_args()

    headers = {**HEADERS, "X-Tenant-Id": args.tenant}
    result = {"date": datetime.now().isoformat(), "tenant": args.tenant, "checks": {}}
    async with httpx.AsyncClient(timeout=120) as client:
        session_id, _, _ = await prepare(client, args.app_url, args.tenant)

        # 1. 完成一次消息，获得完整事件基线。
        response = await client.post(
            f"{args.app_url}/api/v1/chat/sessions/{session_id}/messages",
            headers=headers,
            json={"message": "你好，请回复一句话", "agentCode": "sse_reconnect_agent"},
        )
        response.raise_for_status()
        started = parse_blocks(response.text)
        run_id = next(item["data"]["runId"] for item in started if item["event"] == "run.start")
        baseline = await wait_run_events(client, args.app_url, session_id, run_id, headers)
        baseline_ids = [item["id"] for item in baseline]
        result["checks"]["baselineEvents"] = len(baseline)
        result["checks"]["baselineUniqueIds"] = len(set(baseline_ids)) == len(baseline_ids)

        # 2. 通过网关读取前 2 个事件后主动断开，再用 Last-Event-ID 续流。
        first = await read_stream(
            client,
            f"{args.gateway_url}/api/v1/chat/sessions/{session_id}/runs/{run_id}/stream",
            headers=headers,
            max_events=2,
        )
        last_id = first[-1]["id"]
        result["checks"]["abortedAfter"] = len(first)
        result["checks"]["lastEventId"] = last_id

        rest = await read_stream(
            client,
            f"{args.gateway_url}/api/v1/chat/sessions/{session_id}/runs/{run_id}/stream",
            headers=headers,
            params={"lastEventId": last_id},
        )
        rest_ids = [item["id"] for item in rest if item["event"] != "stream.end"]
        expected = [item["id"] for item in baseline if item["id"] not in {e["id"] for e in first}]
        expected = [item for item in expected if item]
        result["checks"]["replayedEvents"] = len(rest_ids)
        result["checks"]["noDuplicate"] = len(rest_ids) == len(set(rest_ids))
        result["checks"]["noMissing"] = rest_ids == expected
        result["checks"]["restFirstId"] = rest_ids[0] if rest_ids else None
        result["checks"]["expectedFirstId"] = expected[0] if expected else None

        # 3. 会话级长连接，网关下游重启后重连。
        if args.restart_container:
            ready = []

            async def hold_session() -> None:
                events = await read_stream(
                    client,
                    f"{args.gateway_url}/api/v1/chat/sessions/{session_id}/stream",
                    headers=headers,
                    params={"timeoutSeconds": 30, "heartbeatSeconds": 1, "pollSeconds": 0.2},
                    max_events=3,
                )
                ready.extend(events)

            task = asyncio.create_task(hold_session())
            await asyncio.sleep(2)
            subprocess.run(
                ["docker", "restart", args.restart_container],
                check=True,
                capture_output=True,
                text=True,
            )
            try:
                await asyncio.wait_for(task, timeout=40)
            except Exception:  # noqa: BLE001 - 重启断开是预期结果
                pass
            result["checks"]["streamBeforeRestart"] = [e["event"] for e in ready]

            healthy = False
            for _ in range(30):
                try:
                    probe = await client.get(f"{args.app_url}/healthz")
                    if probe.status_code == 200:
                        healthy = True
                        break
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(1)
            result["checks"]["upstreamHealthyAfterRestart"] = healthy

            after = await read_stream(
                client,
                f"{args.gateway_url}/api/v1/chat/sessions/{session_id}/stream",
                headers=headers,
                params={"timeoutSeconds": 3, "heartbeatSeconds": 1, "pollSeconds": 0.2},
            )
            result["checks"]["reconnectedAfterRestart"] = any(
                item["event"] == "stream.ready" for item in after
            )

    result["ok"] = all(
        result["checks"].get(key, False)
        for key in ("baselineUniqueIds", "noDuplicate", "noMissing")
    ) and (
        not args.restart_container
        or (
            result["checks"].get("upstreamHealthyAfterRestart")
            and result["checks"].get("reconnectedAfterRestart")
        )
    )
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
