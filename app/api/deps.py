from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext, get_tenant_context, require_admin
from app.domain.tool.executor import FunctionToolExecutor, function_tool_executor
from app.infrastructure.database.session import get_session
from app.integrations.llm.factory import get_model_router
from app.integrations.llm.router import ModelRouter

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentTenant = Annotated[TenantContext, Depends(get_tenant_context)]
AdminContext = Annotated[TenantContext, Depends(require_admin)]
ModelRouterDep = Annotated[ModelRouter, Depends(get_model_router)]
ToolExecutorDep = Annotated[FunctionToolExecutor, Depends(lambda: function_tool_executor)]
