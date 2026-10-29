import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tenant import TenantContext
from app.domain.profile.models import UserProfileTag
from app.domain.profile.service import get_active_matters
from app.integrations.llm.client import ChatMessage, LLMRequest

SUGGESTION_PROMPT = """你是政务服务助手。根据用户画像与在办事项，给出最多 3 条主动建议。
画像标签：{tags}
在办事项：{matters}
只输出 JSON：{{"suggestions":["建议1","建议2"],"summary":"一句话总结"}}
"""


def _rule_suggestions(tags: list[str], matters: list[dict]) -> dict:
    suggestions = []
    for matter in matters[:3]:
        name = matter.get("matter") or matter.get("name")
        status = matter.get("status")
        if name:
            suggestions.append(f"你的「{name}」当前状态：{status or '处理中'}，可随时查询进度。")
    if not suggestions and tags:
        suggestions.append(f"根据你的偏好（{'、'.join(tags[:3])}），可为你推荐相关办事指南。")
    return {"suggestions": suggestions[:3], "summary": "、".join(suggestions[:1])}


async def generate_suggestions(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    router=None,
    model: str | None = None,
) -> dict:
    tags_result = await session.execute(
        select(UserProfileTag).where(
            UserProfileTag.tenant_id == ctx.tenant_id, UserProfileTag.user_id == ctx.user_id
        )
    )
    tags = [f"{tag.tag_key}：{tag.tag_value}" for tag in tags_result.scalars().all()]
    matters = await get_active_matters(session, ctx)

    if router is not None and (tags or matters):
        try:
            request = LLMRequest(
                messages=[
                    ChatMessage(
                        role="user",
                        content=SUGGESTION_PROMPT.format(
                            tags="；".join(tags) or "无",
                            matters=json.dumps(matters, ensure_ascii=False),
                        ),
                    )
                ],
                model=model or get_settings().llm_model,
                response_format={"type": "json_object"},
            )
            response = await router.complete(
                session, ctx, request, primary_model=request.model, max_retries=0
            )
            payload = json.loads(response.content)
            suggestions = [str(item) for item in payload.get("suggestions") or []][:3]
            if suggestions:
                return {
                    "suggestions": suggestions,
                    "summary": payload.get("summary") or suggestions[0],
                    "source": "model",
                }
        except Exception:  # noqa: BLE001 - 模型生成失败回退规则
            pass

    fallback = _rule_suggestions(tags, matters)
    fallback["source"] = "rule"
    return fallback
