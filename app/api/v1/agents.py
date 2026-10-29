from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.core.tenant import require_admin
from app.domain.agent import service

router = APIRouter(prefix="/admin/agents", tags=["agents"], dependencies=[Depends(require_admin)])


class CreateAgentRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    domain_code: str = Field(min_length=1, max_length=100)
    description: str | None = None


class CreateVersionRequest(BaseModel):
    role: str | None = None
    goal: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    prompt_version_id: int | None = None
    model_policy: dict = Field(default_factory=dict)
    memory_policy: dict = Field(default_factory=dict)
    fallback: dict = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    knowledge_scopes: list[str] = Field(default_factory=list)
    router_rules: dict = Field(default_factory=dict)
    required_slots: list[str] = Field(default_factory=list)
    slot_questions: dict = Field(default_factory=dict)


class PublishRequest(BaseModel):
    version_id: int


def _serialize_agent(agent) -> dict:
    return {
        "id": agent.id,
        "code": agent.code,
        "name": agent.name,
        "domainCode": agent.domain_code,
        "lifecycle": agent.lifecycle,
        "currentVersionId": agent.current_version_id,
    }


def _serialize_version(version) -> dict:
    return {
        "id": version.id,
        "agentId": version.agent_id,
        "versionNo": version.version_no,
        "status": version.status,
        "config": version.config_json,
        "modelPolicy": version.model_policy_json,
        "tools": version.tool_bindings_json,
        "knowledgeScopes": version.knowledge_scopes_json,
        "promptVersionId": version.prompt_version_id,
        "publishedAt": version.published_at.isoformat() if version.published_at else None,
    }


@router.get("")
async def list_agents(session: DbSession, ctx: CurrentTenant) -> dict:
    agents = await service.list_agents(session, ctx)
    return ok([_serialize_agent(agent) for agent in agents])


@router.post("")
async def create_agent(payload: CreateAgentRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    from app.domain.evaluation import audit

    agent = await service.create_agent(
        session,
        ctx,
        code=payload.code,
        name=payload.name,
        domain_code=payload.domain_code,
        description=payload.description,
    )
    await audit.record_audit(
        session,
        ctx,
        action="agent.create",
        resource_type="agent",
        resource_id=agent.id,
        detail={"code": agent.code, "domainCode": agent.domain_code},
    )
    return ok(_serialize_agent(agent))


@router.post("/{agent_id}/versions")
async def create_version(
    agent_id: int, payload: CreateVersionRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    config = {
        "role": payload.role,
        "goal": payload.goal,
        "success_criteria": payload.success_criteria,
        "constraints": payload.constraints,
        "memory_policy": payload.memory_policy,
        "fallback": payload.fallback,
        "router_rules": payload.router_rules,
        "required_slots": payload.required_slots,
        "slot_questions": payload.slot_questions,
    }
    from app.domain.evaluation import audit

    version = await service.create_version(
        session,
        ctx,
        agent_id,
        config=config,
        model_policy=payload.model_policy,
        tool_bindings=payload.tools,
        knowledge_scopes=payload.knowledge_scopes,
        prompt_version_id=payload.prompt_version_id,
    )
    await audit.record_audit(
        session,
        ctx,
        action="agent.version.create",
        resource_type="agent_version",
        resource_id=version.id,
        detail={"agentId": agent_id, "versionNo": version.version_no},
    )
    return ok(_serialize_version(version))


class BindingsRequest(BaseModel):
    tools: list[str] = Field(default_factory=list)
    promptVersionId: int | None = None


@router.get("/{agent_id}/bindings")
async def get_bindings(agent_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    tools, prompt_version_id = await service.get_bindings(session, ctx, agent_id)
    return ok({"tools": tools, "promptVersionId": prompt_version_id})


@router.put("/{agent_id}/bindings")
async def update_bindings(
    agent_id: int, payload: BindingsRequest, session: DbSession, ctx: CurrentTenant
) -> dict:
    from app.domain.evaluation import audit

    await service.sync_bindings(
        session,
        ctx,
        agent_id,
        tools=payload.tools,
        prompt_version_id=payload.promptVersionId,
    )
    await audit.record_audit(
        session,
        ctx,
        action="agent.bindings.update",
        resource_type="agent",
        resource_id=agent_id,
        detail={"tools": payload.tools, "promptVersionId": payload.promptVersionId},
    )
    return ok({"tools": payload.tools, "promptVersionId": payload.promptVersionId})


@router.post("/{agent_id}/publish")
async def publish_agent(agent_id: int, payload: PublishRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    from app.domain.evaluation import audit

    version = await service.publish_version(session, ctx, agent_id, payload.version_id)
    await audit.record_audit(
        session,
        ctx,
        action="agent.publish",
        resource_type="agent",
        resource_id=agent_id,
        detail={"versionId": version.id, "versionNo": version.version_no},
    )
    return ok(_serialize_version(version))
