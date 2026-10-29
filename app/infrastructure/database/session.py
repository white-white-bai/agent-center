from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.config import get_settings
from app.core.tenant import get_current_tenant
from app.infrastructure.database.base import TenantMixin


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_guard(execute_state) -> None:
    """在会话上下文存在租户时，为所有 ORM 查询自动追加租户条件。"""
    tenant_id = get_current_tenant()
    if not tenant_id:
        return
    if not execute_state.is_select:
        return
    if execute_state.execution_options.get("skip_tenant_guard"):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


def create_engine(database_url: str, echo: bool = False) -> AsyncEngine:
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


_settings = get_settings()
engine = create_engine(_settings.database_url, echo=_settings.db_echo)
SessionFactory = create_session_factory(engine)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
