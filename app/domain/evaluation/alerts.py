import logging
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tenant import TenantContext
from app.domain.evaluation import metrics

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    code: str
    message: str
    value: float
    threshold: float

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
        }


async def evaluate_alerts(session: AsyncSession, ctx: TenantContext) -> list[Alert]:
    settings = get_settings()
    data = await metrics.overview(session, ctx)
    alerts: list[Alert] = []

    tools = data["tools"]
    if tools["total"] >= 10 and tools["successRate"] < settings.alert_tool_success_rate_min:
        alerts.append(
            Alert(
                code="AC.ALERT.TOOL_SUCCESS_RATE",
                message=f"工具成功率过低：{tools['successRate']:.2%}",
                value=tools["successRate"],
                threshold=settings.alert_tool_success_rate_min,
            )
        )

    runs = data["runs"]
    if runs["total"] >= 10:
        failed = runs["byStatus"].get("FAILED", 0)
        rate = failed / runs["total"]
        if rate > settings.alert_run_failure_rate_max:
            alerts.append(
                Alert(
                    code="AC.ALERT.RUN_FAILURE_RATE",
                    message=f"Run 失败率过高：{rate:.2%}",
                    value=round(rate, 4),
                    threshold=settings.alert_run_failure_rate_max,
                )
            )

    if data["badcases"]["open"] > settings.alert_badcase_open_max:
        alerts.append(
            Alert(
                code="AC.ALERT.BADCASE_OPEN",
                message=f"待处理 Badcase 过多：{data['badcases']['open']}",
                value=float(data["badcases"]["open"]),
                threshold=float(settings.alert_badcase_open_max),
            )
        )

    models = data["models"]
    if models["calls"] >= 10 and models.get("successRate", 1.0) < settings.alert_model_success_rate_min:
        alerts.append(
            Alert(
                code="AC.ALERT.MODEL_SUCCESS_RATE",
                message=f"模型调用成功率过低：{models['successRate']:.2%}",
                value=models["successRate"],
                threshold=settings.alert_model_success_rate_min,
            )
        )
    return alerts


async def notify_alerts(
    alerts: list[Alert],
    *,
    webhook_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    url = webhook_url or get_settings().alert_webhook_url
    if not url or not alerts:
        return False
    try:
        async with httpx.AsyncClient(timeout=5, transport=transport) as client:
            response = await client.post(url, json={"alerts": [alert.to_dict() for alert in alerts]})
            response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("告警推送失败: %s", exc)
        return False


def render_prometheus(data: dict) -> str:
    lines: list[str] = []

    def metric(name: str, value, labels: dict[str, str] | None = None) -> None:
        label_text = ""
        if labels:
            label_text = "{" + ",".join(f'{key}="{val}"' for key, val in labels.items()) + "}"
        lines.append(f"{name}{label_text} {value}")

    conversations = data["conversations"]
    metric("ac_conversations_total", conversations["total"])
    metric("ac_conversations_by_status", conversations["active"], {"status": "ACTIVE"})
    metric("ac_conversations_by_status", conversations["waitingUser"], {"status": "WAITING_USER"})
    metric("ac_conversations_by_status", conversations["transferred"], {"status": "TRANSFERRED"})

    for status, count in data["runs"]["byStatus"].items():
        metric("ac_runs_total", count, {"status": status})
    metric("ac_runs_total", data["runs"]["total"], {"status": "ALL"})

    metric("ac_tokens_total", data["tokens"]["input"], {"direction": "input"})
    metric("ac_tokens_total", data["tokens"]["output"], {"direction": "output"})

    metric("ac_tool_calls_total", data["tools"]["total"])
    metric("ac_tool_success_rate", data["tools"]["successRate"])

    metric("ac_feedback_total", data["feedback"]["up"], {"rating": "up"})
    metric("ac_feedback_total", data["feedback"]["down"], {"rating": "down"})
    metric("ac_badcases_open", data["badcases"]["open"])

    metric("ac_model_calls_total", data["models"]["calls"])
    metric("ac_model_success_rate", data["models"].get("successRate", 0.0))
    metric("ac_model_latency_ms_avg", data["models"]["avgLatencyMs"])
    return "\n".join(lines) + "\n"


def prometheus_content_type() -> str:
    return "text/plain; version=0.0.4; charset=utf-8"
