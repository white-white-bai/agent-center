from app.domain.agent import models as agent_models  # noqa: F401
from app.domain.evaluation import models as evaluation_models  # noqa: F401
from app.domain.knowledge import models as knowledge_models  # noqa: F401
from app.domain.memory import models as memory_models  # noqa: F401
from app.domain.model import models as model_models  # noqa: F401
from app.domain.profile import models as profile_models  # noqa: F401
from app.domain.prompt import models as prompt_models  # noqa: F401
from app.domain.session import models as session_models  # noqa: F401
from app.domain.tool import models as tool_models  # noqa: F401
from app.infrastructure.database.base import Base

__all__ = ["Base", "create_all", "drop_all"]


async def create_all(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
