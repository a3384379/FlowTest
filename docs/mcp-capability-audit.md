# S61/S62 MCP 能力审计与实施账本

审计日期：2026-09-08。S61A 已由 PR #90 合并，S61B 已由 PR #91 合并并完成合并后 Required Gate；
S61C～S62B 的实现、契约与隔离定向回归已在当前开发分支完成，待本阶段一次集中门禁、PR 复审和主线验证；
本页为一次阶段证据，不做循环 SHA 计算。

## 实际能力，不以工具名猜测实现

基线 38 个工具由 `backend/app/mcp/server.py` 注册，契约清单在
`backend/tests/fixtures/v6_golden/mcp-contract.json`。S61A 新增连接诊断后为 39 个；S61B
新增三个受控初始化工具后为 42 个；S61C 新增契约导入工具后为 44 个；S61D/S62A/S62B 再增加 6 个，
当前注册总数为 50 个。
工具经 MCP Adapter 到应用网关，再复用领域/服务；模型不得绕过 MCP 自行调用网关 REST。

| 现有工具（省略 flowtest.） | 实际服务/能力 | 边界与缺口 |
| --- | --- | --- |
| list_projects、inspect_project、discover_services、inspect_contract | MCPReadService；项目/服务/当前契约 | 已有项目才可读取；inspect_contract 支持有界分页、方法/路径/Service/版本过滤，结构摘要不含请求值 |
| ensure_project、ensure_test_environment、ensure_service_target | MCPBootstrapService；组织级幂等初始化项目、Test/Sandbox 环境和 Service Endpoint | 仅 `mcp:project:bootstrap`；默认 Dry Run；不改成员、凭据、TLS 或出站策略；S61C 复用其资源 |
| inspect_flow、export_flowspec、validate_flowspec、diff_flowspec | 工作流读取和既有 FlowSpec 校验/导出/差异 | 非任意内部节点编辑；复杂旧图保真在 S61D 定向验收 |
| inspect_run_evidence、inspect_test_evidence | MCPReadService 脱敏执行/测试证据 | 不直接读取原始响应/DB 行；S62B 增强安全结果摘要 |
| inspect_source_evidence、inspect_entity_mapping、inspect_data_profile | Context/Evidence Adapter 视图 | 有界结构证据，不主动连接外部 Code/DB 服务 |
| begin_test_context、close_test_context、ingest_external_evidence、ingest_java_evidence、ingest_java_source_snapshot、ingest_database_evidence | TestContextService、Java/Database Evidence、静态 Provider | 有版本写入副作用，mcp:evidence:write；只接受另行授权的有界材料 |
| inspect_test_context、inspect_context_requirements | Context 读取/缺口 | 不把缺证据当作已完成，不自行创建资产 |
| plan_integration_test、validate_integration_plan、compile_integration_flowspec、explain_compiler_diagnostics | 既有确定性 Planner/Compiler | 不扩展第二套 DSL；Path/Cookie 静态值仍有显式不支持路径 |
| propose_flow_draft、inspect_flow_proposal、preview_flow_proposal | AIChangeSet/Flow Proposal/Sandbox Preview | proposal scope 与 preview scope 分开；人工 accepted + unapplied + 一次性批准，不自动 Apply/Publish |
| preview_contract_import、commit_contract_import | MCPContractImportService；批准 URL、有界文档或强类型 Operation 的统一导入管线 | `mcp:contract:import`；dry-run 不落库；持久化预览冻结 ImportRun，Commit 校验 digest/版本且不重新抓取 URL；更新/删除/Endpoint 变化需确认 |
| find_assets | MCPAssetRepository；项目内 API、Workflow、Context、Proposal、测试资产、ImportRun、Execution、Change Regression 的强类型分页发现 | `mcp:read`；单次有界类型/查询，真实 total 与稳定排序；只返回安全摘要、版本、来源和深链 |
| inspect_project_readiness | MCPDiscoveryService；汇总 Contract、Endpoint、Context、凭据引用元数据、Preview 前置条件 | `mcp:read`；区分可生成/可 Preview/人工动作；不返回凭据明文或运行快照 |
| check_service_target | 既有 ServiceTargetService connectivity 适配 | `mcp:project:bootstrap`；仅检查已登记目标，标注 API Host 检查，不能宣称 Worker 网络已验证 |
| generate_test_design、analyze_test_coverage、propose_test_design | 既有 TestDesign/覆盖分析/受控建议 | 只读生成和 mcp:write 待审核持久化，不直接更新发布计划 |
| inspect_change_impact、inspect_change_regression、inspect_context_diff、inspect_affected_flows | Impact、ChangeRegression、Context Diff、AffectedFlow | mcp:read；已有 Run 的只读 inspect，不暗中调用会同步状态的 get |
| diagnose_failure、propose_repair、propose_maintenance | FailureRepair、Maintenance + 既有 AIChangeSet | 产品缺陷保护、Patch 白名单、版本锁定；不替代正式回归执行 |
| prepare_change_regression | MCPPlanningService → ChangeRegressionService/RegressionMaintenanceService | `mcp:regression:prepare`；固定 Context 前后版本，只创建分析与待审核证据，不执行/放行/豁免 |
| propose_test_plan_update | MCPPlanningService → AIChangeSet/AIChangeItem + TestPlanService | `mcp:test-plan:propose`；只写 Draft typed `test_plan_update`，人工接受后物化，不发布/执行 |
| cancel_preview | MCPPlanningService → WorkflowService.request_cancel(force=false) | `mcp:preview:execute`；按执行 ID Graceful Cancel，保留 Cleanup；不强制取消或触碰正式运行 |

