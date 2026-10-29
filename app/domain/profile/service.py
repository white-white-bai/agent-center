from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.domain.profile.models import UserEvent, UserProfile, UserProfileTag

MAX_SUMMARY_TAGS = 8


async def get_or_create_profile(session: AsyncSession, ctx: TenantContext) -> UserProfile:
    result = await session.execute(
        select(UserProfile).where(
            UserProfile.tenant_id == ctx.tenant_id, UserProfile.user_id == ctx.user_id
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserProfile(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


async def merge_tags(session: AsyncSession, ctx: TenantContext, tags: list[dict]) -> list[UserProfileTag]:
    await get_or_create_profile(session, ctx)
    stored: list[UserProfileTag] = []
    for tag in tags:
        key = tag["key"]
        result = await session.execute(
            select(UserProfileTag).where(
                UserProfileTag.tenant_id == ctx.tenant_id,
                UserProfileTag.user_id == ctx.user_id,
                UserProfileTag.tag_key == key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = UserProfileTag(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                tag_key=key,
                tag_value=tag["value"],
                source=tag.get("source", "manual"),
                confidence=float(tag.get("confidence", 0.5)),
            )
            session.add(existing)
        else:
            existing.tag_value = tag["value"]
            existing.source = tag.get("source", existing.source)
            existing.confidence = float(tag.get("confidence", existing.confidence))
        stored.append(existing)
    await session.commit()
    return stored


async def list_tags(session: AsyncSession, ctx: TenantContext) -> list[UserProfileTag]:
    result = await session.execute(
        select(UserProfileTag)
        .where(UserProfileTag.tenant_id == ctx.tenant_id, UserProfileTag.user_id == ctx.user_id)
        .order_by(UserProfileTag.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_profile_summary(session: AsyncSession, ctx: TenantContext) -> str:
    tags = await list_tags(session, ctx)
    if not tags:
        return ""
    parts = [f"{tag.tag_key}：{tag.tag_value}" for tag in tags[:MAX_SUMMARY_TAGS]]
    return "用户画像：" + "；".join(parts)


async def get_active_matters(session: AsyncSession, ctx: TenantContext) -> list[dict]:
    result = await session.execute(
        select(UserEvent)
        .where(
            UserEvent.tenant_id == ctx.tenant_id,
            UserEvent.user_id == ctx.user_id,
            UserEvent.event_type == "matter.active",
        )
        .order_by(UserEvent.occurred_at.desc())
        .limit(10)
    )
    return [dict(event.payload_json or {}) for event in result.scalars().all()]


async def record_event(
    session: AsyncSession, ctx: TenantContext, *, event_type: str, payload: dict
) -> UserEvent:
    event = UserEvent(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        event_type=event_type,
        payload_json=payload,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event
