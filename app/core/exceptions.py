from typing import Any


class AppError(Exception):
    status_code = 400
    code = "AC.COMMON.BAD_REQUEST"
    message = "请求参数错误"

    def __init__(self, message: str | None = None, *, code: str | None = None, detail: Any = None) -> None:
        self.message = message or self.message
        if code:
            self.code = code
        self.detail = detail
        super().__init__(self.message)


class AuthError(AppError):
    status_code = 401
    code = "AC.AUTH.UNAUTHORIZED"
    message = "未认证或缺少可信身份信息"


class ForbiddenError(AppError):
    status_code = 403
    code = "AC.AUTH.FORBIDDEN"
    message = "无权访问该资源"


class NotFoundError(AppError):
    status_code = 404
    code = "AC.COMMON.NOT_FOUND"
    message = "资源不存在"


class ConflictError(AppError):
    status_code = 409
    code = "AC.COMMON.CONFLICT"
    message = "资源状态冲突"


class ValidationError(AppError):
    status_code = 422
    code = "AC.COMMON.VALIDATION_FAILED"
    message = "参数校验失败"


class BudgetExceededError(AppError):
    status_code = 429
    code = "AC.RUN.BUDGET_EXCEEDED"
    message = "执行预算耗尽"


class ToolTimeoutError(AppError):
    status_code = 504
    code = "AC.TOOL.TIMEOUT"
    message = "工具调用超时"


class ModelUnavailableError(AppError):
    status_code = 503
    code = "AC.LLM.UNAVAILABLE"
    message = "模型服务暂不可用"


class MCPUnavailableError(AppError):
    status_code = 502
    code = "AC.MCP.UNAVAILABLE"
    message = "MCP 服务不可用"
