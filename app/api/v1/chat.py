from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.session import service

router = APIRouter(prefix="/chat/sessions", tags=["chat"])


class CreateSessionRequest(BaseModel):
    channel: str = Field(min_length=1, max_length=32)
    agent_group_code: str | None = Field(default=None, max_length=100)
    metadata: dict = Field(default_factory=dict)


@router.post("")
async def create_session(
    payload: CreateSessionRequest,
    session: DbSession,
    ctx: CurrentTenant,
) -> dict:
    conversation = await service.create_conversation(
        session,
        ctx,
        channel=payload.channel,
        agent_group_code=payload.agent_group_code,
        metadata=payload.metadata,
    )
    return ok(service.serialize_conversation(conversation))


@router.get("/{session_id}")
async def get_session(session_id: int, session: DbSession, ctx: CurrentTenant) -> dict:
    conversation = await service.get_conversation(session, ctx, session_id)
    return ok(service.serialize_conversation(conversation))
