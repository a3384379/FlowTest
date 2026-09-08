# MCP Closed Loop S61/S62 验收账本

状态：S61A 已由 PR #90 合并，S61B 已由 PR #91 合并并完成合并后主线门禁；S61C～S62B 的
实现、契约和隔离定向回归已完成，待本阶段一次集中门禁、PR 复审和主线验证。不标记真实宿主/LLM
业务闭环或 GA 已完成。

## 基线与交付范围

2026-09-08 从 PR #91 合并后的主干开始，基线见 [能力审计](../mcp-capability-audit.md)。
当前开发分支为 `codex/v6-s61d-resource-discovery`，从 S61B 合并后主干创建。本轮交付
有界契约预览/提交、inspect_contract 分页、资源发现/Readiness、有限 Service Target 诊断、零接入
Skill 整合、Change Regression 分析准备、Test Plan 更新建议和 Preview Graceful Cancel，同时更新
MCP Client/Server、MCP Golden、五个 Skill、Standalone 基线与文档。工具数 42 → 50；新增 Scope 为
`mcp:contract:import`、`mcp:regression:prepare`、`mcp:test-plan:propose`，bootstrap/read 复用既有
Scope。S61B 的组织级幂等初始化已在 PR #91 闭环。
详见 [ADR 0052](../adr/0052-mcp-onboarding-connection-and-scope.md) 和
[ADR 0053](../adr/0053-mcp-bootstrap-initialization.md)、[连接指南](../operations/mcp-connection-setup.md)。

## S61B 验证记录

- PR #91 已合并，Backend、Integration、Bundle、升级回滚、源码/镜像、Compose Smoke 和 Required
  Gate 全部成功；复审无 P0/P1，两个 P2 作为后续技术债记录并完成线程收口。

- 空组织 Dry Run 不创建项目或组织级幂等回执；真实初始化要求固定组织、
  `mcp:project:bootstrap` 和 `Idempotency-Key`。同键同请求返回历史回执并标记 replay，
  同键不同请求返回冲突，不同键按组织内 `external_key` 复用项目。
- 新增 `external_key` 组织唯一约束和 `20260908_0052` Alembic/Standalone 基线；唯一约束处理
  不同键并发创建，失败的原子操作释放未完成回执，跨步骤不自动删除已创建资源。
- 环境只接受 `test`/`sandbox`，同名地址或分类冲突不覆盖；Service Target 校验项目/环境归属、
  Service 类型、Endpoint Variant、TLS 和现有出站网络策略。URL 凭据、查询/片段、明文 Header
  或 Token 均被拒绝，所有新资源写入审计。
- 定向 API 测试 `3 passed`，MCP Golden/连接 action、Skill Manifest/评测副本与 Standalone 基线
  回归通过；这些是隔离确定性证据，不替代真实宿主 MCP 或真实 LLM 验收。PR #91 集中门禁与合并后
  Required Gate 全部成功。

## S61C 验证记录（开发完成，待 PR）

- 新增 `flowtest.preview_contract_import` 与 `flowtest.commit_contract_import`，专用 Scope 为
  `mcp:contract:import`；支持批准 URL、有界 UTF-8 文档和代码证据生成的强类型 HTTP Operation。
- `persist=false` 只运行现有 Importer/Canonical Contract 预览，不创建 ImportRun；持久化预览保存加密的
  冻结内容和源摘要。Commit 只接受 `preview_id`、`source_sha256`、精确选择及期望版本，绝不重新抓取 URL。
- 纯新增接口可在明确范围内提交；已有接口更新/删除、Endpoint 地址变化要求人工确认和版本匹配。重复提交
  回到已完成回执，敏感参数、示例值、URL 凭据和超大/重复输入均 fail-closed。
- `inspect_contract` 增加真实 total、page/page_size、has_more/next_cursor/truncated、方法/路径/Service
  过滤与指定版本读取，并返回有界参数位置/required/type 和响应结构摘要。
- 定向回归覆盖 schema 严格校验、source-derived OpenAPI 转换、dry-run/冻结摘要边界、ImportService 旧
  合并兼容和 MCP 工具注册；集中 PR 门禁待本阶段完成后执行。

## S61D/S61E/S62 验证记录（实现完成，待集中门禁）

- `flowtest.find_assets` 使用项目范围内的显式 `union_all` 查询，支持 API、Workflow、Context、Proposal、
  测试资产、ImportRun、Execution 和 Change Regression；返回真实 total、稳定分页、安全摘要、版本、来源和深链。
  `inspect_project_readiness` 汇总 Contract/Endpoint/Context、业务凭据引用、只读数据库证据、Preview 环境和
  人工动作；`check_service_target` 只调用已登记 Endpoint 的现有 connectivity，并明确这是 FlowTest API Host
  检查，`worker_network_verified=false`。
- `inspect_flow_proposal`、`inspect_run_evidence` 补充 `human_actions_required`、可信 UI/执行链接、状态和
  Main/Cleanup 安全摘要；不返回 Token、请求/响应 Body、数据库行或错误明文。
- Onboarding、Integration Flow、Complete Coverage、Change-aware Regression、Triage/Repair 五个 Skill
  已接入实际 tools/list、版本/Scope 检查、零项目初始化、资源续接、Test Plan 建议、Graceful Cancel 和有界
  A/B 双提案交接；工具缺失只返回 `TOOL_UNAVAILABLE`/`SERVER_VERSION_UNSUPPORTED`，不回退浏览器、JWT、SQL 或 Docker。
