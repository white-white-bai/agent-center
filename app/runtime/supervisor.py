import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tenant import TenantContext
from app.domain.agent.models import AgentDefinition, AgentVersion
from app.integrations.llm.client import ChatMessage, LLMRequest

CONFIDENCE_THRESHOLD = 0.6

ROUTE_PROMPT = """你是智能体路由器。只能从候选 Agent 中选择一个，或回答无法判断。
用户输入：{message}
候选 Agent：
{candidates}
只输出 JSON：{{"agent":"候选编码或空","confidence":0到1,"reason":"简短原因"}}
"""


@dataclass
class RouteCandidate:
    agent_code: str
    domain_code: str
    score: float


@dataclass
class RouteResult:
    selected_agent: str | None
    domain_code: str | None
    intent: str | None
    confidence: float
    reason_code: str
    need_clarification: bool
    candidates: list[RouteCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "selectedAgent": self.selected_agent,
            "domainCode": self.domain_code,
            "intent": self.intent,
            "confidence": self.confidence,
            "reasonCode": self.reason_code,
            "needClarification": self.need_clarification,
            "candidates": [
                {"agentCode": item.agent_code, "domainCode": item.domain_code, "score": item.score}
                for item in self.candidates
            ],
        }


async def _published_agents(session: AsyncSession, tenant_id: str) -> list[tuple[AgentDefinition, AgentVersion]]:
    result = await session.execute(
        select(AgentDefinition, AgentVersion)
        .join(AgentVersion, AgentVersion.id == AgentDefinition.current_version_id)
        .where(
            AgentDefinition.tenant_id == tenant_id,
            AgentDefinition.lifecycle == "PUBLISHED",
        )
    )
    return [(agent, version) for agent, version in result.all()]


def _rules(version: AgentVersion) -> dict:
    return (version.config_json or {}).get("router_rules") or {}


def _score(agent: AgentDefinition, version: AgentVersion, message: str, channel: str | None, region: str | None) -> tuple[float, bool]:
    rules = _rules(version)
    channels = rules.get("channels") or []
    if channels and channel and channel not in channels:
        return 0.0, False
    regions = rules.get("regions") or []
    if regions and region and region not in regions:
        return 0.0, False

    score = 0.0
    for keyword in rules.get("keywords") or []:
        if keyword and keyword in message:
            score += 1.0
    for intent in rules.get("intents") or []:
        if intent and intent in message:
            score += 0.8
    if rules.get("domains") and agent.domain_code in rules["domains"]:
        score += 0.2
    return score, True


async def _model_select(
    session: AsyncSession,
    ctx: TenantContext,
    router,
    model: str,
    message: str,
    candidates: list[RouteCandidate],
) -> tuple[str | None, float, str]:
    listing = "\n".join(
        f"- {item.agent_code}（领域 {item.domain_code}，规则得分 {item.score}）" for item in candidates
    )
    request = LLMRequest(
        messages=[
            ChatMessage(
                role="user",
                content=ROUTE_PROMPT.format(message=message, candidates=listing),
            )
        ],
        model=model,
        response_format={"type": "json_object"},
    )
    response = await router.complete(session, ctx, request, primary_model=model, max_retries=0)
    payload = json.loads(response.content)
    return (
        payload.get("agent") or None,
        max(0.0, min(1.0, float(payload.get("confidence") or 0.0))),
        payload.get("reason") or "",
    )


async def route(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    message: str,
    channel: str | None = None,
    region: str | None = None,
    router=None,
    model: str | None = None,
) -> RouteResult:
    """Supervisor 路由：硬规则过滤 → 候选召回 → 规则打分 → 模型选择 → 服务端校验。"""
    agents = await _published_agents(session, ctx.tenant_id)
    candidates: list[RouteCandidate] = []
    for agent, version in agents:
        score, allowed = _score(agent, version, message, channel, region)
        if not allowed:
            continue
        candidates.append(RouteCandidate(agent_code=agent.code, domain_code=agent.domain_code, score=score))

    if not candidates:
        return RouteResult(
            selected_agent=None,
            domain_code=None,
            intent=None,
            confidence=0.0,
            reason_code="NO_CANDIDATE",
            need_clarification=True,
        )

    if len(agents) == 1:
        agent, _ = agents[0]
        return RouteResult(
            selected_agent=agent.code,
            domain_code=agent.domain_code,
            intent=None,
            confidence=1.0,
            reason_code="SINGLE_AGENT",
            need_clarification=False,
            candidates=candidates,
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    allowed_codes = {item.agent_code for item in candidates}

    if router is not None and len(candidates) > 1:
        try:
            selected, model_confidence, reason = await _model_select(
                session,
                ctx,
                router,
                model or get_settings().llm_model,
                message,
                candidates[:5],
            )
        except Exception:  # noqa: BLE001 - 模型路由失败回退规则
            selected, model_confidence, reason = None, 0.0, ""
        if selected in allowed_codes:
            chosen = next(item for item in candidates if item.agent_code == selected)
            return RouteResult(
                selected_agent=chosen.agent_code,
                domain_code=chosen.domain_code,
                intent=None,
                confidence=model_confidence,
                reason_code="MODEL_SELECT",
                need_clarification=model_confidence < CONFIDENCE_THRESHOLD,
                candidates=candidates,
            )

    top = candidates[0]
    if top.score <= 0:
        return RouteResult(
            selected_agent=None,
            domain_code=None,
            intent=None,
            confidence=0.0,
            reason_code="NO_MATCH",
            need_clarification=True,
            candidates=candidates,
        )

    confidence = min(0.99, 0.5 + 0.1 * top.score)
    tied = len(candidates) > 1 and candidates[1].score == top.score
    if tied:
        confidence = min(confidence, 0.5)
    need_clarification = confidence < CONFIDENCE_THRESHOLD

    return RouteResult(
        selected_agent=top.agent_code,
        domain_code=top.domain_code,
        intent=None,
        confidence=confidence,
        reason_code="DOMAIN_MATCH",
        need_clarification=need_clarification,
        candidates=candidates,
    )
