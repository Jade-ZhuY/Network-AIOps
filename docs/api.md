# 第 1–8 步开发验证 API

只用于本机演示，无用户/会话持久化。服务端使用固定 demo-tenant + R1/R2/R3/R4 + netops 文档范围。

## GET /health、GET /api/v1/health

实际执行受限 SELECT 检查数据库，检查已加载知识库；200 表示 ready，503 表示依赖异常。模型 mock 可离线运行；真实模型健康仅声明 configured_not_probed，不能据此认为 LLM 可用。

## POST /api/v1/demo/analyze

```json
{"message":"查询 R2 昨天严重告警和 eth1 平均丢包率", "timezone":"Asia/Shanghai"}
```

- message 必填，去除前后空白后长度 1–4000。
- timezone 为合法 IANA 名称，缺省 Asia/Shanghai。
- 额外字段（包括 scope、session_id）返回 422。
- session_id 不存在；每次请求全新 State。
- 业务结果（成功、部分成功、证据不足、澄清、失败）通过响应 status 标明。

报告包含 summary / facts / hypotheses / next_checks / limitations / evidence_refs / time_range_utc / timezone / data_freshness / data_mode。

facts 为 `{text, evidence_refs}`；hypotheses 增加 `strength=to_verify`。Report 对所有事实、推断和总结做严格证据契约校验，不接受模型新增的数值或引用。

证据：

- rag：实际 doc_id、chunk_id、来源文件、章节/页码、文本、文档版本、更新时间、RRF 分数（非概率）。
- sql：query_id、受限 SQL、绑定参数、列名、结果行、行数/截断标志、单位、聚合口径、数据来源和新鲜度。SQL 显示用户模板；服务端另注入的租户参数不由用户指定。
- trace：请求内 Agent/工具名称、耗时、状态/错误类型；不记录 Prompt、凭据或异常原文。

## 暂未实现

`/api/v1/chat`、`/api/v1/sessions`、上传/审计管理端、SSE、前端和 Checkpoint 恢复，均位于第 9 步之后。
