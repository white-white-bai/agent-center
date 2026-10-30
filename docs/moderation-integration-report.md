# 审核服务联调报告

> 日期：2026-10-30
> 范围：输入/输出审核、失败降级、鉴权与字段映射
> 状态：**协议适配与自动化验证完成；真实审核服务待提供地址/协议/密钥后联调**

## 一、结论

| 用例 | 结果 |
| --- | --- |
| 输入拦截 20 条 | 20/20 正确拒绝 |
| 输出拦截 20 条 | 20/20 正确拒绝 |
| 正常内容 | 放行 |
| 审核服务不可用 | 按默认策略**拒绝放行**，返回兜底话术 |
| 审核返回非对象 JSON | 拒绝放行 |
| 本地敏感词 | 本地命中即拒绝，不再调用远端 |
| 鉴权 | 支持 `Authorization: Bearer <key>` |
| 自定义协议 | text/stage/blocked/reason/category 字段可配置 |

聊天链路集成验证：

- 输入命中审核：SSE 返回 `AC.SAFETY.BLOCKED` + 兜底话术
- 输出命中审核：模型回答被替换为兜底话术，不输出未审内容

## 二、接口契约

请求：

```json
{"text": "待审核文本", "stage": "input|output"}
```

响应：

```json
{"blocked": true, "reason": "命中规则", "category": "SENSITIVE"}
```

配置：

```bash
AC_MODERATION_URL=http://moderation.internal/moderate
AC_MODERATION_API_KEY=...
AC_MODERATION_TIMEOUT_MS=2000
# 可选字段映射
AC_MODERATION_TEXT_FIELD=text
AC_MODERATION_STAGE_FIELD=stage
AC_MODERATION_BLOCKED_FIELD=blocked
AC_MODERATION_REASON_FIELD=reason
AC_MODERATION_CATEGORY_FIELD=category
```

## 三、验证方式

```bash
.venv\Scripts\python -m pytest -q \
  tests/unit/test_moderation_service.py \
  tests/integration/test_moderation_chat.py
```

自动化使用 `httpx.MockTransport` 模拟审核服务；另提供 `scripts/mock_moderation.py` 供本地容器联调（支持延迟与拦截词）。

## 四、待真实环境确认

1. 审核服务实际地址、鉴权方式与请求/响应字段（当前按通用契约适配）。
2. 真实服务超时/限流/5xx 表现，以及是否需要重试。
3. 审核服务不可用时业务上是否允许“放行”白名单；当前默认一律拒绝。
4. 输入/输出审核的并发容量与 P95 延迟，需纳入压测。
5. 审核日志留存与合规审计要求。
