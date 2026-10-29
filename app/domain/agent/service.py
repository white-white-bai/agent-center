from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import TenantContext
from app.domain.agent.models import AgentDefinition, AgentVersion


async def create_agent(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    code: str,
    name: str,
    domain_code: str,
    description: str | None = None,
) -> AgentDefinition:
    existing = await session.execute(
        select(AgentDefinition).where(
            AgentDefinition.tenant_id == ctx.tenant_id, AgentDefinition.code == code
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"Agent 编码已存在: {code}")
    agent = AgentDefinition(
        tenant_id=ctx.tenant_id,
        code=code,
        name=name,
        domain_code=domain_code,
        description=description,
        lifecycle="DRAFT",
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def get_agent(session: AsyncSession, ctx: TenantContext, agent_id: int) -> AgentDefinition:
    result = await session.execute(
        select(AgentDefinition).where(
            AgentDefinition.id == agent_id, AgentDefinition.tenant_id == ctx.tenant_id
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise NotFoundError("Agent 不存在")
    return agent


async def list_agents(session: AsyncSession, ctx: TenantContext) -> list[AgentDefinition]:
    result = await session.execute(
        select(AgentDefinition)
        .where(AgentDefinition.tenant_id == ctx.tenant_id)
        .order_by(AgentDefinition.id.desc())
    )
    return list(result.scalars().all())


async def create_version(
    session: AsyncSession,
    ctx: TenantContext,
    agent_id: int,
    *,
    config: dict,
    model_policy: dict,
    tool_bindings: list,
    knowledge_scopes: list,
    prompt_version_id: int | None,
) -> AgentVersion:
    await get_agent(session, ctx, agent_id)
    result = await session.execute(
        select(AgentVersion.version_no)
        .where(AgentVersion.agent_id == agent_id, AgentVersion.tenant_id == ctx.tenant_id)
        .order_by(AgentVersion.version_no.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none() or 0
    version = AgentVersion(
        tenant_id=ctx.tenant_id,
        agent_id=agent_id,
        version_no=latest + 1,
        config_json=config,
        model_policy_json=model_policy,
        tool_bindings_json=tool_bindings,
        knowledge_scopes_json=knowledge_scopes,
        prompt_version_id=prompt_version_id,
        status="DRAFT",
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)
    return version


async def publish_version(
    session: AsyncSession, ctx: TenantContext, agent_id: int, version_id: int
) -> AgentVersion:
    agent = await get_agent(session, ctx, agent_id)
    result = await session.execute(
        select(AgentVersion).where(
            AgentVersion.id == version_id,
            AgentVersion.agent_id == agent_id,
            AgentVersion.tenant_id == ctx.tenant_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise NotFoundError("Agent 版本不存在")
    if version.status == "PUBLISHED":
        raise ConflictError("该版本已发布，已发布版本不可重复发布或原地修改")

    previous = await session.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.tenant_id == ctx.tenant_id,
            AgentVersion.status == "PUBLISHED",
        )
    )
    for old in previous.scalars().all():
        old.status = "DEPRECATED"

    version.status = "PUBLISHED"
    version.published_at = datetime.utcnow()
    agent.current_version_id = version.id
    agent.lifecycle = "PUBLISHED"
    await session.commit()
    await session.refresh(version)
    return version


async def get_published_version(
    session: AsyncSession, ctx: TenantContext, agent_code: str
) -> tuple[AgentDefinition, AgentVersion]:
    result = await session.execute(
        select(AgentDefinition).where(
            AgentDefinition.tenant_id == ctx.tenant_id, AgentDefinition.code == agent_code
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"Agent 不存在: {agent_code}")
    if agent.current_version_id is None:
        raise ConflictError(f"Agent 尚未发布版本: {agent_code}")
    version_result = await session.execute(
        select(AgentVersion).where(AgentVersion.id == agent.current_version_id)
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        raise ConflictError(f"Agent 当前版本数据缺失: {agent_code}")
    return agent, version
