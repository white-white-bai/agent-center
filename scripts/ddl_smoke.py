"""DDL 建库后的 CRUD/SSE 冒烟。

用法：
    python scripts/ddl_smoke.py --base-url http://127.0.0.1:8012
"""

import argparse
import json
from datetime import datetime

import httpx


def parse_sse(text: str) -> dict:
    run_id = None
    answer = ""
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
        elif name == "message.delta" and data:
            answer += data.get("content", "")
        elif name == "message.end" and data:
            finish = data.get("finishReason")
    return {"runId": run_id, "answer": answer, "finish": finish}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--tenant", default=f"ddl_{datetime.now().strftime('%H%M%S')}")
    args = parser.parse_args()
    headers = {"X-Tenant-Id": args.tenant, "X-User-Id": "ddl_user", "X-Roles": "admin"}

    with httpx.Client(timeout=60) as client:
        agent = client.post(
            f"{args.base_url}/api/v1/admin/agents",
            headers=headers,
            json={"code": "ddl_agent", "name": "DDL 冒烟", "domain_code": "district_service"},
        ).json()["data"]
        version = client.post(
            f"{args.base_url}/api/v1/admin/agents/{agent['id']}/versions",
            headers=headers,
            json={"role": "冒烟", "model_policy": {"primary": "stub-primary", "max_steps": 2}},
        ).json()["data"]
        client.post(
            f"{args.base_url}/api/v1/admin/agents/{agent['id']}/publish",
            headers=headers,
            json={"version_id": version["id"]},
        )

        space = client.post(
            f"{args.base_url}/api/v1/admin/knowledge-spaces",
            headers=headers,
            json={"code": "ddl_kb", "name": "DDL 知识", "domainCode": "district_service"},
        ).json()["data"]
        document = client.post(
            f"{args.base_url}/api/v1/admin/knowledge-spaces/{space['id']}/documents",
            headers=headers,
            json={"title": "冒烟指南", "content": "冒烟测试需要身份证。"},
        ).json()["data"]
        client.post(
            f"{args.base_url}/api/v1/admin/knowledge-spaces/{space['id']}/documents/{document['id']}/publish",
            headers=headers,
        )
        search = client.post(
            f"{args.base_url}/api/v1/knowledge/search",
            headers=headers,
            json={"query": "冒烟测试", "topK": 5},
        ).json()["data"]

        session = client.post(
            f"{args.base_url}/api/v1/chat/sessions", headers=headers, json={"channel": "web"}
        ).json()["data"]
        response = client.post(
            f"{args.base_url}/api/v1/chat/sessions/{session['sessionId']}/messages",
            headers={**headers, "Accept": "text/event-stream"},
            json={"message": "冒烟测试需要什么材料？", "agentCode": "ddl_agent"},
        )
        stream = parse_sse(response.text)
        detail = client.get(
            f"{args.base_url}/api/v1/admin/runs/{stream['runId']}", headers=headers
        ).json()["data"]

        print(
            json.dumps(
                {
                    "tenant": args.tenant,
                    "agentId": agent["id"],
                    "knowledgeHits": len(search),
                    "sessionId": session["sessionId"],
                    "runId": stream["runId"],
                    "finish": stream["finish"],
                    "runStatus": detail["run"]["status"],
                    "steps": len(detail["steps"]),
                    "answer": stream["answer"][:120],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
