from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.infrastructure.database.registry import Base, create_all

EXPECTED_TABLES = {
    "agent_definition",
    "agent_version",
    "prompt_template",
    "prompt_version",
    "prompt_binding",
    "conversation",
    "conversation_turn",
    "message",
    "run",
    "run_step",
    "run_checkpoint",
    "citation",
    "tool_definition",
    "tool_binding",
    "tool_invoke_log",
    "tool_idempotency_record",
    "tool_confirmation",
    "memory_item",
    "memory_episode",
    "memory_embedding",
    "user_profile",
    "user_profile_tag",
    "user_event",
    "knowledge_space",
    "knowledge_document",
    "knowledge_chunk",
    "knowledge_route_rule",
    "knowledge_sync_task",
    "model_provider",
    "model_route_policy",
    "model_usage_log",
    "eval_dataset",
    "eval_case",
    "eval_run",
    "eval_result",
    "feedback",
    "badcase",
    "audit_log",
    "notification",
    "run_event",
}


async def test_all_tables_are_created() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

    assert tables == EXPECTED_TABLES
    await engine.dispose()
