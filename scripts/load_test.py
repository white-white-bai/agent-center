"""Agent Center 并发压测。

默认针对桩模型服务，测量平台自身开销（鉴权、锁、DB、SSE），不包含真实模型推理时间。

用法：
    python scripts/load_test.py --base-url http://127.0.0.1:8001 \
        --sessions 2000 --concurrency 200
"""

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime

import httpx


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * ratio))
    return ordered[index]


async def _prepare_agent(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict,
    *,
    primary_model: str,
    fallback_model: str | None,
) -> None:
    agent = (
        await client.post(
            f"{base_url}/api/v1/admin/agents",
            headers=headers,
            json={"code": "load_agent", "name": "压测 Agent", "domain_code": "district_service"},
        )
    ).json()["data"]
    model_policy = {"primary": primary_model, "max_steps": 3}
    if fallback_model:
        model_policy["fallback"] = fallback_model
    version = (
        await client.post(
            f"{base_url}/api/v1/admin/agents/{agent['id']}/versions",
            headers=headers,
            json={"role": "压测", "model_policy": model_policy},
        )
    ).json()["data"]
    await client.post(
        f"{base_url}/api/v1/admin/agents/{agent['id']}/publish",
        headers=headers,
        json={"version_id": version["id"]},
    )


async def _one_session(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        started = time.perf_counter()
        try:
            session = await client.post(
                f"{base_url}/api/v1/chat/sessions",
                headers=headers,
                json={"channel": "load"},
            )
            session.raise_for_status()
            session_id = session.json()["data"]["sessionId"]
            request_started = time.perf_counter()
            first_token = None
            finish = None
            error = None
            async with client.stream(
                "POST",
                f"{base_url}/api/v1/chat/sessions/{session_id}/messages",
                headers={**headers, "Accept": "text/event-stream"},
                json={"message": "压测消息"},
            ) as response:
                if response.status_code != 200:
                    error = f"HTTP_{response.status_code}"
                event = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: ") and event:
                        data = json.loads(line[6:])
                        if event == "message.delta" and first_token is None:
                            first_token = time.perf_counter()
                        elif event == "message.end":
                            finish = data.get("finishReason")
                        elif event == "error":
                            error = data.get("code") or "SSE_ERROR"
                    if finish:
                        break
            ended = time.perf_counter()
            return {
                "ok": error is None and finish is not None,
                "error": error,
                "finish": finish,
                "ttft_ms": (
                    (first_token - request_started)
                    if first_token is not None
                    else (ended - request_started)
                )
                * 1000,
                "e2e_ms": (ended - started) * 1000,
            }
        except Exception as exc:  # noqa: BLE001 - 压测失败按错误统计
            return {"ok": False, "error": type(exc).__name__, "finish": None, "ttft_ms": 0, "e2e_ms": 0}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--base-urls", default="", help="多节点地址，逗号分隔；优先于 --base-url")
    parser.add_argument("--sessions", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--primary-model", default="stub-primary")
    parser.add_argument("--fallback-model", default="")
    parser.add_argument("--tenant", default=f"load_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    args = parser.parse_args()

    headers = {
        "X-Tenant-Id": args.tenant,
        "X-User-Id": "load_user",
        "X-Roles": "admin",
    }
    limits = httpx.Limits(
        max_connections=args.concurrency + 20, max_keepalive_connections=args.concurrency
    )
    bases = [item.strip() for item in (args.base_urls or args.base_url).split(",") if item.strip()]
    async with httpx.AsyncClient(timeout=180, limits=limits) as client:
        await _prepare_agent(
            client,
            bases[0],
            headers,
            primary_model=args.primary_model,
            fallback_model=args.fallback_model or None,
        )

        semaphore = asyncio.Semaphore(args.concurrency)
        started = time.perf_counter()
        results = await asyncio.gather(
            *(
                _one_session(client, bases[index % len(bases)], headers, semaphore)
                for index in range(args.sessions)
            )
        )
        elapsed = time.perf_counter() - started

    ok = [item for item in results if item["ok"]]
    errors = [item for item in results if not item["ok"]]
    ttft = [item["ttft_ms"] for item in ok]
    e2e = [item["e2e_ms"] for item in ok]
    summary = {
        "tenant": args.tenant,
        "baseUrls": bases,
        "primaryModel": args.primary_model,
        "sessions": args.sessions,
        "concurrency": args.concurrency,
        "durationSeconds": round(elapsed, 2),
        "success": len(ok),
        "errors": len(errors),
        "errorRate": round(len(errors) / args.sessions, 4),
        "throughputPerSecond": round(args.sessions / elapsed, 2),
        "ttftP50Ms": round(percentile(ttft, 0.50), 1),
        "ttftP95Ms": round(percentile(ttft, 0.95), 1),
        "ttftP99Ms": round(percentile(ttft, 0.99), 1),
        "e2eP50Ms": round(percentile(e2e, 0.50), 1),
        "e2eP95Ms": round(percentile(e2e, 0.95), 1),
        "e2eP99Ms": round(percentile(e2e, 0.99), 1),
        "e2eMeanMs": round(statistics.mean(e2e), 1) if e2e else 0,
        "errorSamples": [item["error"] for item in errors[:10]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


asyncio.run(main())
