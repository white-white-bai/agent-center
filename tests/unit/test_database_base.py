from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.infrastructure.database.base import TenantMixin, TimestampMixin


class _LocalBase(DeclarativeBase):
    pass


class _SampleModel(_LocalBase, TenantMixin, TimestampMixin):
    __tablename__ = "sample_model_for_test"

    id: Mapped[int] = mapped_column(primary_key=True)


async def test_tenant_and_timestamp_columns_are_created() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_LocalBase.metadata.create_all)
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"]: c for c in inspect(sync_conn).get_columns("sample_model_for_test")}
        )

    assert {"tenant_id", "created_at", "updated_at"} <= set(columns)
    assert columns["tenant_id"]["nullable"] is False
    await engine.dispose()
