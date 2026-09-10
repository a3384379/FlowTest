# FlowTest 基础体验与轻量 MCP 验收记录

更新时间：2026-09-10

审计基线：`ea3aca8419be9d180e9c887aa0219acc460ab866`（PR #97 合并结果）

已验证实现提交：`3b9586f`（`fix: address PR 97 audit findings`）

本记录归一描述 PR #97 审计 F01—F08 的修复和本地实测结果。两份方案文档及审计报告是实施输入，不作为测试结论。验收没有访问真实开票、红冲或用户业务数据库。

## 审计问题收口

| 问题 | 修复后的契约 | 回归证据 | 结果 |
|---|---|---|---|
| F01 数组路径 | Quick 的响应路径支持对象字段与非负数组下标的受限组合，例如 `body.records[0].id`；负下标和可执行表达式仍拒绝 | `test_quick_safe_paths_support_bounded_array_indexes` 及 S51 Quick 图构造测试 | 通过 |
| F02 polling | API 节点显式保存完成条件、失败终态、最多 20 次、间隔及总时间预算；业务轮询与网络重试分离，只允许只读方法重复调用 | `pending,pending,success` 恰好 3 次；失败终态立即停止；Quick 编译后 `max_retries=0` | 通过 |
| F03 必填运行参数 | FlowSpec 与 WorkflowDefinition 持久化类型、required、nullable、说明和缺省值状态；运行与断点调试均在快照准备及业务 HTTP 前校验 | Quick 提案重读契约；缺失及类型不匹配校验；整数、数组和字符串输入区分 | 通过 |
| F04 异步保存冲突 | 保存按 workflow ID 捕获资源；响应使用服务端新 revision 重建仍在编辑的草稿；内存草稿按资源保存并参与 dirty 标记 | 工作流草稿、页签和服务回归；静态类型检查 | 通过 |
| F05 Skill 契约 | manifest 明确 `default_mode=quick`，Quick 与 Deep 工具及阶段分开；证据前置仅属于显式 Deep；OFF 不做敏感值拒绝 | `test_s56_core_rc.py`、`scripts/build_skill_evaluation.py` | 通过 |
| F06 全局工作区 | 应用壳提供按用户/项目持久化的模块标签；API 编辑、项目变量/Header 和多个工作流分别保存草稿；存储不可用时显示警告并保留当前表单或内存草稿 | App、APIWorkbench、ManagementPanels 组件测试，覆盖损坏存储、禁用存储、跨模块恢复和只读用户 | 通过 |
| F07 耗时归因 | Quick 返回互斥的 resolve、build、validate_and_stage，以及幂等事务 commit 和服务端 total；不再返回重叠的 validate/persist | S51 Quick 响应结构和非负、包含关系断言 | 通过 |
| F08 证据归一 | 本文件统一记录同一实现提交、测试层、实际结果与未验证范围 | 本文件 | 完成 |

## 后端门禁

在 `backend/` 使用 `UV_CACHE_DIR=/private/tmp/flowtest-uv-cache` 和 `uv run --no-sync` 执行：

- `ruff format --check .`：通过，555 个文件格式正确。
- `ruff check .`：通过。
- `mypy app`：通过，390 个源文件无错误。
- `pytest`：1325 passed、5 skipped、2 个既有 `PytestCollectionWarning`。
- 后端覆盖率：90.53%，达到 90% 门槛。

全量 pytest 在允许绑定本机临时测试端口的环境中执行，没有连接真实业务目标。数据库结构没有变化，因此本轮不新增 Alembic migration。

## 前端门禁

在 `frontend/` 执行：

- `pnpm format:check`：通过。
- `pnpm lint`：ESLint 与 `tsc -b` 通过。
- `pnpm test:coverage`：70 个测试文件、296 个测试通过。
- 覆盖率：Statements 85.87%、Branches 80.01%、Functions 85.47%、Lines 88.23%。
- `pnpm build`：通过。

新增回归覆盖工作区标签恢复与关闭、损坏或不可用的 localStorage、API 草稿保存后清理、项目变量草稿恢复和只读用户行为。

## Compose 与 Playwright

- `docker compose config --quiet`：通过。
- 当前源码重建 backend、frontend、worker 和 mock-target。`127.0.0.1:8080` 已被本机其他容器占用，因此复用 `/private/tmp/flowtest-compose-e2e.override.yaml` 将 mock-target 映射至 18080；相关服务最终均为 healthy。
- 为避免改动已有管理员凭据，在本机测试数据库创建专用 `audit-e2e@flowtest.dev` 系统管理员，仅用于此次 Playwright。
- Playwright 认证前置：1 passed。
- `e2e/s51-mcp-visual-proposal.spec.ts`：1 passed；可视化提案只应用到 Workflow Draft。

## 已验证边界

- Quick 提案只创建待审核草稿，`execution_status=not_run`；不会自动 preview、apply、publish 或调用真实业务。
- polling 对提交类 POST 不会重复调用。开票或红冲提交仍需单次请求，后续状态查询应建模为独立只读步骤。
- OFF 延续产品决定：不扫描、遮罩、替换或阻止已授权采集中的值，也不扩大日志或数据采集范围。
- 输入校验在业务 HTTP 之前执行；缺参或类型不匹配返回可定位的 422 错误。

## 尚未实测

- 未对真实开票/红冲系统、用户内网 Endpoint 或业务数据库执行请求。
- 未运行 Windows 安装包、升级/回滚和跨浏览器实机矩阵。
- 未完成 20 次冷热模型样本的端到端 p95、LLM 分析时间和工具往返统计；服务端阶段耗时已可用于后续采样。
- 本轮 Playwright 聚焦 S51 审阅应用路径；Quick 的数组、轮询、输入契约和耗时主要由后端单元及 ASGI 集成测试覆盖。

以上未实测项不影响本轮代码门禁结论，但在面向真实开票/红冲环境发布前仍需使用固定业务夹具补跑。
