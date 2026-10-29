"""真实业务问题集端到端抽样。

在容器内运行：
    python /tmp/e2e_sample.py

每次使用独立租户，自动创建知识库、Agent，并逐题走完整 HTTP + SSE 链路。
输出每题路由、引用、关键词命中、延迟与最终汇总。
"""

import json
import time
from datetime import datetime

import httpx

BASE = "http://127.0.0.1:8000"
RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")
TENANT = f"e2e_{RUN_ID}"
HEADERS = {"X-Tenant-Id": TENANT, "X-User-Id": "e2e_user", "X-Roles": "admin"}

DISTRICT_DOCS = [
    (
        "营业执照办理指南",
        """# 申请材料
申请人需要提交身份证、营业执照申请书、经营场所证明。
# 办理时限
材料齐全后 5 个工作日内办结。
# 办理地点
天宁区政务服务中心商事登记窗口。""",
    ),
    (
        "社保卡补办指南",
        """# 补办材料
本人身份证、社保卡挂失证明。
# 办理时限
补办一般需要 7 个工作日。""",
    ),
    (
        "公积金提取指南",
        """# 提取条件
购买自住住房、偿还房贷、租房等情形可以申请提取。
# 所需材料
身份证、购房合同、购房发票。""",
    ),
    (
        "居住证办理指南",
        """# 办理条件
在本地居住满半年且符合合法稳定就业、住所条件。
# 所需材料
身份证、居住证明、近期照片。""",
    ),
    (
        "新生儿落户指南",
        """# 所需材料
出生医学证明、父母双方身份证、结婚证。""",
    ),
]

TRANSACTION_DOCS = [
    (
        "投标保证金退还指南",
        """# 退还材料
中标通知书、退款申请书、原缴款凭证。
# 退还时限
资料齐全后 5 个工作日内退还。""",
    ),
    (
        "招投标异议投诉指南",
        """# 异议渠道
对招标过程有异议的，可向交易中心提交书面异议。
# 答复时限
交易中心在 3 个工作日内答复。""",
    ),
    (
        "CA 证书办理指南",
        """# 办理材料
营业执照、法定代表人身份证、授权委托书。
# 办理地点
公共资源交易中心 CA 窗口。""",
    ),
]

QUESTIONS = [
    {
        "no": 1,
        "question": "营业执照办理需要哪些材料？",
        "agent": "district",
        "keywords": ["身份证", "申请书"],
        "expect_citation": True,
    },
    {
        "no": 2,
        "question": "营业执照多久能办下来？",
        "agent": "district",
        "keywords": ["5 个工作日", "五个工作日", "5个工作日"],
        "expect_citation": True,
    },
    {
        "no": 3,
        "question": "社保卡丢了怎么补办？",
        "agent": "district",
        "keywords": ["挂失", "身份证"],
        "expect_citation": True,
    },
    {
        "no": 4,
        "question": "公积金提取需要什么材料？",
        "agent": "district",
        "keywords": ["购房合同", "发票"],
        "expect_citation": True,
    },
    {
        "no": 5,
        "question": "居住证办理需要哪些材料？",
        "agent": "district",
        "keywords": ["居住证明", "照片"],
        "expect_citation": True,
    },
    {
        "no": 6,
        "question": "新生儿落户要带什么？",
        "agent": "district",
        "keywords": ["出生医学证明", "结婚证"],
        "expect_citation": True,
    },
    {
        "no": 7,
        "question": "投标保证金怎么退？",
        "agent": "transaction",
        "keywords": ["中标通知书", "退款"],
        "expect_citation": True,
    },
    {
        "no": 8,
        "question": "对招投标结果有异议怎么办？",
        "agent": "transaction",
        "keywords": ["书面异议", "3 个工作日", "三个工作日"],
        "expect_citation": True,
    },
    {
        "no": 9,
        "question": "CA 证书怎么办理？",
        "agent": "transaction",
        "keywords": ["营业执照", "授权委托书"],
        "expect_citation": True,
    },
    {
        "no": 10,
        "question": "政务服务中心几点上班？",
        "agent": None,
        "keywords": [],
        "expect_citation": False,
    },
    {
        "no": 11,
        "question": "企业开办一般需要几个环节？",
        "agent": None,
        "keywords": [],
        "expect_citation": False,
    },
    {
        "no": 12,
        "question": "医保报销比例是多少？",
        "agent": None,
        "keywords": [],
        "expect_citation": False,
    },
    {
        "no": 13,
        "question": "告知承诺制是什么意思？",
        "agent": None,
        "keywords": [],
        "expect_citation": False,
    },
    {
        "no": 14,
        "question": "跨省通办有哪些事项？",
        "agent": None,
        "keywords": [],
        "expect_citation": False,
    },
    {
        "no": 15,
        "question": "残疾人补贴怎么申请？",
        "agent": None,
        "keywords": [],
        "expect_citation": False,
    },
    {
        "no": 16,
        "question": "12345 热线能办理哪些事项？",
        "agent": None,
        "keywords": [],
        "expect_citation": False,
    },
    {
        "no": 20,
        "question": "公共资源交易中心在哪里办理业务？",
        "agent": "transaction",
        "keywords": [],
        "expect_citation": False,
    },
]


