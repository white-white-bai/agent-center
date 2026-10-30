# C5 推荐与摘要校准报告

> 日期：2026-10-30
> 范围：主动推荐长度/去重、摘要长度、模型输出校验、离线校准
> 状态：**代码校验与离线校准完成；真实用户样本与模型质量评测待做**

## 一、代码改进

- 摘要：
  - `AC_SUMMARY_MAX_CHARS`（默认 800）控制落库摘要长度
  - `AC_SUMMARY_PROMPT_MAX_CHARS`（默认 300）写入模型提示
  - 模型摘要超长自动截断；模型失败回退规则摘要
- 推荐：
  - `AC_SUGGESTION_MAX_ITEMS`（默认 3）
  - `AC_SUGGESTION_ITEM_MAX_CHARS`（默认 120）
  - `AC_SUGGESTION_SUMMARY_MAX_CHARS`（默认 200）
  - 空项丢弃、重复项去重、超长截断
  - 模型返回 `suggestions` 非数组时回退规则，不再逐字符迭代字符串
  - 模型摘要为空时回退首条建议

## 二、离线校准结果

数据集：`tests/fixtures/c5_cases.json`（10 个构造用例，覆盖营业执照、社保、公积金、保证金、居住证、落户、CA、残疾人补贴、空数据、重复事项）。

```bash
python scripts/calibrate_c5.py --dataset tests/fixtures/c5_cases.json
```

| 指标 | 结果 |
| --- | --- |
| 用例数 | 10 |
| 平均建议数/用例 | 0.9 |
| 单用例最多建议 | 1 |
| 建议最大长度 | 31 字（限制 120） |
| 摘要平均长度 | 24.2 字（限制 200） |
| 重复建议 | 0 |
| 预期关键词命中率 | 100%（构造数据） |

说明：本轮校准针对**规则兜底路径**，数据集为构造样本，不能代表真实用户推荐质量。

## 三、自动化验证

```bash
.venv\Scripts\python -m pytest -q \
  tests/unit/test_profile_quality.py \
  tests/integration/test_proactive_suggestions.py \
  tests/integration/test_summarizer_model.py
```

覆盖：去重、空项、超长截断、模型摘要超长截断、非数组降级。

## 四、真实评测待办

1. 提供脱敏后的真实用户画像/在办事项样本（建议 ≥100 条）。
2. 对模型建议做人工相关性标注，计算 Precision@3 / 无效率 / 重复率。
3. 校准摘要长度阈值与触发消息数，避免摘要过短丢失事实或过长占用上下文。
4. 将评测接入发布门禁（`AC_PUBLISH_REQUIRE_EVAL`）或运营看板。
5. 对比规则与模型路径的点击/采纳率，确定默认策略。
