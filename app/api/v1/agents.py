from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.agent import service

router = APIRouter(prefix="/admin/agents", tags=["agents"])


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
    agent = await service.create_agent(
        session,
        ctx,
        code=payload.code,
        name=payload.name,
        domain_code=payload.domain_code,
        description=payload.description,
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
    return ok(_serialize_version(version))


@router.post("/{agent_id}/publish")
async def publish_agent(agent_id: int, payload: PublishRequest, session: DbSession, ctx: CurrentTenant) -> dict:
    version = await service.publish_version(session, ctx, agent_id, payload.version_id)
    return ok(_serialize_version(version))