def create_space(client: httpx.Client, code: str, name: str, domain: str) -> int:
    response = client.post(
        f"{BASE}/api/v1/admin/knowledge-spaces",
        headers=HEADERS,
        json={"code": f"{code}_{RUN_ID}", "name": name, "domainCode": domain},
    )
    return response.json()["data"]["id"]


def ingest(client: httpx.Client, space_id: int, title: str, content: str) -> int:
    response = client.post(
        f"{BASE}/api/v1/admin/knowledge-spaces/{space_id}/documents",
        headers=HEADERS,
        json={"title": title, "content": content, "authorityLevel": 4},
    )
    document_id = response.json()["data"]["id"]
    client.post(
        f"{BASE}/api/v1/admin/knowledge-spaces/{space_id}/documents/{document_id}/publish",
        headers=HEADERS,
    )
    return document_id


def create_agent(
    client: httpx.Client,
    code: str,
    name: str,
    domain: str,
    keywords: list[str],
    *,
    required_slots: list[str] | None = None,
    slot_questions: dict | None = None,
) -> str:
    agent = client.post(
        f"{BASE}/api/v1/admin/agents",
        headers=HEADERS,
        json={"code": code, "name": name, "domain_code": domain},
    ).json()["data"]
    version = client.post(
        f"{BASE}/api/v1/admin/agents/{agent['id']}/versions",
        headers=HEADERS,
        json={
            "role": f"{name}，负责准确解答并优先引用知识库",
            "goal": "准确回答用户问题，信息不足时追问",
            "router_rules": {"keywords": keywords},
            "required_slots": required_slots or [],
            "slot_questions": slot_questions or {},
            "model_policy": {
                "primary": "deepseek/deepseek-v4.1-flash",
                "fallback": "deepseek/deepseek-v4-flash",
                "max_steps": 4,
            },
        },
    ).json()["data"]
    client.post(
        f"{BASE}/api/v1/admin/agents/{agent['id']}/publish",
        headers=HEADERS,
        json={"version_id": version["id"]},
    )
    return code


def parse_sse(text: str) -> tuple[list[str], str, str | None, list[dict], str | None]:
    events: list[str] = []
    answer = ""
    finish = None
    citations: list[dict] = []
    error = None
    for block in text.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if not name:
            continue
        events.append(name)
        if name == "message.delta" and data:
            answer += data.get("content", "")
        elif name == "message.end" and data:
            finish = data.get("finishReason")
        elif name == "citation" and data:
            citations.append(data)
        elif name == "error" and data:
            error = data.get("code")
    return events, answer, finish, citations, error


