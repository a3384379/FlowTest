# AI 助手配置、评测与故障处理

## 默认边界

AI 助手默认关闭。关闭时 Web 显示说明页，其他功能不受影响。AI 只生成待审核建议，不自动发布或执行，也不能读取 Secret、创建 Credential 或修改权限。

## 配置

在生产 `.env` 中设置：

```dotenv
FLOWTEST_FEATURE_AI_ENABLED=true
FLOWTEST_AI_BASE_URL=https://ai-gateway.example/v1
FLOWTEST_AI_MODEL=approved-model
FLOWTEST_AI_API_KEY=replace-with-runtime-secret
FLOWTEST_AI_REQUEST_TIMEOUT_SECONDS=30
FLOWTEST_AI_MAX_SUGGESTIONS=20
FLOWTEST_AI_WORKER_CONCURRENCY=1
```

生产环境只接受 HTTPS 网关。API Key 只能通过运行时 Secret 注入，不能提交到 Git、写入前端或出现在问题单中。AI Worker 使用独立 `ai` 队列；调整并发后需重新验证网关限流和项目配额。

## 上线前评测

1. 执行 `uv run pytest tests/test_ai_assistant.py`，确认队列、网关、脱敏、权限、人工审核和草稿落库全部通过。
2. 离线隐私评测集位于 `backend/tests/fixtures/ai_redaction_evaluation.json`。新增敏感字段规则时必须先添加会失败的用例，再修改脱敏器。
3. 在专用测试项目中分别创建 Schema 用例、断言、Workflow 草稿和失败归因任务；人工接受、编辑和拒绝至少一项。
4. 检查审计日志包含输入摘要、模型、提示版本、Token 用量和审核结果，且不包含原始样本、Authorization 或 Provider API Key。
5. 模拟网关断网、非 200、无效 JSON 和不符合 Schema 的响应，确认任务安全失败且不创建资产。

## 故障处理

- `AI_QUEUE_UNAVAILABLE`：检查 AI Worker 心跳与 Redis 通知；任务已持久化为失败，不要直接修改数据库重放。
- `AI_GATEWAY_UNAVAILABLE` / `AI_GATEWAY_REJECTED`：检查网关连通、证书、模型权限和限流；不得把 API Key 粘贴到日志。
- `AI_RESPONSE_INVALID`：保留任务 ID、模型和提示模板版本，使用脱敏后的输入摘要复现；不要绕过本地 Schema 校验。
- 疑似敏感信息外传：立即关闭 `FLOWTEST_FEATURE_AI_ENABLED`、轮换网关密钥、导出审计证据并按安全事件流程处理。

## 回滚

关闭 Feature Flag 即可停止新任务；随后停止 AI Worker。既有 Job、Suggestion 和审计记录保留。若必须降级到迁移 `0017`，先导出审核记录，再执行 `alembic downgrade 20260811_0017`；该操作会删除 S21 AI 数据和项目样本共享开关。
