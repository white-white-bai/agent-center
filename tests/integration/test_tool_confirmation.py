HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1"}


async def _create_confirmation(db_session, *, conversation_id: int, arguments: dict | None = None):
    from app.core.tenant import TenantContext
    from app.domain.tool import confirmation

    return await confirmation.create_confirmation(
        db_session,
        TenantContext(tenant_id="t1", user_id="u1"),
        run_id="run_1",
        conversation_id=conversation_id,
        tool_code="matter.submit",
        arguments=arguments or {"matter": "license"},
        summary="将为你提交营业执照申请",
    )


async def test_confirm_executes_and_is_idempotent(db_session) -> None:
    from app.core.tenant import TenantContext
    from app.domain.tool import confirmation

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    record = await _create_confirmation(db_session, conversation_id=1)

    decided, executable = await confirmation.decide(
        db_session, ctx, confirmation_id=record.confirmation_id, decision="confirm"
    )
    assert decided.status == "CONFIRMED"
    assert executable is True

    again, executable_again = await confirmation.decide(
        db_session, ctx, confirmation_id=record.confirmation_id, decision="confirm"
    )
    assert again.status == "CONFIRMED"
    assert executable_again is False


async def test_reject_does_not_execute(db_session) -> None:
    from app.core.tenant import TenantContext
    from app.domain.tool import confirmation

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    record = await _create_confirmation(db_session, conversation_id=1)

    decided, executable = await confirmation.decide(
        db_session, ctx, confirmation_id=record.confirmation_id, decision="reject"
    )

    assert decided.status == "REJECTED"
    assert executable is False


async def test_changed_arguments_invalidate_confirmation(db_session) -> None:
    import pytest

    from app.core.exceptions import ConflictError
    from app.core.tenant import TenantContext
    from app.domain.tool import confirmation

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    record = await _create_confirmation(db_session, conversation_id=1, arguments={"matter": "license"})

    with pytest.raises(ConflictError):
        await confirmation.decide(
            db_session,
            ctx,
            confirmation_id=record.confirmation_id,
            decision="confirm",
            arguments={"matter": "other"},
        )


async def test_expired_confirmation_is_rejected(db_session) -> None:
    import pytest
    from datetime import datetime, timedelta

    from app.core.exceptions import ConflictError
    from app.core.tenant import TenantContext
    from app.domain.tool import confirmation

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    record = await _create_confirmation(db_session, conversation_id=1)
    record.expires_at = datetime.utcnow() - timedelta(seconds=1)
    await db_session.commit()

    with pytest.raises(ConflictError):
        await confirmation.decide(
            db_session, ctx, confirmation_id=record.confirmation_id, decision="confirm"
        )


def test_confirmation_api_requires_conversation_ownership(client) -> None:
    session_id = client.post(
        "/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS
    ).json()["data"]["sessionId"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/confirmations/cfm_unknown",
        json={"decision": "confirm"},
        headers=HEADERS,
    )

    assert response.status_code == 404
