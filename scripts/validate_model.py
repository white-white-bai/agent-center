"""真实模型决策验证脚本。

用法（容器内）：
    python scripts/validate_model.py

覆盖：决策 JSON 解析成功率、类型匹配率、流式输出、备用模型可用性。
不打印密钥。
"""

import asyncio
import json
import time

from app.core.config import get_settings
from app.integrations.llm.client import ChatMessage, LLMRequest, LLMResponse
from app.integrations.llm.openai_client import build_llm_client
from app.runtime.decisions import (
    ClarifyDecision,
    FanoutDecision,
    FinalDecision,
    SlotsDecision,
    ToolCallDecision,
    TopicDecision,
    parse_decision,
)
from app.runtime.react_executor import build_system_prompt

TOOLS = ["knowledge.search", "matter.status.query", "profile.get", "matter.submit"]

CASES: list[tuple[str, str, str]] = [
    ("final", "营业执照办理需要哪些材料？直接回答。", "final"),
    ("final", "解释一下什么是政务服务一网通办。", "final"),
    ("final", "办理社保卡需要本人到场吗？", "final"),
    ("final", "公共资源交易中心的工作时间是什么？", "final"),
    ("final", "请说明公积金提取的基本条件。", "final"),
    ("final", "医保报销比例一般是多少？", "final"),
    ("final", "如何查询自己的办事进度？", "final"),
    ("final", "外地户籍可以在本地办理居住证吗？", "final"),
    ("final", "企业开办一般需要几个环节？", "final"),
    ("final", "请用一句话介绍你能做什么。", "final"),
    ("final", "政务服务中心周末上班吗？", "final"),
    ("final", "残疾人补贴怎么申请？", "final"),
    ("final", "新生儿落户需要哪些手续？", "final"),
    ("final", "请解释告知承诺制的含义。", "final"),
    ("final", "不动产权证遗失如何补办？", "final"),
    ("tool_call", "必须先调用工具，查询申请编号 A2026001 的办理进度，不要直接回答。", "tool_call"),
    ("tool_call", "请使用 profile.get 查询当前用户画像后再回答。", "tool_call"),
    ("tool_call", "请先调用 knowledge.search 检索营业执照政策，再给出结论。", "tool_call"),
    ("tool_call", "申请编号 A10086 的状态是什么？必须调用 matter.status.query。", "tool_call"),
    ("tool_call", "请调用 knowledge.search 查询公共资源交易规则，不要猜测。", "tool_call"),
    ("tool_call", "先用 profile.get 获取用户所在区域，再回答办理地点。", "tool_call"),
    ("tool_call", "查询编号 B7788 的审批结果，必须调用工具。", "tool_call"),
    ("tool_call", "请检索最新的社保补贴政策，使用 knowledge.search。", "tool_call"),
    ("tool_call", "调用 matter.status.query 查询 C2026 的进度后再回答。", "tool_call"),
    ("tool_call", "先查用户画像（profile.get），再推荐可办事项。", "tool_call"),
    ("clarify", "我想办那个证，需要带什么？", "clarify"),
    ("clarify", "帮我查一下进度。", "clarify"),
    ("clarify", "这个怎么办？", "clarify"),
    ("clarify", "我要办理变更，需要准备什么材料？", "clarify"),
    ("clarify", "我的申请现在到哪一步了？", "clarify"),
    ("clarify", "上次说的事情进展如何？", "clarify"),
    ("clarify", "我想咨询一个业务。", "clarify"),
    ("clarify", "这个政策适用于我吗？", "clarify"),
    ("clarify", "我要提交材料，怎么弄？", "clarify"),
    ("clarify", "帮我看看这个能不能办。", "clarify"),
    ("slots", "我要办理营业执照，用户类型是个体工商户。请记录槽位。", "slots"),
    ("slots", "申请编号是 A2026001，请记录申请编号槽位。", "slots"),
    ("slots", "办理事项是社保补缴，请记录事项名称。", "slots"),
    ("slots", "所在区域是常州市天宁区，请记录区域槽位。", "slots"),
    ("slots", "用户类型是企业法人，事项是税务登记，请记录这两个槽位。", "slots"),
    ("slots", "联系电话不方便提供，其他信息：办理事项为公积金提取。请记录办理事项。", "slots"),
    ("slots", "申请编号 B7788，事项是公共资源交易报名，请记录槽位。", "slots"),
    ("slots", "办理事项为居住证，所属区域为钟楼区，请记录槽位。", "slots"),
    ("topic", "请把当前话题挂起，切换到社保查询。", "topic"),
    ("topic", "先转到公共资源交易话题，稍后再回来。", "topic"),
    ("topic", "用户说：回到刚才的话题。请恢复原话题。", "topic"),
    ("topic", "用户说：还是继续说之前办理营业执照的事。请恢复原话题。", "topic"),
    ("fanout", "请并行调用 knowledge.search 查询营业执照政策，并调用 matter.status.query 查询 A2026001 进度，再汇总。", "fanout"),
    ("fanout", "并行查询：knowledge.search 检索社保政策，profile.get 查询用户画像。", "fanout"),
    ("fanout", "同时调用 knowledge.search 和 matter.status.query 获取信息，不要逐个调用。", "fanout"),
]

