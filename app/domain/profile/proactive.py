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


def normalize_suggestions(
    items: list[object], *, max_items: int, max_chars: int
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        text = text[:max_chars].rstrip()
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
        if len(normalized) >= max_items:
            break
    return normalized


def _rule_suggestions(
    tags: list[str],
    matters: list[dict],
    *,
    max_items: int = 3,
    max_chars: int = 120,
) -> dict:
    suggestions: list[str] = []
    for matter in matters[:max_items]:
        name = matter.get("matter") or matter.get("name")
        status = matter.get("status")
        if name:
            suggestions.append(f"你的「{name}」当前状态：{status or '处理中'}，可随时查询进度。")
    if not suggestions and tags:
        suggestions.append(f"根据你的偏好（{'、'.join(tags[:3])}），可为你推荐相关办事指南。")
    suggestions = normalize_suggestions(suggestions, max_items=max_items, max_chars=max_chars)
    return {"suggestions": suggestions, "summary": suggestions[0] if suggestions else ""}


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

    settings = get_settings()
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
                model=model or settings.llm_model,
                response_format={"type": "json_object"},
            )
            response = await router.complete(
                session, ctx, request, primary_model=request.model, max_retries=0
            )
            payload = json.loads(response.content)
            raw = payload.get("suggestions")
            suggestions = normalize_suggestions(
                raw if isinstance(raw, list) else [],
                max_items=settings.suggestion_max_items,
                max_chars=settings.suggestion_item_max_chars,
            )
            if suggestions:
                summary = str(payload.get("summary") or "").strip()
                summary = summary[: settings.suggestion_summary_max_chars] or suggestions[0]
                return {"suggestions": suggestions, "summary": summary, "source": "model"}
        except Exception:  # noqa: BLE001 - 模型生成失败回退规则
            pass

    fallback = _rule_suggestions(
        tags,
        matters,
        max_items=settings.suggestion_max_items,
        max_chars=settings.suggestion_item_max_chars,
    )
    fallback["summary"] = fallback["summary"][: settings.suggestion_summary_max_chars]
    fallback["source"] = "rule"
    return fallback