- `flowtest.prepare_change_regression` 在固定 Context 前后版本上以既有 ChangeRegression/Impact/Maintenance
  服务创建分析 Run，Dry Run 不落库，正式请求使用幂等键且不执行/放行 Release；`flowtest.propose_test_plan_update`
  只创建共享 AIChangeSet 的 typed `test_plan_update` Draft，未发布依赖显式返回，人工接受后才通过
  `TestPlanService` 物化。迁移 `20260908_0053` 与 Standalone/Transfer 基线同步。
- `flowtest.cancel_preview` 仅接受当前项目的 Preview Execution，复用 `WorkflowService.request_cancel(force=false)`；
  终态和重复请求幂等，不扩大到生产或强制取消，Cleanup 状态如实返回。
- 当前定向回归：S56/S60 Skill 契约、S61D 资源发现、S62 规划、MCP SDK 注册、Golden、Standalone Runtime/Transfer
  均通过；Skill 自包含评测检查通过。该证据不替代真实 LLM Host、真实业务目标或人工 Review/Preview。

## S61A 验证记录

- 修改前的 4 个特征测试失败，确认旧 HTTP 缺失/非 Bearer 请求回落到进程账号，以及缺少连接端点。
- 新连接与配置测试覆盖机器身份、Scope、未知字段、协议版本、过期/撤销/禁用、组织禁用、用户 JWT
  拒绝、失效 Cookie、HTTP 两调用者与无凭据隔离、stdio、配置无令牌、非法参数不回显、Feature 过滤。
- 首次后端集中回归：1226 passed / 4 skipped / 1 failed，覆盖率 91.17%；唯一失败为
  `test_mcp_red_team_surface_has_no_uncontrolled_mutation_tools` 的旧精确工具清单。已将新增只读
  入口显式加入清单，保留禁止无控写入断言，修复后相关 80 项定向回归通过。
- 后续新增错误分类/令牌格式测试单独定向验证；最终完整集合以 PR Backend CI 为准，不把旧全量
  结果冒充修改后重新运行的全量结果。Ruff Format/Check、mypy、架构依赖检查均执行；最终 CI 待出。
- 前端集中检查：format、lint/TypeScript、build 通过；61 个文件、240 项测试通过，branch 80.34%。
- Onboarding Skill quick_validate、四个 Skill Manifest 契约检查、五包 Evaluation 资产同步检查通过。
- PR 复审 P1 修复：项目资产授权现在以 `service_account_id`、固定组织和 MCP scope 为边界，
  不读取创建者的 `is_system_admin` 或项目成员角色；setup 校验并拒绝敏感 URL path，避免把令牌
  写入 config_template/stdout。相关回归覆盖同组织无成员访问、跨组织 404、越权能力拒绝和
  URL 错误不回显。
- 真实 SDK Streamable HTTP 的 ASGI 传输测试通过，保持默认 Host 安全校验。进程内调用与 HTTP
  身份分别验证；这不是实际宿主或真实模型验收。Compose Playwright 由本次路径门禁 CI 执行，当前待出。

本轮没有执行实机、公司 Windows、容量或 Compact 重门禁；Windows CI 保留。没有操作用户若依
真实目标，未读取或改写用户 MCP 配置，启动时已有 RuoYi Compose 改动不进入本 PR。

## 分阶段状态

| 阶段 | 开发 | 合并/主线门禁 |
| --- | --- | --- |
| S61A 连接、权限契约 | 已完成 | PR #90 已合并，主线门禁全绿 |
| S61B 项目/环境/服务初始化 | 已完成 | PR #91 已合并，合并后门禁全绿 |
| S61C 有界契约导入 | 实现与定向回归完成 | 待本阶段集中门禁/PR |
| S61D 读取/查找/Readiness/目标诊断 | 已完成 | 待本阶段集中门禁/PR |
| S61E 零接入与生成 Skill | 已完成（真实宿主/模型未验证） | 待本阶段集中门禁/PR |
| S62A 回归准备与 TestPlan 建议 | 已完成 | 待本阶段集中门禁/PR |
| S62B 取消、结果续接与总验收 | 已完成 | 待本阶段集中门禁/PR |

## 真实模型验收单独记录

当前会话未暴露 FlowTest MCP。未用用户 JWT、通用 REST、内部 SQL、Docker/.env 管理员凭据或
浏览器登录绕开此条件。宿主连接、实际安装 Skill、真实模型从零资产生成与 A/B 执行尚未验证。
这不是认定用户没有凭据，不影响先做隔离开发；需要真实接入时才请求缺失的明确授权或资源。
不得把 Golden、SDK、ASGI 或 Compose Fixture 写成生产 MCP-only 成功。

## 当前已可用的短指令示例

```text
发现当前会话的 FlowTest MCP 工具，不读取本机凭据。
若 inspect_connection 可用，检查当前机器身份、组织、scope 和版本。
列出我已获授权的项目，报告证据缺口和下一步。
缺工具或权限时准确说明原因，不切换浏览器/JWT/SQL 补权限。
不要创建凭据、自动审核、Apply、Publish 或执行测试。
```

该例仍只展示连接与读取；S61B 的零项目初始化必须由具备明确 Scope 的 MCP 工具执行，不能由
用户手工复制 UUID 代替。S61/S62 的开发实现已完成，最终远程门禁和真实宿主/模型验收仍按上文单独记录。
