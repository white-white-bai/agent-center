"""通过反向代理保持 SSE 长连接，统计心跳与断连。

用法：
    python scripts/sse_gateway_hold.py --url http://127.0.0.1:8080 \
        --session-id 1 --tenant t1 --seconds 1800 --heartbeat 15
"""

import argparse
import json
import time
from datetime import datetime

import httpx


def _event(lines: list[str]) -> tuple[str | None, dict | None, str | None]:
    name = None
    data = None
    event_id = None
    for line in lines:
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
        elif line.startswith("id: "):
            event_id = line[4:]
    return name, data, event_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--heartbeat", type=int, default=15)
    parser.add_argument("--output", default="sse_gateway_result.json")
    args = parser.parse_args()

    headers = {
        "X-Tenant-Id": args.tenant,
        "X-User-Id": "gw_test",
        "X-Roles": "admin",
        "Accept": "text/event-stream",
    }
    url = f"{args.url}/api/v1/chat/sessions/{args.session_id}/stream"
    started = time.monotonic()
    heartbeats: list[float] = []
    ready = False
    ended = False
    error = None
    buffer: list[str] = []

    try:
        with httpx.Client(timeout=args.seconds + 120) as client:
            with client.stream(
                "GET",
                url,
                params={
                    "timeoutSeconds": args.seconds,
                    "heartbeatSeconds": args.heartbeat,
                    "pollSeconds": 1,
                },
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                for line in response.iter_lines():
                    if line:
                        buffer.append(line)
                        continue
                    name, data, _ = _event(buffer)
                    buffer = []
                    now = time.monotonic()
                    if name == "stream.ready":
                        ready = True
                    elif name == "heartbeat":
                        heartbeats.append(round(now - started, 2))
                        print(
                            f"heartbeat #{len(heartbeats)} at {heartbeats[-1]}s",
                            flush=True,
                        )
                        if len(heartbeats) >= 2 and len(heartbeats) % 8 == 0:
                            print("progress", json.dumps({"elapsed": round(now - started, 1)}))
                    elif name == "stream.end":
                        ended = True
                        break
    except Exception as exc:  # noqa: BLE001 - 结果落盘用于验收
        error = repr(exc)

    elapsed = round(time.monotonic() - started, 2)
    gaps = [
        round(heartbeats[index] - heartbeats[index - 1], 2)
        for index in range(1, len(heartbeats))
    ]
    result = {
        "date": datetime.now().isoformat(),
        "url": url,
        "targetSeconds": args.seconds,
        "elapsedSeconds": elapsed,
        "ready": ready,
        "ended": ended,
        "heartbeats": len(heartbeats),
        "firstHeartbeat": heartbeats[0] if heartbeats else None,
        "lastHeartbeat": heartbeats[-1] if heartbeats else None,
        "maxGapSeconds": max(gaps) if gaps else None,
        "error": error,
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if error or not ready or not ended or elapsed < args.seconds - 5:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
