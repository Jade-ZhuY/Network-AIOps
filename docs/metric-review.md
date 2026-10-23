# 查询审核与正式指标

后续已接上 [治理反馈闭环](governance-feedback.md)：问数问题自动进入治理项，审核/发布与治理记录关联，必须使用重新取数或有效澄清证据验证后关闭，回归时重开。

2026-10-20：落实治理反馈的两个最小功能：**人工判定查询结果**，以及**将审核通过的查询发布为可执行的正式指标**。不是 SQL 示例缓存，不自动修改业务 MySQL、采集字段或原始九指标目录。

## 页面怎么用

1. 在智能调查中执行第三层问题，例如 `查询 R2 昨天按平均丢包率排名前3的接口`。
2. 在右侧模型 SQL 证据卡片的“人工审核”点击 **结果正确** 或 **需要修改**，可填写意见。保存审核人、时间、版本和历史。
3. 确认正确后点击 **整理为正式指标**，填写名称、可选别名和统计口径说明。
4. 展开核对 SQL、固定参数、单位、时间和空值规则，明确勾选确认，再发布。
5. 左侧 **正式指标** 可查看定义或填入查询问题，确认设备/时间后发送：

   ```text
   查询指标「接口丢包排名前三」 R3 昨天
   ```

名称或别名均可。当前采用上述**明确的命名调用**，未声称任意自然语言到自定义指标的语义泛化。

“需要修改”记录意见，**不自动重写 SQL**；已发布的关联指标在同一事务内撤回。重新确认正确也不自动恢复，必须再次明确发布；再次发布保留历史、提升版本。

原始报告、SQL 与数据行不被审核覆盖。页面在原始报告上方单独展示当前人工结论；原始 `unverified` 表示生成时状态。新执行的正式指标证据标记 `human_reviewed`，携带指标版本和定义指纹。

## 固定口径与本次条件

| 项目 | 行为 |
|---|---|
| 源视图、输出表达式、分组、排序、业务 LIMIT | 固化为审核后的定义；运行时行预算不误作业务 Top-N |
| `value_N` 阈值 | 固定，例如 5% 保留为数字 5 |
| 原查询指定的告警级别/类型 | 固定分类条件，调用时不接受冲突值 |
| 设备、时间窗口、适用接口 | 每次明确指定，不继承原请求的绑定值 |
| 原定义未固定的级别/类型 | 对适用视图可作为本次额外过滤 |
| 结果行 | 不存入指标定义，每次重新只读查询 |

服务器解析时间、转 UTC `[start,end)`；分桶仍为 UTC，演示时钟仍为 `DEMO_NOW`。有时间列的指标要求设备与时间，快照指标不冒充历史状态。JOIN/CTE/窗口等原限制未放宽。

命名调用若缺设备/时间、附加其他计算、时间/全网范围冲突，或指标已撤回，会先澄清，不忽略要求，也不让模型重写为另一种含义的 SQL。

## 接入第一层

```text
已登录 chat / metrics.resolve
 → 名称/别名匹配
 → 校验本次请求条件
 → 绑定审核定义版本和指纹
 → 重新校验 SQL，注入请求过滤及当前租户/设备 ACL
 → 只读查询当前数据
```

这条路径不调用模型，`query_path=reviewed_metric`。`metrics.resolve` 仍只返回计划，不执行 SQL。关闭 `TEXT_TO_SQL_ENABLED` 不影响已发布指标。

内置九指标保持封闭编译器，受审自定义指标作为单独目录扩展，使用 `matched_reviewed_metrics` / `reviewed_metric_plan`，不把动态 ID 塞入原九指标枚举。启用会话后 `GET /metrics` 额外返回当前身份的 `reviewed_metrics`；`data/metric_catalog.json` 未改。

## 权限与一致性

- 首期只对**同一用户、租户、完整 Scope 指纹**可见/可用，不是全租户公共发布。工程师和管理员均只操作自己的原请求。
- 审核绑定服务端 `request_id + query_id + 证据哈希`。客户端只提交判断/说明，不能提交替换 SQL、结果行或授权范围。
- `expected_revision` / `review_revision` 防旧页面覆盖、旧审核发布。发布重试幂等；名称/别名冲突拒绝；改判和撤回事务化。
- 仅审核已经执行的第三层 SQL 证据，没有对知识回答/内置指标添加通用点赞接口。
- 发布要求当前证据已确认正确，结果非空、未截断，且可恢复为允许的单视图定义。NULL 空聚合不作有效依据；OR/NOT 混合请求条件等需要先整理。
- 执行前重新检查有效状态、版本、指纹，维持当前授权、只读、限行和超时。人工审核不等于自动证明业务正确、数据新鲜或故障根因。
- 删除原会话不自动删除独立指标定义；定义不含旧结果行，来源 ID、审核和旧版本保留，可从指标库撤回。原请求过期后调整定义需要新的查询证据。

