from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext, get_tenant_context
from app.infrastructure.database.session import get_session

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentTenant = Annotated[TenantContext, Depends(get_tenant_context)]
