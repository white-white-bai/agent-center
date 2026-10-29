from app.core.tenant import TenantContext
from app.domain.evaluation import metrics
from app.domain.evaluation.models import Badcase, Feedback
from app.domain.model.models import ModelUsageLog
from app.domain.session.models import Conversation, Run
from app.domain.tool.models import ToolInvokeLog

CTX = TenantContext(tenant_id="t1", user_id="u1")


async def _seed(db_session) -> None:
    db_session.add_all(
        [
            Conversation(tenant_id="t1", user_id="u1", channel="web", status="ACTIVE"),
            Conversation(tenant_id="t1", user_id="u1", channel="web", status="WAITING_USER"),
            Conversation(tenant_id="t2", user_id="u2", channel="web", status="ACTIVE"),
        ]
    )
    await db_session.commit()
    db_session.add_all(
        [
            Run(
                id="r1",
                tenant_id="t1",
                conversation_id=1,
                trace_id="t",
                status="COMPLETED",
                token_input=100,
                token_output=50,
            ),
            Run(id="r2", tenant_id="t1", conversation_id=1, trace_id="t", status="FAILED"),
            ToolInvokeLog(tenant_id="t1", tool_code="a", status="SUCCESS"),
            ToolInvokeLog(tenant_id="t1", tool_code="a", status="FAILED"),
            Feedback(tenant_id="t1", rating="up"),
            Feedback(tenant_id="t1", rating="down"),
            Badcase(tenant_id="t1", status="OPEN"),
            Badcase(tenant_id="t1", status="CONVERTED"),
            ModelUsageLog(tenant_id="t1", model_alias="m", status="SUCCESS", latency_ms=100),
            ModelUsageLog(tenant_id="t1", model_alias="m", status="FAILED", latency_ms=300),
        ]
    )
    await db_session.commit()


async def test_overview_aggregates_tenant_metrics(db_session) -> None:
    await _seed(db_session)

    data = await metrics.overview(db_session, CTX)

    assert data["conversations"] == {"total": 2, "active": 1, "waitingUser": 1, "transferred": 0}
    assert data["runs"] == {"total": 2, "byStatus": {"COMPLETED": 1, "FAILED": 1}}
    assert data["tokens"] == {"input": 100, "output": 50}
    assert data["tools"]["successRate"] == 0.5
    assert data["feedback"] == {"up": 1, "down": 1}
    assert data["badcases"]["open"] == 1
    assert data["models"]["avgLatencyMs"] == 200.0


async def test_overview_is_empty_for_new_tenant(db_session) -> None:
    data = await metrics.overview(db_session, TenantContext(tenant_id="empty", user_id="u"))

    assert data["conversations"]["total"] == 0
    assert data["runs"]["total"] == 0
    assert data["tools"]["successRate"] == 0.0