后端已有 ProjectService、Environment/Service/Endpoint、ImportService、Connectivity、TestPlan、
ChangeRegression、WorkflowCancel/Preview 能力，不新增同义系统。S61/S62 是最小授权的 MCP 适配，
不是将任意服务方法直接开放成工具。具体冻结工具和 Scope 见 ADR 0052。

## 已确认工程缺口与顺序

| 阶段 | 缺口与实现目标 | 当前状态 |
| --- | --- | --- |
| S61A | 无项目连接诊断、显式配置模板、HTTP 每调用者身份、冻结 Scope | PR #90 已合并，合并后主线门禁全绿 |
| S61B | 首个项目的组织授权/幂等、test/sandbox 环境和 Service Target | PR #91 已合并，合并后门禁全绿；2 个 P2 已记录为技术债 |
| S61C | ImportRun 冻结预览与选定纯新增提交、inspect_contract 完整分页/版本摘要 | 实现与定向回归完成，集中门禁/PR 待本轮统一执行 |
| S61D | Readiness、Find Assets、真实契约分页/版本、旧图保真、有限目标诊断 | 已完成实现与定向回归 |
| S61E | 零资产到提案 Skill、真实宿主/模型闭环与有界 A/B 编排 | Skill/Manifest/Golden 已更新；真实宿主/模型仍未验证 |
| S62A | ChangeRegression 分析准备、TestPlan 更新建议 | 已完成实现与定向回归；只生成分析/待审核 Draft |
| S62B | Preview Graceful Cancel、结果续接、安全摘要、总验收 | 已完成实现与定向回归；集中门禁/PR 待本轮统一执行 |

项目级 IdempotencyRecord 必需 project_id，故不能承载“创建第一个项目”；组织级最小存储与唯一
约束先经 ADR/迁移，再实现。机器账号有 actor 引用但 role=None，不继承创建者管理员身份。
H0 Viewer 拒绝创建规则必须保留。现有 Scope 不静默映射到通用 create_project。

## 生产边界与验收口径

当前宿主工具发现没有暴露 FlowTest MCP 工具。这只能证明本会话工具未连接，不能据此声称用户缺少
凭据；未读取真实 MCP 配置、环境凭据、Docker/.env、浏览器 Cookie。可继续开发/隔离测试，但
真实已安装 Skill + 实际模型 + 业务目标验收暂未执行。

账号签发、Review、Apply、Publish、一次性 Preview 批准仍由人类在既有产品入口完成。初始化测试
元数据的授权不等同于批准执行。目标网络与 TLS 保持现有治理；连接检查必须标注 Host/API/Worker
位置，未从 Worker 执行不得写 Worker 已验证。未知或生产环境不能伪装成 test/sandbox。

隔离数据库/ASGI/SDK/Compose 测试使用人工 Fixture，只证明代码契约；不计为真实模型闭环。
不操作用户若依真实业务数据，保留本次启动已有的 `deploy/ruoyi/compose.yaml` 改动。
无实机测试要求，保留 Windows CI；容量/Compact 重门禁仅按显式 RC 策略，不逐函数重跑。

S61A 已按集中门禁合并；S61B PR #91 的全部门禁成功后已合并，保留 2 个已记录 P2 技术债。
S61C～S62B 的代码、迁移、Skill 和契约资产已在当前分支收口；本轮会按用户要求在全部实现完成后只执行一次
集中 Backend/Frontend/契约/迁移/安全/Compose CI，再补 PR 与主线证据。S61/S62 的真实宿主、真实模型、
若依业务执行和人工审核不伪造为已通过，最终证据落入 `docs/release/mcp-closed-loop-acceptance.md`。
