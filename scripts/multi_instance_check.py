"""多实例一致性检查：共享 Redis 会话锁与限流计数。

前置：两个 app 实例共享同一 MySQL/Redis，并通过 AC_MODERATION_URL 指向带延迟的
模拟审核服务（scripts/mock_moderation.py）。

用法：
    python scripts/multi_instance_check.py --base-a http://127.0.0.1:8010 \
        --base-b http://127.0.0.1:8011
"""

import argparse
import asyncio
import json
import time
from datetime import datetime

import httpx


def _parse_sse(text: str) -> tuple[str | None, str | None]:
    run_id = None
    finish = None
    for block in text.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name == "run.start" and data:
            run_id = data.get("runId")
        elif name == "message.end" and data:
            finish = data.get("finishReason")
    return run_id, finish


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-a", default="http://127.0.0.1:8010")
    parser.add_argument("--base-b", default="http://127.0.0.1:8011")
    parser.add_argument("--tenant", default=f"mi_{datetime.now().strftime('%H%M%S')}")
    args = parser.parse_args()
    headers = {"X-Tenant-Id": args.tenant, "X-User-Id": "mi_user", "X-Roles": "admin"}
    results: dict = {"tenant": args.tenant}

    async with httpx.AsyncClient(timeout=120) as client:
        agent = (
            await client.post(
                f"{args.base_a}/api/v1/admin/agents",
                headers=headers,
                json={"code": "mi_agent", "name": "多实例", "domain_code": "district_service"},
            )
        ).json()["data"]
        version = (
            await client.post(
                f"{args.base_a}/api/v1/admin/agents/{agent['id']}/versions",
                headers=headers,
                json={"role": "多实例", "model_policy": {"primary": "stub-primary", "max_steps": 2}},
            )
        ).json()["data"]
        await client.post(
            f"{args.base_a}/api/v1/admin/agents/{agent['id']}/publish",
            headers=headers,
            json={"version_id": version["id"]},
        )
        session_id = (
            await client.post(
                f"{args.base_a}/api/v1/chat/sessions", headers=headers, json={"channel": "web"}
            )
        ).json()["data"]["sessionId"]
        cross_read = await client.get(
            f"{args.base_b}/api/v1/chat/sessions/{session_id}", headers=headers
        )
        results["crossInstanceRead"] = cross_read.status_code

        tool_code = f"mi_rate_{args.tenant[-6:]}"
        await client.post(
            f"{args.base_a}/api/v1/admin/tools",
            headers=headers,
            json={
                "tool_code": tool_code,
                "name": "限流工具",
                "source_type": "FUNCTION",
                "rate_limit_policy": {"limit": 1, "window_seconds": 60},
            },
        )
        first = await client.post(
            f"{args.base_a}/api/v1/admin/tools/{tool_code}/test",
            headers=headers,
            json={"arguments": {}},
        )
        second = await client.post(
            f"{args.base_b}/api/v1/admin/tools/{tool_code}/test",
            headers=headers,
            json={"arguments": {}},
        )
        results["rateLimit"] = {
            "firstStatus": first.status_code,
            "secondStatus": second.status_code,
            "shared": first.status_code == 200 and second.status_code == 429,
        }

        async def send(base: str) -> dict:
            started = time.perf_counter()
            response = await client.post(
                f"{base}/api/v1/chat/sessions/{session_id}/messages",
                headers={**headers, "Accept": "text/event-stream"},
                json={"message": "多实例并发消息"},
            )
            elapsed = time.perf_counter() - started
            run_id, finish = _parse_sse(response.text)
            return {
                "status": response.status_code,
                "runId": run_id,
                "finish": finish,
                "elapsed": elapsed,
            }

        started = time.perf_counter()
        both = await asyncio.gather(send(args.base_a), send(args.base_b))
        elapsed = time.perf_counter() - started
        results["concurrent"] = {
            "elapsedSeconds": round(elapsed, 2),
            "requests": both,
            "distinctRuns": both[0]["runId"] != both[1]["runId"],
            "serialized": elapsed >= 6.0,
        }

    print(json.dumps(results, ensure_ascii=False, indent=2))


asyncio.run(main())
