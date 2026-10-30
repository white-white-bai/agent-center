# Dify 知识迁移适配报告

> 日期：2026-10-30
> 范围：Dify 数据集文档/分段导入、同步任务执行、断点与重试
> 状态：**适配器与自动化验证完成；真实试点数据待提供**

## 一、已完成

- 新增 `dify_fetcher`：按 dataset_id 拉取 Dify 文档与分段，转换为知识库文档
  - 文档编码：`dify:{dataset_id}:{document_id}`
  - 标题：Dify 文档名称；内容：分段按顺序拼接
  - 支持文档/分段分页，空分段文档跳过
- 同步任务支持 `sourceType=DIFY`，复用现有断点、幂等与失败重试
- 新增 `POST /api/v1/admin/knowledge-sync-tasks/{id}/run`，可手动执行/续跑同步任务
- 配置：
  - `AC_DIFY_BASE_URL`
  - `AC_DIFY_API_KEY`
  - `AC_DIFY_TIMEOUT_MS`（默认 15000）
  - `AC_DIFY_PAGE_SIZE`（默认 100）

## 二、使用示例

```bash
# 1. 创建知识空间
curl -X POST http://127.0.0.1:8000/api/v1/admin/knowledge-spaces \
  -H "X-Tenant-Id: t1" -H "X-User-Id: admin" -H "X-Roles: admin" \
  -H "Content-Type: application/json" \
  -d '{"code":"dify_kb","name":"Dify 迁移知识","domainCode":"district_service"}'

# 2. 创建 Dify 同步任务（sourceRef = dataset_id）
curl -X POST http://127.0.0.1:8000/api/v1/admin/knowledge-sync-tasks \
  -H "X-Tenant-Id: t1" -H "X-User-Id: admin" -H "X-Roles: admin" \
  -H "Content-Type: application/json" \
  -d '{"spaceId":1,"sourceType":"DIFY","sourceRef":"<dataset_id>"}'

# 3. 执行（失败可重复调用，checkpoint 幂等续跑）
curl -X POST http://127.0.0.1:8000/api/v1/admin/knowledge-sync-tasks/1/run \
  -H "X-Tenant-Id: t1" -H "X-User-Id: admin" -H "X-Roles: admin"
```

## 三、自动化验证

```bash
.venv\Scripts\python -m pytest -q \
  tests/unit/test_dify_fetcher.py \
  tests/integration/test_dify_sync.py
```

覆盖：

- 文档/分段分页与内容拼接
- 空分段文档跳过
- Authorization Header
- 同步任务执行、checkpoint、重复执行幂等
- 导入后知识检索命中

## 四、真实试点待办（A3）

1. 提供 Dify 地址、Dataset API Key、1–2 个试点 dataset（50+ 文档）。
2. 抽样 30 题核对引用准确率 ≥ 90%；本仓库暂无真实业务问答集。
3. 验证同步失败重试与断点续跑（可用网络故障注入）。
4. Dify chatflow 作为工具（`dify.chatflow.invoke`）尚未接入；当前只完成知识库迁移。
5. 迁移期间双写/灰度策略与回滚方案需结合现网 chatflow 评估。
