from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt, key_version
from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.domain.tool.models import ToolCredential


async def save_credential(
    session: AsyncSession, ctx: TenantContext, *, tool_code: str, name: str, value: str
) -> ToolCredential:
    result = await session.execute(
        select(ToolCredential).where(
            ToolCredential.tenant_id == ctx.tenant_id,
            ToolCredential.tool_code == tool_code,
            ToolCredential.name == name,
        )
    )
    credential = result.scalar_one_or_none()
    ciphertext = encrypt(value)
    if credential is None:
        credential = ToolCredential(
            tenant_id=ctx.tenant_id,
            tool_code=tool_code,
            name=name,
            ciphertext=ciphertext,
            key_version=key_version(),
        )
        session.add(credential)
    else:
        credential.ciphertext = ciphertext
        credential.key_version = key_version()
    await session.commit()
    await session.refresh(credential)
    return credential


async def list_credentials(session: AsyncSession, ctx: TenantContext, tool_code: str) -> list[ToolCredential]:
    result = await session.execute(
        select(ToolCredential).where(
            ToolCredential.tenant_id == ctx.tenant_id,
            ToolCredential.tool_code == tool_code,
        )
    )
    return list(result.scalars().all())


async def reveal_credential(
    session: AsyncSession, ctx: TenantContext, *, tool_code: str, name: str
) -> str:
    result = await session.execute(
        select(ToolCredential).where(
            ToolCredential.tenant_id == ctx.tenant_id,
            ToolCredential.tool_code == tool_code,
            ToolCredential.name == name,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise NotFoundError("凭证不存在")
    return decrypt(credential.ciphertext)


async def delete_credential(session: AsyncSession, ctx: TenantContext, credential_id: int) -> None:
    result = await session.execute(
        select(ToolCredential).where(
            ToolCredential.id == credential_id, ToolCredential.tenant_id == ctx.tenant_id
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise NotFoundError("凭证不存在")
    await session.delete(credential)
    await session.commit()
