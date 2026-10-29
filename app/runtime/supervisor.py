from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.agent.models import AgentDefinition, AgentVersion

CONFIDENCE_THRESHOLD = 0.6


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


async def route(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    message: str,
    channel: str | None = None,
    region: str | None = None,
) -> RouteResult:
    """Supervisor 路由：硬规则过滤 → 候选召回 → 打分 → 服务端校验 → 澄清判断。"""
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