def ask(
    client: httpx.Client, session_id: str, question: str, *, agent_code: str | None = None
) -> dict:
    payload: dict = {"message": question}
    if agent_code:
        payload["agentCode"] = agent_code

    attempts = 0
    response = None
    attempt_statuses: list[int] = []
    events: list[str] = []
    answer = ""
    finish = None
    citations: list[dict] = []
    error = None
    started = time.perf_counter()
    while attempts < 2:
        attempts += 1
        response = client.post(
            f"{BASE}/api/v1/chat/sessions/{session_id}/messages",
            headers=HEADERS,
            json=payload,
        )
        attempt_statuses.append(response.status_code)
        events, answer, finish, citations, error = parse_sse(response.text)
        if response.status_code == 200 and events:
            break

    latency = int((time.perf_counter() - started) * 1000)
    return {
        "latency_ms": latency,
        "status_code": response.status_code if response else 0,
        "attempt_statuses": attempt_statuses,
        "attempts": attempts,
        "events": events,
        "answer": answer,
        "finish": finish,
        "citations": citations,
        "error": error or (None if response and response.status_code == 200 and events else "EMPTY_RESPONSE"),
    }


def session_agent(client: httpx.Client, session_id: str) -> str | None:
    data = client.get(f"{BASE}/api/v1/chat/sessions/{session_id}", headers=HEADERS).json()["data"]
    return data.get("currentAgentCode")


def session_state(client: httpx.Client, session_id: str) -> dict:
    data = client.get(f"{BASE}/api/v1/chat/sessions/{session_id}", headers=HEADERS).json()["data"]
    return data.get("sessionState") or {}


