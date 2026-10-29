import json

import httpx

from app.core.tenant import TenantContext
from app.domain.evaluation import alerts, metrics
from app.domain.evaluation.models import Badcase
from app.domain.session.models import Run
from app.domain.tool.models import ToolInvokeLog

CTX = TenantContext(tenant_id="t1", user_id="u1")


async def _seed(db_session) -> None:
    db_session.add_all(
        [
            Run(id="r_ok", tenant_id="t1", conversation_id=1, trace_id="t", status="COMPLETED"),
            *[
                Run(
                    id=f"r_fail_{index}",
                    tenant_id="t1",
                    conversation_id=1,
                    trace_id="t",
                    status="FAILED",
                )
                for index in range(11)
            ],
            ToolInvokeLog(tenant_id="t1", tool_code="a", status="FAILED"),
            *[
                Badcase(tenant_id="t1", status="OPEN")
                for _ in range(3)
            ],
        ]
    )
    await db_session.commit()


async def test_render_prometheus_contains_core_metrics(db_session) -> None:
    await _seed(db_session)
    data = await metrics.overview(db_session, CTX)

    text = alerts.render_prometheus(data)

    assert "ac_conversations_total 0" in text
    assert 'ac_runs_total{status="FAILED"} 11' in text
    assert "ac_tool_success_rate 0.0" in text
    assert "ac_badcases_open 3" in text


async def test_evaluate_alerts_reports_run_and_tool_issues(db_session) -> None:
    await _seed(db_session)

    found = await alerts.evaluate_alerts(db_session, CTX)
    codes = {alert.code for alert in found}

    assert "AC.ALERT.RUN_FAILURE_RATE" in codes
    assert "AC.ALERT.BADCASE_OPEN" not in codes
    assert "AC.ALERT.TOOL_SUCCESS_RATE" not in codes


async def test_notify_alerts_posts_webhook_payload() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    sent = await alerts.notify_alerts(
        [alerts.Alert(code="X", message="m", value=1.0, threshold=2.0)],
        webhook_url="http://hook.local/alert",
        transport=httpx.MockTransport(handler),
    )

    assert sent is True
    assert captured["body"]["alerts"][0]["code"] == "X"


async def test_notify_alerts_skips_without_webhook() -> None:
    assert await alerts.notify_alerts([], webhook_url=None) is False
