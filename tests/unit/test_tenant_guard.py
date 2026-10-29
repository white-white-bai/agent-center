from sqlalchemy import select

from app.core.tenant import get_current_tenant, reset_current_tenant, set_current_tenant
from app.domain.session.models import Conversation


async def _seed(db_session) -> None:
    db_session.add_all(
        [
            Conversation(tenant_id="t1", user_id="u1", channel="web", status="ACTIVE"),
            Conversation(tenant_id="t2", user_id="u2", channel="web", status="ACTIVE"),
        ]
    )
    await db_session.commit()


async def test_tenant_guard_filters_orm_selects(db_session) -> None:
    await _seed(db_session)
    token = set_current_tenant("t1")
    try:
        rows = (await db_session.execute(select(Conversation))).scalars().all()
        tenants = {row.tenant_id for row in rows}
    finally:
        reset_current_tenant(token)

    assert tenants == {"t1"}


async def test_tenant_guard_can_be_skipped_explicitly(db_session) -> None:
    await _seed(db_session)
    token = set_current_tenant("t1")
    try:
        rows = (
            await db_session.execute(
                select(Conversation).execution_options(skip_tenant_guard=True)
            )
        ).scalars().all()
        tenants = {row.tenant_id for row in rows}
    finally:
        reset_current_tenant(token)

    assert tenants == {"t1", "t2"}


async def test_tenant_guard_noop_without_context(db_session) -> None:
    await _seed(db_session)

    assert get_current_tenant() is None
    rows = (await db_session.execute(select(Conversation))).scalars().all()
    assert len(rows) == 2
