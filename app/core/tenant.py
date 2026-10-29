from dataclasses import dataclass, field

from fastapi import Depends, Header

from app.core.exceptions import AuthError, ForbiddenError


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: str
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    data_scopes: list[str] = field(default_factory=list)

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or "admin" in self.roles


def _split_header(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


async def get_tenant_context(
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_roles: str | None = Header(default=None),
    x_permissions: str | None = Header(default=None),
    x_data_scopes: str | None = Header(default=None),
) -> TenantContext:
    """从可信认证上下文构建租户上下文。

    首期由网关注入请求头；正式接入 D02 身份认证接口后，在此处改为校验 Token 并解析身份。
    """
    if not x_tenant_id or not x_user_id:
        raise AuthError("缺少 X-Tenant-Id 或 X-User-Id")
    return TenantContext(
        tenant_id=x_tenant_id,
        user_id=x_user_id,
        roles=_split_header(x_roles),
        permissions=_split_header(x_permissions),
        data_scopes=_split_header(x_data_scopes),
    )


async def require_admin(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    """管理接口必须由管理员角色或 admin 权限调用。"""
    if not (
        ctx.has_role("admin")
        or ctx.has_permission("admin")
        or ctx.has_permission("admin:write")
    ):
        raise ForbiddenError("需要管理员权限")
    return ctx
