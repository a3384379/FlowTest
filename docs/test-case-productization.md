# 测试用例产品化实现记录

## 使用路径

在“测试用例”中保存流程、版本策略、环境、测试变量与请求头。草稿可以反复编辑；发布时将流程版本固定在不可变的用例版本中。直接运行时必须选择已发布版本，或明确确认“发布已保存草稿并运行”。后者只发布服务器中已保存的草稿，草稿校验值过期时返回冲突，需要重新加载。两种运行均走现有工作流执行器，不创建隐藏测试计划。

列表的“最近运行”按用例来源展示直接运行和计划运行，并可跳转到工作流执行详情。用例加入已有计划时固定所选用例版本；后续发布新版本不会改写计划目标。套件成员也可固定各自的用例版本，修改套件名称等元数据不会升级成员。

契约自动化位于“契约中心”的独立分区，旧测试用例页面的 `?type=contracts` 地址跳转到该分区。旧用例路由和旧 MCP 工具名称保持兼容。现有 MCP 用例草稿使用 `TestCaseDefinitionInput`，已有变量、请求头和流程版本字段；计划成员变更仍经人工审核提案，不开放自动执行工具。

## API 与数据

- `POST /api/v1/projects/{project_id}/test-cases/{case_id}/runs`：请求体使用 `source=published` 与 `version`，或 `source=draft`、`publish_draft=true` 与 `expected_draft_fingerprint`；必须带 `Idempotency-Key`。返回 202 和真实执行 ID、用例/流程版本及来源。
- `GET /api/v1/projects/{project_id}/test-cases/runs/latest?case_ids=...`：批量查询当前页用例的最近运行；单次最多 100 个 ID。新运行读取执行来源字段；迁移前计划运行通过已有 `TestPlanRunItem` 与执行记录关联，不从工作流 ID 或名称猜测用例。
- `POST /api/v1/projects/{project_id}/test-plans/{plan_id}/items`：调用既有 `TestPlanService.add_item`，使用 `target_type=case`、`target_id` 和固定 `target_version`。
- Alembic `20260928_0062` 给执行记录增加可空来源字段、约束与索引，旧记录无需阻塞式回填。升级前端和后端前须先执行迁移。回滚应用入口不删除已有来源数据；若要执行降级迁移，应先备份新增字段，因为降级会删除这些字段。

## 验证边界

本记录说明实现行为，不代表远端 CI、Compose 端到端、生产网络策略或发布验收已通过。完整验收需在目标部署中执行迁移和模块 E2E，并检查执行队列、Worker、执行详情及契约页面。