## 存储与迁移

使用现有应用状态 PostgreSQL 的新表 `aiops_metric_governance`，与只读业务 MySQL 分离。每个用户/租户/Scope 一份 JSONB 文档；审核、发布和撤回原子提交，PostgreSQL 行锁保障跨进程写入顺序。没有启动自动建表：

```powershell
uv run python -m scripts.migrate
```

health 检查治理表是否就绪。`PERSISTENCE_BACKEND=memory` 是显式开发替身，页面提示**重启不保留审核和指标**；`none` 不开放这些会话审核接口。

首期上限：每身份 2000 条审核、每条 50 次历史、200 个指标、每指标 30 个发布版本。没有跨团队共享、批量治理、自动修复或完整指标编辑器；扩大规模时需规范化表、分页和归档，不无限扩张 JSON 文档。

单身份治理文档另设 8 MiB 容量预算，超限事务回滚，返回 409。旧版 SQL 证据若没有区分业务 LIMIT 与执行行预算的元数据，需要重新查询后再发布，避免把服务器限行意外固化为业务定义。

## API

均需现有 Bearer 身份和原请求归属。

- `GET /api/v1/requests/{request_id}/queries/{query_id}/review`
- `PUT /api/v1/requests/{request_id}/queries/{query_id}/review`

  ```json
  {"verdict":"approved","comment":"核对过采样均值、排序与单位","expected_revision":0}
  ```

  `changes_requested` 表示需要修改。

- `GET /api/v1/requests/{request_id}/queries/{query_id}/metric-candidate`：可发布性、固定口径预览。
- `POST /api/v1/requests/{request_id}/queries/{query_id}/metric`

  ```json
  {
    "label":"接口丢包排名前三",
    "aliases":["丢包Top3"],
    "description":"按设备和接口计算非空采样等权平均丢包率，降序返回前三项。",
    "review_revision":1,
    "confirm_contract":true
  }
  ```

- `GET /api/v1/metrics/reviewed?include_inactive=true`：当前身份指标和存储模式。
- `DELETE /api/v1/metrics/reviewed/{metric_id}?version=1`：撤回，不硬删除历史。

chat、请求详情、会话历史额外返回 `query_reviews`。正式指标证据位于 `evidence.reviewed_metric`，包含 ID、版本、定义指纹、审核人/时间和本次实际结果。

错误：401 未登录；404 非本人/没有可审核证据；409 版本或命名冲突/发布条件不满足；422 非法输入/夹带 SQL；503 治理存储未就绪。存储失败不假称已保存。

## 验证

```powershell
uv run pytest -q --run-mysql
uv run ruff check app tests scripts
node --check app/web/app.js
node --check app/web/metric-review.js
# PostgreSQL 服务可用且迁移完成后显式执行
uv run pytest -q tests/test_postgres_integration.py --run-postgres
```

覆盖审核、回显、过期证据/版本、并发、命名冲突、撤回/重发、跨身份隔离、拒绝客户端 SQL、去除旧设备/时间绑定、重新取数、命名澄清及权限、关闭 SQL 生成仍可执行，以及实际只读 MySQL。新增 opt-in PostgreSQL 新连接池恢复测试。

浏览器在独立本地测试实例（显式 mock 模型/数据、内存会话与测试解析器）验证两个按钮、发布弹窗、指标库、换设备查询和改判撤回，不等于生产部署或 PostgreSQL 验收。当前 PostgreSQL TCP 探测未通，迁移与真实重启恢复仍待复验。

2026-10-20 最终记录：全量 `pytest -q --run-mysql` **440 passed / 16 skipped**，54.56 秒；包含实际只读 MySQL 执行已发布指标的测试。Ruff、两个前端脚本的 Node 语法检查、`git diff --check` 通过。浏览器最新页面无控制台 error；截图保存在忽略提交的 `outputs/query-review-ui.jpg`、`outputs/reviewed-metrics-ui.jpg`。没有执行新 PostgreSQL 表迁移或重启主应用；独立 UI 测试实例用后关闭。
