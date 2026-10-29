from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.tenant import TenantContext
from app.domain.model.models import ModelUsageLog
from app.domain.session.events import RunEvent
from app.domain.session.models import RunStep
from app.domain.tool.models import ToolInvokeLog
from app.workers.retention import purge_trace

CTX = TenantContext(tenant_id="t1", user_id="u1")


async def _seed(db_session, *, created_at: datetime, suffix: str = "") -> None:
    run_id = f"r1{suffix}"
    db_session.add_all(
        [
            RunStep(tenant_id="t1", run_id=run_id, step_no=1, step_type="X", created_at=created_at),
            RunEvent(
                tenant_id="t1", run_id=run_id, seq=1, event="x", data_json={}, created_at=created_at
            ),
            ModelUsageLog(tenant_id="t1", model_alias="m", created_at=created_at),
            ToolInvokeLog(tenant_id="t1", tool_code="t", status="SUCCESS", created_at=created_at),
        ]
    )
    await db_session.commit()


async def test_purge_trace_deletes_only_expired_rows(db_session) -> None:
    old = datetime.utcnow() - timedelta(days=200)
    recent = datetime.utcnow() - timedelta(days=1)
    await _seed(db_session, created_at=old, suffix="_old")
    await _seed(db_session, created_at=recent, suffix="_new")

    result = await purge_trace(db_session, CTX, days=90)

    assert result["deleted"] == {
        "run_step": 1,
        "run_event": 1,
        "model_usage_log": 1,
        "tool_invoke_log": 1,
    }
    for model in (RunStep, RunEvent, ModelUsageLog, ToolInvokeLog):
        rows = (await db_session.execute(select(model))).scalars().all()
        assert len(rows) == 1
        assert rows[0].created_at >= recent - timedelta(minutes=1)


async def test_purge_trace_is_tenant_isolated(db_session) -> None:
    old = datetime.utcnow() - timedelta(days=200)
    await _seed(db_session, created_at=old)
    db_session.add(
        RunStep(tenant_id="t2", run_id="r2", step_no=1, step_type="X", created_at=old)
    )
    await db_session.commit()

    await purge_trace(db_session, CTX, days=90)

    rows = (await db_session.execute(select(RunStep))).scalars().all()
    assert [row.tenant_id for row in rows] == ["t2"]
