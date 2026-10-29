from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.core.responses import ok
from app.domain.session import service
from app.domain.tool import confirmation

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


class ConfirmationRequest(BaseModel):
    decision: str = Field(pattern="^(confirm|reject)$")
    arguments: dict | None = None


@router.post("/{session_id}/confirmations/{confirmation_id}")
async def decide_confirmation(
    session_id: int,
    confirmation_id: str,
    payload: ConfirmationRequest,
    session: DbSession,
    ctx: CurrentTenant,
) -> dict:
    await service.get_conversation(session, ctx, session_id)
    record, executable = await confirmation.decide(
        session,
        ctx,
        confirmation_id=confirmation_id,
        decision=payload.decision,
        arguments=payload.arguments,
    )
    return ok(
        {
            "confirmationId": record.confirmation_id,
            "status": record.status,
            "executable": executable,
            "toolCode": record.tool_code,
        }
    )