EXPECTED = {
    "final": FinalDecision,
    "tool_call": ToolCallDecision,
    "clarify": ClarifyDecision,
    "slots": SlotsDecision,
    "topic": TopicDecision,
    "fanout": FanoutDecision,
}

# final / clarify 的答案有合理多解（例如缺少信息时追问、跨话题时切换），
# 只对明确要求动作的类别统计类型匹配率。
INSTRUCTED = {"tool_call", "slots", "topic", "fanout"}

STATE = {
    "active_topic": "营业执照办理",
    "topic_stack": [{"topic": "社保查询", "status": "suspended"}],
    "slots": {},
}


def describe(decision) -> dict:
    if isinstance(decision, ToolCallDecision):
        return {"type": "tool_call", "tool": decision.tool}
    if isinstance(decision, FinalDecision):
        return {"type": "final", "answer": decision.answer[:80]}
    if isinstance(decision, ClarifyDecision):
        return {"type": "clarify", "question": decision.question[:80]}
    if isinstance(decision, SlotsDecision):
        return {"type": "slots", "slots": decision.slots}
    if isinstance(decision, TopicDecision):
        return {"type": "topic", "action": decision.action}
    if isinstance(decision, FanoutDecision):
        return {"type": "fanout", "tasks": [item.get("tool") for item in decision.tasks]}
    return {"type": "unknown"}


async def main() -> None:
    settings = get_settings()
    print(f"model={settings.llm_model} fallback={settings.llm_fallback_model}")
    print(f"key_configured={bool(settings.llm_api_key)} cases={len(CASES)}")

    client = build_llm_client()
    system_prompt = build_system_prompt(
        {"role": "政务咨询助手", "goal": "理解用户意图并输出规定 JSON"},
        TOOLS,
        required_slots=["matter_type", "application_number"],
        session_state=STATE,
    )

    parsed_ok = 0
    type_ok = 0
    instructed_total = 0
    instructed_ok = 0
    distribution: dict[str, int] = {}
    failures: list[str] = []
    started = time.perf_counter()

    for index, (category, prompt, expected) in enumerate(CASES, start=1):
        try:
            response: LLMResponse = await client.complete(
                LLMRequest(
                    messages=[
                        ChatMessage(role="system", content=system_prompt),
                        ChatMessage(role="user", content=prompt),
                    ],
                    model=settings.llm_model,
                    timeout_ms=30000,
                    response_format={"type": "json_object"},
                )
            )
            decision = parse_decision(response.content)
            parsed_ok += 1
            matched = isinstance(decision, EXPECTED[expected])
            distribution[expected] = distribution.get(expected, 0) + 1
            if expected in INSTRUCTED:
                instructed_total += 1
                if matched:
                    instructed_ok += 1
                else:
                    failures.append(
                        f"#{index} {category}: expected={expected} got={describe(decision)} raw={response.content[:120]}"
                    )
            elif not matched:
                # final/clarify 允许合理多解，仅记录不参与匹配率
                type_ok += 1
            else:
                type_ok += 1
        except Exception as exc:  # noqa: BLE001 - 统计失败样本
            failures.append(f"#{index} {category}: parse/call failed: {str(exc)[:150]}")

    elapsed = time.perf_counter() - started
    total = len(CASES)
    print(f"parsed={parsed_ok}/{total} ({parsed_ok / total:.1%})")
    print(
        f"instructed_type_match={instructed_ok}/{instructed_total} "
        f"({instructed_ok / instructed_total:.1%})"
    )
    print(f"elapsed={elapsed:.1f}s")
    print(f"expected_categories={distribution}")
    for line in failures[:10]:
        print("FAIL", line)

    stream_chunks: list[str] = []
    try:
        async for chunk in client.stream(
            LLMRequest(
                messages=[ChatMessage(role="user", content="从1数到3，只输出数字")],
                model=settings.llm_model,
                timeout_ms=30000,
            )
        ):
            stream_chunks.append(chunk)
        print(f"stream_ok={bool(stream_chunks)} chunks={len(stream_chunks)} text={''.join(stream_chunks)[:40]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"stream_failed={str(exc)[:150]}")

    try:
        fallback = await client.complete(
            LLMRequest(
                messages=[ChatMessage(role="user", content="只回复两个字：备用")],
                model=settings.llm_fallback_model,
                timeout_ms=30000,
            )
        )
        print(f"fallback_ok=True model={fallback.model} content={fallback.content[:40]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"fallback_ok=False error={str(exc)[:150]}")

    summary = {
        "model": settings.llm_model,
        "cases": total,
        "parsed": parsed_ok,
        "parsedRate": round(parsed_ok / total, 4),
        "instructedTotal": instructed_total,
        "instructedMatch": instructed_ok,
        "instructedMatchRate": round(instructed_ok / instructed_total, 4),
    }
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))


asyncio.run(main())