def main() -> None:
    results: list[dict] = []
    started_at = time.perf_counter()
    with httpx.Client(timeout=120) as client:
        district_space = create_space(client, "district", "区级业务知识", "district_service")
        for title, content in DISTRICT_DOCS:
            ingest(client, district_space, title, content)

        transaction_space = create_space(client, "transaction", "公共资源交易知识", "transaction")
        for title, content in TRANSACTION_DOCS:
            ingest(client, transaction_space, title, content)

        create_agent(
            client,
            "district_consult",
            "区级政务咨询",
            "district_service",
            ["营业执照", "社保", "公积金", "居住证", "落户", "医保"],
        )
        create_agent(
            client,
            "transaction_agent",
            "公共资源交易咨询",
            "transaction",
            ["招投标", "投标", "公共资源", "CA 证书", "保证金"],
        )
        create_agent(
            client,
            "matter_agent",
            "事项办理助手",
            "district_service",
            ["办理进度", "申请编号", "提交申请", "事项办理", "进度查询"],
            required_slots=["matter_type", "application_number"],
            slot_questions={
                "matter_type": "请问您要办理什么事项？",
                "application_number": "请提供您的申请编号。",
            },
        )

        for item in QUESTIONS:
            session = client.post(
                f"{BASE}/api/v1/chat/sessions", headers=HEADERS, json={"channel": "web"}
            ).json()["data"]
            outcome = ask(client, session["sessionId"], item["question"])
            agent_code = session_agent(client, session["sessionId"])
            expected_prefix = item["agent"]
            routed_ok = (
                expected_prefix is None
                or (agent_code or "").startswith(expected_prefix[:8])
            )
            keyword_hit = int(
                any(word in outcome["answer"] for word in item["keywords"])
            ) if item["keywords"] else 0
            results.append(
                {
                    "no": item["no"],
                    "question": item["question"],
                    "expected_agent": expected_prefix,
                    "actual_agent": agent_code,
                    "routed_ok": routed_ok,
                    "finish": outcome["finish"],
                    "status_code": outcome["status_code"],
                    "attempt_statuses": outcome["attempt_statuses"],
                    "attempts": outcome["attempts"],
                    "citations": len(outcome["citations"]),
                    "expect_citation": item["expect_citation"],
                    "keyword_hit": keyword_hit,
                    "keyword_expected": bool(item["keywords"]),
                    "latency_ms": outcome["latency_ms"],
                    "error": outcome["error"],
                    "answer": outcome["answer"][:200],
                }
            )

        # 多轮槽位：先给出事项，再补申请编号
        session = client.post(
            f"{BASE}/api/v1/chat/sessions", headers=HEADERS, json={"channel": "web"}
        ).json()["data"]
        first = ask(client, session["sessionId"], "我要办理营业执照", agent_code="matter_agent")
        state_after_first = session_state(client, session["sessionId"])
        second = ask(client, session["sessionId"], "申请编号是 A2026001")
        state_after_second = session_state(client, session["sessionId"])

        results.append(
            {
                "no": 17,
                "question": "我要办理营业执照（多轮槽位）",
                "expected_agent": "matter",
                "actual_agent": session_agent(client, session["sessionId"]),
                "routed_ok": True,
                "finish": f"{first['finish']} -> {second['finish']}",
                "citations": len(first["citations"]) + len(second["citations"]),
                "expect_citation": False,
                "keyword_hit": 0,
                "keyword_expected": False,
                "status_code": first["status_code"],
                "attempt_statuses": first["attempt_statuses"] + second["attempt_statuses"],
                "attempts": first["attempts"] + second["attempts"],
                "latency_ms": first["latency_ms"] + second["latency_ms"],
                "error": first["error"] or second["error"],
                "answer": (first["answer"] + " | " + second["answer"])[:200],
                "slots_before": state_after_first.get("slots", {}).get("matter_type"),
                "slots_after": state_after_second.get("slots", {}).get("application_number"),
                "clarify_question": first["answer"][:80],
            }
        )

        # 缺信息澄清
        session = client.post(
            f"{BASE}/api/v1/chat/sessions", headers=HEADERS, json={"channel": "web"}
        ).json()["data"]
        clarify = ask(client, session["sessionId"], "帮我查一下进度", agent_code="matter_agent")
        results.append(
            {
                "no": 19,
                "question": "帮我查一下进度（缺槽位）",
                "expected_agent": "matter",
                "actual_agent": session_agent(client, session["sessionId"]),
                "routed_ok": True,
                "finish": clarify["finish"],
                "citations": len(clarify["citations"]),
                "expect_citation": False,
                "keyword_hit": 0,
                "keyword_expected": False,
                "status_code": clarify["status_code"],
                "attempt_statuses": clarify["attempt_statuses"],
                "attempts": clarify["attempts"],
                "latency_ms": clarify["latency_ms"],
                "error": clarify["error"],
                "answer": clarify["answer"][:200],
            }
        )

    total = len(results)
    completed = sum(1 for item in results if item["finish"] in {"completed", "waiting_user"})
    errors = [item for item in results if item["error"]]
    routed = sum(1 for item in results if item["routed_ok"])
    citation_expected = [
        item for item in results if item["expect_citation"] and item["finish"] == "completed"
    ]
    citation_hit = [item for item in citation_expected if item["citations"] > 0]
    keyword_expected = [item for item in results if item["keyword_expected"]]
    keyword_hits = sum(item["keyword_hit"] for item in keyword_expected)
    latencies = sorted(item["latency_ms"] for item in results)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]

    print(f"tenant={TENANT} questions={total}")
    for item in results:
        print(
            f"#{item['no']} agent={item['actual_agent']} routed={item['routed_ok']} "
            f"finish={item['finish']} citation={item['citations']} "
            f"kw_hit={item['keyword_hit']} statuses={item['attempt_statuses']} attempts={item['attempts']} "
            f"{item['latency_ms']}ms error={item['error']}"
        )
        print(f"    Q: {item['question']}")
        print(f"    A: {item['answer']}")

    summary = {
        "tenant": TENANT,
        "questions": total,
        "completed": completed,
        "errors": len(errors),
        "routingAccuracy": round(routed / total, 4),
        "citationHitRate": round(len(citation_hit) / len(citation_expected), 4)
        if citation_expected
        else None,
        "keywordHitRate": round(keyword_hits / len(keyword_expected), 4)
        if keyword_expected
        else None,
        "latencyP50Ms": p50,
        "latencyP95Ms": p95,
        "totalSeconds": round(time.perf_counter() - started_at, 1),
        "slotState": {
            "matter_type": results[-2].get("slots_before"),
            "application_number": results[-2].get("slots_after"),
        },
    }
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))


main()
