from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.tenant import TenantContext
from app.domain.prompt.models import PromptTemplate, PromptVersion
from app.domain.prompt.service import can_transition, extract_variables


async def create_template(
    session: AsyncSession, ctx: TenantContext, *, code: str, name: str, layer: str = "AGENT"
) -> PromptTemplate:
    template = PromptTemplate(tenant_id=ctx.tenant_id, code=code, name=name, layer=layer)
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


async def get_template(session: AsyncSession, ctx: TenantContext, template_id: int) -> PromptTemplate:
    result = await session.execute(
        select(PromptTemplate).where(
            PromptTemplate.id == template_id, PromptTemplate.tenant_id == ctx.tenant_id
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise NotFoundError("提示词模板不存在")
    return template


async def create_draft(
    session: AsyncSession, ctx: TenantContext, template_id: int, *, content: str
) -> PromptVersion:
    await get_template(session, ctx, template_id)
    result = await session.execute(
        select(PromptVersion.version_no)
        .where(PromptVersion.template_id == template_id, PromptVersion.tenant_id == ctx.tenant_id)
        .order_by(PromptVersion.version_no.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none() or 0
    version = PromptVersion(
        tenant_id=ctx.tenant_id,
        template_id=template_id,
        version_no=latest + 1,
        content=content,
        variables_json=extract_variables(content),
        status="DRAFT",
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)
    return version


async def get_version(session: AsyncSession, ctx: TenantContext, version_id: int) -> PromptVersion:
    result = await session.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id, PromptVersion.tenant_id == ctx.tenant_id
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise NotFoundError("提示词版本不存在")
    return version


async def transition(session: AsyncSession, ctx: TenantContext, version_id: int, target: str) -> PromptVersion:
    version = await get_version(session, ctx, version_id)
    if not can_transition(version.status, target):
        raise ConflictError(f"提示词版本不能从 {version.status} 流转到 {target}")
    version.status = target
    if target == "PUBLISHED":
        version.published_at = datetime.utcnow()
        template = await get_template(session, ctx, version.template_id)
        template.current_version_id = version.id
    await session.commit()
    await session.refresh(version)
    return version


async def resolve_published_version(
    session: AsyncSession, ctx: TenantContext, version_id: int | None
) -> PromptVersion | None:
    if version_id is None:
        return None
    version = await get_version(session, ctx, version_id)
    if version.status != "PUBLISHED":
        raise ValidationError("Run 只能固定引用已发布的提示词版本")
    return version
