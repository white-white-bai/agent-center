import asyncio
import logging
import time
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics, telemetry
from app.core.exceptions import ModelUnavailableError
from app.core.tenant import TenantContext
from app.domain.model.models import ModelUsageLog
from app.integrations.llm.client import LLMClient, LLMRequest, LLMResponse, ModelUnavailable

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (asyncio.TimeoutError, ModelUnavailable)


class ModelRouter:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    async def complete(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        request: LLMRequest,
        *,
        primary_model: str,
        fallback_model: str | None = None,
        max_retries: int = 1,
        run_id: str | None = None,
        prompt_version_id: int | None = None,
    ) -> LLMResponse:
        candidates = [primary_model] + ([fallback_model] if fallback_model else [])
        last_error: Exception | None = None
        for model in candidates:
            for attempt in range(max_retries + 1):
                started = time.perf_counter()
                attributes = {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": model,
                    "ac.model.primary": primary_model,
                    "ac.model.attempt": attempt + 1,
                    "ac.model.fallback": model != primary_model,
                    "ac.run_id": run_id,
                }
                with telemetry.span("model.complete", attributes) as current:
                    try:
                        response = await asyncio.wait_for(
                            self.client.complete(replace(request, model=model)),
                            timeout=request.timeout_ms / 1000,
                        )
                    except (asyncio.TimeoutError, ModelUnavailable) as exc:
                        last_error = exc
                        status = (
                            "TIMEOUT" if isinstance(exc, asyncio.TimeoutError) else "FAILED"
                        )
                        code = (
                            "AC.LLM.TIMEOUT"
                            if isinstance(exc, asyncio.TimeoutError)
                            else "AC.LLM.UNAVAILABLE"
                        )
                        telemetry.mark_error(current, code, str(exc))
                        metrics.observe_model(
                            model,
                            status,
                            time.perf_counter() - started,
                            trace_id=telemetry.current_trace_id(),
                        )
                        logger.warning("model %s 调用失败（第 %d 次）: %s", model, attempt + 1, exc)
                        await self._log_usage(
                            session,
                            ctx,
                            model=model,
                            status=status,
                            latency_ms=int((time.perf_counter() - started) * 1000),
                            run_id=run_id,
                            prompt_version_id=prompt_version_id,
                        )
                        continue
                    current.set_attribute("gen_ai.response.model", response.model)
                    current.set_attribute("gen_ai.usage.input_tokens", response.token_input)
                    current.set_attribute("gen_ai.usage.output_tokens", response.token_output)
                    current.set_attribute("gen_ai.response.finish_reason", response.finish_reason)
                    metrics.observe_model(
                        response.model,
                        "SUCCESS",
                        time.perf_counter() - started,
                        token_input=response.token_input,
                        token_output=response.token_output,
                        trace_id=telemetry.current_trace_id(),
                    )
                    await self._log_usage(
                        session,
                        ctx,
                        model=response.model,
                        status="SUCCESS",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        token_input=response.token_input,
                        token_output=response.token_output,
                        run_id=run_id,
                        prompt_version_id=prompt_version_id,
                    )
                    if model != primary_model:
                        logger.info("模型降级生效: %s -> %s", primary_model, model)
                    return response
        raise ModelUnavailableError(f"模型调用失败: {last_error}") from last_error

    async def _log_usage(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        *,
        model: str,
        status: str,
        latency_ms: int,
        token_input: int = 0,
        token_output: int = 0,
        run_id: str | None,
        prompt_version_id: int | None,
    ) -> None:
        session.add(
            ModelUsageLog(
                tenant_id=ctx.tenant_id,
                run_id=run_id,
                model_alias=model,
                prompt_version_id=prompt_version_id,
                token_input=token_input,
                token_output=token_output,
                latency_ms=latency_ms,
                status=status,
            )
        )
        await session.commit()
