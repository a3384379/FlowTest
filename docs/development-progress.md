# FlowTest 开发进度

最后更新：2026-09-05（Asia/Shanghai）
状态：V5 功能主线与 Post-Merge H0 Hotfix 已合并；Main Ruleset 与 Required Gate 已生效。V6.0 Core
已完成 S48～S56、H1 实现及主线验收，S56 Flagship Skill、Evaluation、Compatibility 与 RC Evidence
已由 PR #67 普通 Squash Merge；GitHub Codex 最新复审 P0/P1 为 0，普通 PR CI、显式 RC 重门禁及合并后
Main Push 全部成功，`V6_RC_READY=YES`。S52 External Evidence Adapter、Entity Mapping 与 Java/Spring POC
已由 PR #58 普通 Squash Merge，Evidence Closure PR #59 也已普通 Squash Merge 且 Main Push Required Gate
成功。S53 Data Recipe、Cross-API Oracle 与 DB Read Oracle 已由 PR #60 普通 Squash Merge，最终
P0/P1 为 0，精确 Head 与 Merge 后 Main Push 七项门禁全部成功；S53 Evidence Closure 也已
普通合并且 Main Push Required Gate 成功。S54 Cleanup / Compensation Runtime 已由 PR #62 普通 Squash Merge，
最终 PR 与 Merge 后 Main Push 七项门禁全部成功。H1 真实 Key Rotation 已由 PR #63 普通 Squash Merge，
最终 P0/P1 为 0，PR 与 Merge 后 Main Push 七项门禁全部成功。S55 Sandbox Preview Beta 已由 PR #64
普通 Squash Merge，合并后 Main 七项门禁全部成功。跨阶段最终审计 PR #69 已清除全部
P0/P1，最终候选七项门禁全绿并普通 Squash Merge；合并后 Main 七项门禁也全部成功。当前分支
Migration/Standalone 单 Head 为 `20260831_0051`。V6 RC 候选自动化证据已闭环，尚未创建正式
Tag/Release，连续 RC、安全审批和人工签署等 GA 外部门槛仍未满足，
`GA_READY=NO`。
V6.1 前置阶段 S57.0 已按三个独立 PR 完成：PR #71 收口 Planner/Compiler/Data 正确性，PR #72
收口 Java Evidence 正确性，PR #73 收口 Governance/Evaluation/Skill Flow；三个 PR 最终复审均为
P0=`0`、P1=`0`，Required Gate 全绿并普通 Squash Merge。原 12 项已接受 P2 中，10 项代码、契约与
流程正确性问题已经关闭；Context Inspector UI 纳入 S57 产品化，Skill 自包含 Evaluation Assets 最迟在
S60 收口。当前后续顺序固定为 S57.0 → S57 → S58 → S59 → S60，不把 Change Maintenance 提前塞入
S58。完整记录见 [S57.0 Foundation Correctness 验收](release/v6-s57-0-foundation-correctness.md)。
S57 Built-in Java/Spring Provider 已由 PR #75 普通 Squash Merge；最终复审 P0=`0`、P1=`0`，1 项 MCP
省略必填参数错误信封 P2 已按策略接受，Required Gate 全绿。State Knowledge 已由 PR #76 普通 Squash
Merge；最终复审 P0=`0`、P1=`0`，1 项 Java 全限定名 Token P2 已按策略接受，Required Gate 与 Compose
Playwright 均全绿。Context Inspector 已由 PR #77 通过集中门禁、Compose Playwright 与 Required Gate 后普通
Squash Merge，S57 已全部完成。S58 Failure Diagnosis 与 Repair Proposal 已由 PR #78 普通 Squash Merge；
最终复审 P0=`0`、P1=`0`，精确 Head 与 Merge 后 Main Push 七项门禁全部成功。S58 保留 3 项必须在
S59 自动 Patch 前收口的 P2，完整证据见
[S58 Failure Diagnosis 与 Repair Proposal 验收](release/v6-s58-failure-repair.md)。
历史记录：V5 S47.1 已补齐 Canonical Contract、位置物化、Evidence Fusion、FlowSpec
版本固定、测试语义覆盖、Evidence 脱敏、5xx 归因和 Migration truth；本轮完整门禁证据见专项记录。
H1 Key Rotation 已完成代码与主线验收，但 H2 外部运行证据与人工签署仍未完成，因此仍不是 GA Ready；
S30 Failure Intelligence 与 S31 Release Gate/全局搜索已分别通过
PR #33/#34 五项 CI 并 squash 合并。V2→V3 原地升级/回滚小阶段已完成真实资产执行、
MinIO 哈希验证及 PR #35 远程 Upgrade/Security CI；S31 页面产品化的独立服务目录、
项目导航和全局搜索深链小阶段已完成本地及 PR #36 远程验收，质量指挥中心小阶段已完成本地及
PR #37 远程源码验收。用户已授权提前进入 V4，S32～S36 小型化、离线分发、资源/兼容基线、隐私安全诊断、回滚证明和事务式升级已完成本地真实验收，PR #38 的六项远程 CI 亦全部通过。Standalone PR #39 的 Windows Bundle、Backend、Compose Smoke、Security、Upgrade 六类共七项远程检查也已在 `bed1047` 全部通过。72 小时公司试点和人工签署待执行。
`v2.0.0`、`v3.0.0` 正式标签仍分别受真实部署与连续 14 天 RC 观察门槛约束。

## 当前验收策略：实机测试不再作为门槛（2026-09-05）

- 按用户最新决定，当前及后续版本均不要求实机测试，包括公司 Windows 实机长时测试；不以缺少
  这类证据阻止后续开发或验收，也不再安排这类测试。
- 该项状态为“不要求”，不是“已执行通过”。历史阶段记录保留当时事实，本节覆盖其中已过时的
  实机测试前置要求。
- Windows 自动打包与 CI、后端/前端自动化测试、Compose Playwright 继续保留；连续 RC 观察、
  外部恢复演练、安全审批、生产发布授权及人工签署不因本次决定自动豁免或视为完成。

## 已完成实现并合并：V6.1 S57.0 Foundation Correctness

- PR #71 修复对象型 JSON Body Mapping、Scenario Path/Cookie 保留、Synthetic Variable 唯一性、
  Constant/Existing-safe-record DB Read 来源和 Plan v1 `setup_api` 兼容。
- PR #72 将 Java 结构字段与 DTO Wire 字段分离，按 Jackson 可见性处理私有成员，并正确区分
  `@RestController`、普通 `@Controller`、`@ResponseBody` 与 `ResponseEntity`；JPA 结构字段不再被
  JSON 过滤误删。
- PR #73 将 Project/Context 授权与校验前移到 Idempotency Claim 之前；Evaluation 硬门禁使用精确未
  舍入比例；Sandbox Preview 前必须重新确认 Proposal 已接受且 `applied=false`。
- 三个 PR 均在最终复审清除 P0/P1 后普通合并。普通 PR 只运行一次集中门禁，Compact 与容量门禁保持
  显式 RC 路径，不因 P2 继续触发修复—全门禁循环。
- 新复审发现的 4 项 P2 与原 12 项分开记录：`previous_step` 跨来源变量冲突、Body 嵌套路径预检、
  Lombok `@FieldDefaults`、异步响应 Wrapper。它们不改变“原 10 项正确性 P2 已关闭”的事实，也不
  阻断 S57。
- 后续阶段：S57 正式化 Built-in Java/Spring Provider、State Knowledge 与 Context Inspector；S58 才
  进入 Failure Diagnosis/Repair；S59 为 Change-aware Maintenance；S60 收口完整 Skills 与独立评测包。

## 已完成实现并合并：V6.1 S57

- PR #75 已交付固定身份 `flowtest-java-spring@1.0.0`、HTTP/MCP 源码快照入口、有界静态分析、授权前置、
  脱敏错误边界和不保存原始源码的 Evidence Ingest；完整本地门禁与远程 Required Gate 已通过。
- PR #76 已交付 State Knowledge 的确定性重建、Evidence Reference、保守命名关联、State Candidate 与
  RuoYi Golden；最终复审 P0=`0`、P1=`0`，普通合并后 Main Required Gate 全绿。
- Context Revision 现在从已持久化 Java/Database Typed Evidence 派生 Operation、DTO/Field、Service/Feign、
  Repository、Entity、Table/Column、Validation、State Candidate、Exception 与 Event 节点。
- 显式证据关系与 `may_use_repository` / `may_map_entity` 保守命名关联分离；Request/Response DTO 方向不混淆。
- 初始用户 Knowledge 原样保留，FlowTest 生成图可重复重建并进入 Revision Fingerprint；500 Node、1000 Edge
  与 50 Fact 上限保持 Fail Closed，不保存或执行目标代码。
- 真实本地 RuoYi 固定 Revision 已验证
  `Route → DTO → Service → Mapper/Entity → Table`；CI 使用同结构强类型 Fixture。
- Context Inspector 使用项目用户 Read 授权展示当前 Revision、Completeness/Missing、Conflict、Provider
  Finding、State Knowledge 与同 Revision Flow Proposal；不扩大 MCP Scope，不建立平行生命周期，过期状态
  只读计算。
- PR #77 集中门禁：后端 Format/Ruff/mypy 全绿，pytest `997 passed, 4 skipped`、覆盖率 `90.89%`；前端
  Format/ESLint/TypeScript/Build 全绿，Vitest `227 passed`、Branch Coverage `80%`；Compose 中 Context →
  Built-in Java Evidence → State Candidate → Flow Proposal 深链 Playwright `2 passed`。PR #77 与合并后
  Required Gate 均通过，S57 已完成。

## 已完成实现并合并：V6.1 S58 Failure Diagnosis 与 Repair Proposal

- 新增版本化 Failure Diagnosis，基于终态执行和脱敏节点证据确定性分类；Product Defect Guard 禁止创建任何
  测试 Repair，环境、网络、认证、超时和未知故障也不会因 Cleanup 失败获得测试修改权限。
- Binding/Data/Cleanup/Contract Drift/Oracle 使用严格 FlowSpec 字段白名单；Schema 切换、空 Patch、跨类型修改
  Fail Closed，Oracle 变化要求显式确认可能弱化断言。
- Repair Proposal 复用现有 FlowSpec `AIChangeSet`，绑定目标草稿 Revision 与 Ready Context Revision；授权、
  Context、敏感输入和 Patch Scope 校验在 Idempotency Claim 前完成，Source Snapshot 只保存结构化诊断与来源。
- Web 已接入“执行历史 → 失败诊断 → 受限 Patch → Proposal Review”，创建后复用现有 Accepted + Fresh
  One-time Sandbox Preview Approval 路径完成 Re-preview，不建立第二套审批或执行生命周期。
- ADR 0048 已固定安全边界。集中门禁后端 Format/Ruff/mypy 全绿，pytest `1008 passed, 4 skipped`、覆盖率
  `90.94%`；前端 Format/ESLint/TypeScript/Build 全绿，Vitest `230 passed`、Branch Coverage `80.04%`。
- 最新 Compose 镜像上的管理员初始化与“失败诊断 → 受限 Repair Proposal → 人工接受 → 单次审批
  Re-preview”Playwright `2 passed`。
- PR #78 最终复审 P0=`0`、P1=`0`，精确 Head 与 Merge 后 Main Push 的 Backend、Frontend、Security、
  Compose、Windows、Upgrade 与 Required Gate 全部成功，随后普通 Squash Merge。
- S58 已知 3 项 P2 为统一 Proposal Discovery、Capability Node Binding Repair 与 Cleanup Failure 独立分类；
  `version_strategy` 锁定作为独立 S59.0 Hardening。它们不改变 S58 的合并结论，但必须在 S59 自动
  Flow Patch 前完成。
- S58 Evidence Closure PR #79 已普通 Squash Merge，Closure PR 与合并后 Main 的路径选择门禁均成功；
  S59.0 正式基线为 `989711c360ffaec19dc155b86fbeeebb0cf1c0f8`。

## 已完成实现并合并：V6.2 S59.0 Patch Correctness

- Cleanup Failure 使用独立分类开放 Repair；Capability Binding 纳入严格 Node Binding 白名单；Contract Drift
  锁定 `version_strategy`。
- `previous_step` 跨来源变量冲突、Body Mapping 完整嵌套路径和 Java 全限定引用 Token 已收口。
- 新增 7 个原缺陷触发回归，四个相关测试文件 `62 passed`；后端全仓 Ruff/Mypy 通过，全量 Pytest
  `1019 passed, 4 skipped`，Coverage `90.94%`。
- PR #80 最终复审 P0=`0`、P1=`0`，精确 Head Required Gate 全绿并普通 Squash Merge。合并后 Backend
  CI 暴露测试把随机 `trace_id` 中偶然出现的 `abc` 误判为 Secret 泄漏；Hotfix PR #81 仅排除
  `trace_id` 后继续扫描完整错误 Envelope，复审 P0=`0`、P1=`0` 且精确 Head 全绿后普通合并。
- Patch Correctness 已闭环，后续 Unified Proposal Discovery 从合并后的 Main 创建独立分支。完整记录见
  [S59.0 Patch Correctness](release/v6-s59-0-patch-correctness.md)。

## 已完成实现并合并：V6.2 S59.0 Unified Proposal Discovery

- 新增统一 Proposal 游标接口，结构化返回 `mcp`、`repair`、`maintenance`、`import` 来源；旧 MCP
  接口继续只返回 `mcp://`，保持兼容。
- Flow Proposal Review Dialog 不再过滤为 MCP-only，Repair Proposal 关闭后可从同一列表重新发现；
  后续 Maintenance Proposal 复用同一 AIChangeSet、Review、Apply 与 Preview 生命周期。
- 后端 Format/Ruff/mypy 全绿，Pytest `1019 passed, 4 skipped`、Coverage `90.94%`；前端
  Format/ESLint/Build 全绿，Vitest `230 passed`、Branch Coverage `80.01%`。
- PR #82 已普通合并，PR 最终门禁与合并后 main 七项工作流均成功。复审 P0=0、P1=0，接受一项
  来源标签可信性 P2：需在 S59C 依据可信 Provenance 分类，线程关闭不表示代码已修复。完整设计见
  [S59.0 Unified Proposal Discovery](release/v6-s59-0-unified-proposal-discovery.md)。

## 开发中：V6.2 S59C Maintenance Proposal

- 从 S59B 合并后全绿 main 开始，分支 `codex/v6-s59c-maintenance-proposals`；复用既有
  AIChangeSet、人工 Review、Sandbox Preview 和 Apply Draft，不新建维护状态机。
- 同一 PR 先收口 PR #82 来源标签可信性、PR #84 显式 Kafka `consumes` 和请求级分析预算三项 P2。
  来源依据服务端 Provenance 分类，不信任调用方 `source_ref`；分析增加总节点、身份解析和比较预算。
- 维护请求先校验项目编辑权限、敏感值、当前 Context、目标草稿、精确影响证据与 Patch 白名单，再创建
  幂等记录；持久化时重新校验，Apply 继续验证来源 Context。启发式不授予 Patch 权限。
- 现有审核窗口增加维护来源、前后 Context、影响引用和未覆盖诊断；不自动接受、应用、发布或生产执行。
- 集中验收：后端 1097 passed / 4 skipped、覆盖率 91.04%；前端 232 项通过、分支覆盖率 80.17%；
  格式、Lint、类型和构建全绿。隔离 Compose 浏览器验证人工接受后的实际 Preview 与 Cleanup 均 passed。
  当前待 PR 复审、远程门禁和普通合并，不提前标记完成。详见
  [S59C Maintenance Proposal](release/v6-s59c-maintenance-proposals.md)。
- PR #85 首次复审的 3 项 P1 与 1 项 P2 已集中修复：边差异保留启发式强度、Binding 固定拓扑、
  提案/幂等原子提交、Context 范围授权前置。修复后后端 1113 passed / 4 skipped；额外 MCP/Repair 原子
  提交兼容回归 34 项通过。等待新候选复审和 Required Gate，不以本地通过替代合并条件。
- S59D 后续才将 Diff、Affected Flow、维护提案接入现有 Change Regression Snapshot v4 和页面。

## 已合并并完成 main 门禁：V6.2 S59B Affected Flow

- S59A PR #83 已普通合并，合并后 main Required Gate 成功；从该全绿基线继续 S59B。
- 新增授权只读 Affected Flow 接口，复用现有 Impact 选择、Context 历史比较与 Change Regression
  Operation Identity 解析；不新增表、页面或维护状态机。
- 区分精确实例、Portable 与候选匹配；固定版本缺失不回退 current，启发式关系不授予 Patch 权限。
- 本地集中验收通过：后端 1071 passed / 4 skipped、覆盖率 91.01%；前端 230 项通过、分支覆盖率
  80.01%；格式、Lint、类型与构建检查成功。PR #84 已普通 Squash 合并，最终 PR 与合并后 main 的
  Backend、Windows、Upgrade、Security、Compose、Required Gate 均成功。
  最终复审 P0=0、P1=0，显式 `consumes` 与请求级预算两项 P2 在合并时接受，修复纳入 S59C。
  后续为 S59C Maintenance Proposal、S59D 集成。
  设计与边界见 [S59B Affected Flow](release/v6-s59b-affected-flow.md)。

## 已合并并完成 main 门禁：V6.2 S59A Context / Knowledge Diff

- 从 S59.0 全绿 main 创建独立分支，已实现版本化纯领域差异与 Context Inspector 历史版本只读接口。
- 覆盖 Evidence、Provider/来源版本、Completeness、Conflict、State Knowledge Node/Edge/State Candidate；
  Diff 只报告结构化差异，不复制源码、原始行或节点值，也不授予自动 Patch 权限。
- 顺序为 S59A Diff → S59B Affected Flow → S59C Maintenance Proposal → S59D 既有 Change Regression
  集成。阶段证据见 [S59A Context / Knowledge Diff](release/v6-s59a-context-knowledge-diff.md)。
- 本地后端格式、Lint、类型检查通过；全量测试 1032 passed / 4 skipped，覆盖率 90.95%。
  PR #83 最终候选复审无未解决行内线程，子工作流与 Required Gate 均成功后普通 Squash 合并。
  合并后 main 的 Backend/Windows/Upgrade/Security/Compose 与 Required Gate 全部成功，
  Required Gate Controller 为 `33957102399`。未绕过门禁；S59A 完成不代表整个 S59 已完成。

## 已完成实现并合并：V6 Core 跨阶段最终审计

- PR #69 统一修正 FlowSpec 跨实例 Service/Operation Identity、历史 Fingerprint 兼容、
  Change Regression Frozen Identity，并通过 `20260831_0051` 回填 API Version Service Identity。
- MCP Flow Proposal 现在会在持久化前检查递归数组/对象、参数、字段映射、断言/条件、
  Extract 目标与完整 JMESPath AST 中的 Secret/Credential/PII 字面量；动态路径与
  `secret://` 引用保持允许。
- 最新 GitHub `@codex review` 未发现重大问题，P0=`0`、P1=`0`。PR #38～#69 共 32 个 PR
  的未解决 Review Thread 统一核对为 `0`；历史 P1 标注为由 #69 修复，P2 接受为
  V6.1 技术债。
- #69 最终 Backend、Frontend、Security、Compose、Windows、Upgrade 与 Required Gate 全部
  Success，随后普通 Squash Merge；合并后 Main 的同类七项门禁也全部 Success。未使用
  Admin/Bypass/Force Push/Direct Main Push。
- 完整证据见 [V6 Core 最终验收报告](release/v6-core-final-acceptance.md)。

## 已完成实现与定向验收：V6 S56 Flagship Skill、Evaluation 与 RC Closure

### Implemented

- 新增可安装 `flowtest-generate-integration-flow@1.0.0-rc.1`，固定 MCP 最小版本、Tools/Scopes、外部
  Code/DB MCP 只读边界、Human Approval、Stop Conditions、Security Rules、Examples 与 Changelog。
- 完整链路覆盖 Project → Context → Missing Evidence → External Evidence → Plan → Compile → Dry Run →
  Proposal → Visual Review，并将 Sandbox Preview 保持为用户显式请求的一次性审批分支。
- 扩展模型无关 Golden Evaluation：Operation `3/3`、Binding `2/3`，以及 Compiler/Preview/Conflict/
  Static 与九项零事件安全门槛；空分母失败关闭，不伪造 95% Accuracy。
- 新增 Skill Contract、Evidence Ref 解析和 Baseline 一致性测试；所有 pytest Evidence 必须指向真实函数。
- CI Bootstrap PR #65/#66 已普通合并并恢复唯一 Required Gate；普通变更跳过 Compact/容量重门禁，
  `skills/**` 仍触发 Backend Skill Contract 与 Security；复审清除 P0/P1 后用
  `run_rc_gates=true` 显式执行，门槛没有删除或弱化。

### 当前证据

- Skill Creator Validation：PASS；S56 Skill/Evaluation + V6 Golden：`17 passed`；S48～S55 跨阶段
  Evidence/Compiler/Stale/Conflict/MCP/Preview/Cleanup 定向回归：`26 passed`；Ruff/Mypy/Evaluator：PASS。
- PR #67 最新 GitHub Codex Review：P0=`0`、P1=`0`、P2=`3`；P2 已按用户批准的合并策略记录为
  Remaining Risk，不阻塞 RC。
- PR #67 普通 Remote CI、显式 `run_rc_gates=true` RC Run `33314854497`、普通 Squash Merge 与合并后
  Main Push 全部 Success；Head/Merge Tree 完全一致，`V6_RC_READY=YES`。
- 连续 RC、公司实机、安全审批和人工签署不属于已完成证据，`GA_READY=NO`。

## 已完成实现与定向验收：V6 S55 Sandbox Preview Beta

### Implemented

- Preview 复用现有 Workflow Snapshot、Execution、Scheduler、Runner、Checkpoint 与 Report；
  `run_purpose=preview` 明确绑定 Proposal、Context、Environment、一次性 Approval 和 Budget。
- Environment 新增 `test/sandbox/staging/production/unclassified` 分类，仅 Test/Sandbox 允许预览，
  Production 使用独立错误码硬拒绝。
- Approval 绑定 Organization、Project、Proposal/Context Fingerprint、Actor/Service Account、Environment、
  Budget 与过期时间；数据库行锁与消费状态阻断 Replay。
- 默认硬上限为 100 Nodes、50 Requests、20 Dataset Rows、5 Parallelism、600 Seconds；主/清理阶段
  共用请求预算，恢复执行会扣除既有 Checkpoint 消耗。
- 缺少 Cleanup、未接受或 Stale Proposal、过期 Context、未决 Blocker、无 Scope、跨租户、未配置 Secret、
  不受支持节点及出站策略失败均 Fail Closed。
- Proposal Mode 可创建一次性 Approval、启动 Preview、轮询 Live Node Status，并展示 Binding、Assert、
  Cleanup、Budget、Redactions、Trace 与 Approval Evidence；不提供 Production 选项。
- MCP 新增 `flowtest.preview_flow_proposal`，仅 `mcp:preview:execute` 服务账号可以消费为其签发的 Approval。

### 当前证据

- 后端 S55 真实链路覆盖人工接受、Production 硬拒绝、Sandbox 执行、幂等重放、Approval Replay 拒绝、
  Main/Cleanup 实际请求及请求预算 Evidence；S55 + S51 定向集 `4 passed`。
- 前端 Proposal Mode 定向集 `7 passed`，TypeScript、ESLint 与 Prettier 通过；MCP SDK、GA Red Team 与
  golden contract 定向集 `3 passed`。
- 受影响后端 20 个模块 mypy 通过；隔离 PostgreSQL 完成 `0049→0050→0049→0050`，临时库已删除。
- PR #64 已完成 GitHub Codex Review、普通 CI、普通 Squash Merge 与 Merge 后 Main 七项门禁；
  S55 Beta Exit 已满足并进入 S56。
- 完整边界与证据见 [S55 Release Evidence](release/v6-s55-sandbox-preview.md)。

## 已合并并通过主线验收：V6 S54 Cleanup / Compensation Runtime

### Implemented

- Workflow 与 FlowSpec v2 原生区分 Main/Cleanup Phase，支持条件激活、关联 Main Node、
  Required/Best-effort、独立 Timeout/Retry/Request Budget 和反向清理顺序。
- Scheduler 不可变地保留 Main Result；Graceful Cancel 继续 Cleanup，Force Cancel 需显式原因并
  可按快照策略跳过。Execution、Node/Durable Checkpoint、Runner Ack 与 Report 已完成持久化。
- S50 Cleanup Requirement 不再标记为 Deferred，可完整编译、Review、Apply 并以 FlowSpec v2
  再导出。Web 分离展示 Main/Cleanup Status 与 Node Phase。

### 验收结果

- S54 后端定向集 `85 passed`，兼容回归 `47 passed`，前端相关测试 `6 passed`；
  Ruff、Mypy、TypeScript 与隔离 PostgreSQL Migration 升级/回滚/再升级通过。
- 五轮复审的 14 个 P1 已完成 Force Cancel Policy、Reclaim Budget、Best-effort
  Fail-fast、Main Request/Runtime Budget、非 API Cleanup Timeout、持久化 Runtime/Request
  Reservation、预算拒绝激活语义、取消终态 Reservation、Standalone 持久化与
  Policy-only v2 导出、Main Phase 完整终态标记与 Capability 请求计费定向修复；
  修复后 S54 合并定向集 `113 passed`。
- PR #62 最终复审 P0/P1 为 0，已普通 Squash Merge；PR 精确 Head 与 Merge 后 Main Push 的
  Backend、Frontend、Security、Compose、Windows、Upgrade 和 Required Gate 全部成功。
- 下一串行阶段为 S55 前置 H1 真实 Key Rotation；H1 合并并通过 Main 后才启动 S55。
- 完整实现、验证与边界见 [S54 Release Evidence](release/v6-s54-cleanup-runtime.md)。

## 已完成实现验收：V6 S53 Data Recipe 与 Cross-system Oracle

### Implemented

- `flowtest-integration-plan-v2` 增加 Synthetic、Approved Dataset、Previous Step、Environment Variable、
  Secret Reference、Setup API、Existing Safe Record 与 Database Observation Recipe，并保存来源、证据、
  Deterministic、Requires Review、Confidence 与 Applies To。
- Compiler 复用现有 Start/API/Extract/Assert/SQL Node，生成每次执行变化的 Synthetic 数据、Cross-API
  动态断言与参数化只读 DB Read；敏感路径、写 SQL、跨项目 Artifact/Credential、低置信度与设计期 DB
  Observation 均 Fail Closed。
- 真实链路覆盖 Login → Create → Query → DB Read → Cross-API/DB Assert；项目出站策略显式允许
  `backend` 与 `postgres`，失败断言会输出节点错误码但不输出 Token/Secret。

### 当前门槛

- 测试先行红灯、64 项聚焦回归、Ruff/Mypy 与独立最小真实栈 S53 Playwright 均已通过；临时
  `flowtest-s53-*` 资源已精确清理，既有 Docker 恢复栈未改动。
- PR #60 最终 Review 的 P0/P1 为 0；重复 Synthetic 变量名、常量 DB Read 参数与旧版 setup_api
  兼容三项 P2 按用户指定门槛延期并记录，不继续触发修复—全量门禁循环。
- PR #60 已普通 Squash Merge，未使用 Admin/Bypass/Force Push/直接 Main；最终精确 Head 与 Merge 后
  Main 的 Backend、Frontend、Security、Compose Full/Compact、Windows、Upgrade 与 Required Gate
  全部 Success。完整运行 ID 见 [S53 Release Evidence](release/v6-s53-data-oracles.md)。
- 下一门槛：S53 Evidence Closure 文档 PR 普通合并且其 Main Push Required Gate 成功后，才可从最新
  Main 创建 S54 Cleanup Scheduler / Compensation Runtime 独立分支。

## 已完成实现验收：V6 S52 External Evidence Adapter 与 Entity Mapping

### Implemented

- 新增 `flowtest-java-evidence-v1` 与 `flowtest-database-evidence-v1` 强类型契约，分别完整表达 Java/Spring
  Route/DTO/Validation/Call/Persistence/Entity/State/Event 证据与 DB Schema/Table/Column/Constraint/
  Distribution/Masked Example；两者均适配进入既有不可变 Context Revision。
- 新增 Operation → Entity、Request/Response Field → Column、Operation → State Set 候选；每个候选携带
  Evidence Ref，全部默认 `proposed`，多个 Target 生成显式 Mapping Conflict 并把 Context 标为
  `conflicted`，不静默选择。
- MCP 升级至 `s52-evidence-adapter-v1`，新增 Java/DB Ingest 与 Mapping Inspect 三个 Tool，继续复用
  `mcp:evidence:write`、Tenant/Project 授权和标准错误 Envelope。FlowTest 不主动连接外部 MCP Server。
- Java/Spring POC 只做有界静态文本分析，不编译或执行代码；固定 small-spring Fixture 与本地 RuoYi
  `3b3941ab...` Golden Target 均已通过定向回归。Python AST Provider 通过 Evidence Bundle Adapter 保持兼容。

### 当前门槛

- 测试先行红灯与 S52 Domain/API 绿灯已记录；S49/S51 兼容、MCP Golden/SDK、S46 MCP Red Team、Ruff 与
  337-source Mypy 检查通过。Backend 全量为 872 passed / 4 skipped、90.75% 覆盖率；Frontend 为
  57 files / 222 tests；格式、Lint、Build、Python/Node 依赖审计与安全 Lint 全部通过。
- 隔离 Compose 15/15 Healthy，S52 Playwright Setup + 用例 2 passed；日志与敏感信息扫描、精确资源清理完成，
  用户既有三个栈仍为 6 / 2 / 6。
- PR #58 最终实现 Head `099ca44837c88527c3cf4e7b8490e9af7af64904` 的七项精确 CI 全部 Success；最终
  Review 无 P0/P1，两项 P2 按阶段门槛记录为非阻塞债务。PR 已普通 Squash Merge，未使用 Admin、Bypass、
  Force Push 或直接推送 Main；精确 Merge SHA 的七项 Main Push 检查全部 Success。
- 完整边界与持续更新的证据见 [S52 Release Evidence](release/v6-s52-evidence-adapters.md)。

## 已完成：V6 S51 MCP Flow Draft 与 Visual Proposal Alpha

### Implemented

- MCP SDK 与 Gateway 新增 Plan、Validate、Compile、Explain、Propose、Inspect 六个精确 Tool，统一使用
  `mcp:flow:propose`；Proposal 默认 Dry Run，持久化要求 Idempotency Key，更新现有 Workflow 强制 Expected
  Revision，并校验 Context/Plan/Compilation/FlowSpec Provenance。
- Proposal 继续写入既有 `AIChangeSet`/`AIChangeItem` FlowSpec Draft；不新建 Proposal 表、Review 状态机或
  Apply 服务，不自动 Review、Apply、Publish 或 Execute。
- 既有 `WorkflowDesigner` 增加只读 `mode=proposal`，使用同一个 Canvas 切换冻结的 Existing/Proposed Graph，
  展示 Added/Modified/Removed Node、Rewired Edge、Mapping/Assert Diff、Evidence、Confidence、Unresolved 与
  Review Actions。
- 人工可 Accept/Reject，Accepted Proposal 才能 Apply 到 Workflow Draft；Raw JSON 与 Cross-instance Mapping
  仍进入既有 `FlowSpecReviewDialog`。安全编辑创建新的待审核 ChangeSet，不原地修改 MCP Proposal。
- 隔离 Compose 的真实 Alpha 路径已覆盖 Context → Typed Evidence → Plan → Compile → MCP Dry Run → MCP Draft
  → UI 可视化检查 → Accept → Apply → WorkflowDesigner Draft，且 Graph 与 Proposal 一致、发布与执行均为 0。
- 合并后修复补齐 Edge 语义分类、Apply 后状态一致性、中文化、Proposal-keyed Override，并以
  MCP-only `(created_at, id)` Keyset Pagination 与用户显式“加载更多提案”取代可变 Offset 及无界预加载。

### 当前门槛

- Backend Format/Lint、335-source Mypy、安全 Lint 与全量 Pytest 已通过：`663 passed / 4 skipped`，Coverage
  `90.41%`。Frontend Format、Lint/Types、Coverage 与 Build 已通过：`57 files / 222 tests`，Statements/
  Branches/Functions/Lines 为 `86.23/80.12/85.44/88.48%`；Python/Node 依赖审计无已知漏洞。
- 最终隔离 Compose 15 服务全部 Healthy；真实 Playwright Alpha 链路 `2 passed`，日志 Traceback 为 0，验收后
  仅清除 `flowtest-s51-review-local` 资源；既有 `flowtest-compact` / `flowtest-ruoyi` /
  `flowtest-v5-compact` 仍分别保持 6 / 2 / 6 个运行容器。Requirement、Correctness/Data、
  Security/Tenant/Secret/SSRF 与 E2E/Scope 四类本地 Review 已完成。
- PR #55 及迟到 Review 修复 PR #56 均已普通 Squash Merge；精确头 CI、精确头 Codex Review、全部 Thread
  Resolution 与两个精确 Merge SHA Main Push 均已闭环。#55 / #56 未使用 Admin、Bypass 或直接推送 Main。
- S51 Evidence Closure PR #57 已普通 Squash Merge 至 `b6c281a832ec63e94433e0f322b30b6e342098c1`，其
  Main Push Required Gate 已 Success；S52 从该精确 Main 创建。完整边界与证据记录见
  [S51 Release Evidence](release/v6-s51-mcp-visual-proposal.md)。

## 已完成：V6 S50 Multi-Operation Plan 与 Executable FlowSpec Compiler

### Implemented

- 新增严格 `flowtest-integration-plan-v1` 纯领域 Contract 与稳定 Fingerprint，覆盖 Context、Objective、Actors、
  Preconditions、Operations、Steps、Branches、Bindings、Data Recipes、Oracles、Cleanup、Coverage、Unresolved、
  Confidence、Diagnostics 与 Evidence。
- Planner 只对用户显式选择的 Operation 使用 Canonical Contract 做同名同型 Request/Response Binding；复用
  Test Engineering 的确定性 Scenario/Oracle 与固定 Existing Auth Workflow Version。多候选不猜测、缺证据
  阻断、Secret Literal 拒绝。
- Compiler 以十个显式 Pass 生成当前 Runtime 可执行的 API/Extract/Assert/Condition/Dataset/SubFlow 与 Edge
  Mapping；Path/Cookie/Secret/External Source、未决 Review、多个 Dataset 等不可无损语义返回 Blocker。
- Plan/Compiler Provenance 进入既有 AIChangeSet Source Snapshot；写入前核对 Context、Plan 与 FlowSpec 指纹，
  不新建 Plan 表，不复制 FlowSpec Mapping/Review/Apply 状态机。
- Golden 固定 Login Token → Create → Extract ID → Query by ID → Assert ID/Status/Schema；纯领域、真实服务层
  Draft Review/Apply 与 Compose Playwright 路径均有回归。

### 当前门槛

- Backend 458-file Format、Lint、334-source Mypy、659 passed/4 skipped Pytest（90.32% 覆盖率）以及 Frontend
  Format、Lint/Types、215-test Coverage、Build 均通过；Python/Node 依赖审计与 Security Lint 无已知漏洞。
- 隔离 Compose 完整栈 15 个服务 Healthy，真实 Playwright Draft → Review → Apply 通过；验收资源已清除且用户
  既有三个 Compose Project 运行数量不变。Requirement、Correctness/Data、Security/Tenant/Secret/SSRF 与
  E2E/Scope 四类本地 Review 已完成。
- PR #53 精确 Head `9193b7fe8bcdf012d275e15319bee65ca907fb4a` 的 Backend、Frontend、Compose、
  Security、Windows、Upgrade/Rollback 与 Ready 后 Required Gate 全部 Success；Review/Comment/Thread 均为 0。
- PR #53 已普通 Squash Merge 至 `507aff999606ab6b3190810cf25717a55265eb88`；该 Merge SHA 的 Backend、
  Frontend、Compose、Security、Windows、Upgrade/Rollback 与唯一 Required Gate 全部 Success。
- S50 Evidence Closure PR #54 已普通 Squash Merge 至
  `8f20500fd151e89573bb8f01f24cb6512143dbe1`，其 Main Push Required Gate 已 Success；S51 从该精确
  Main 创建。
- 完整边界与证据记录见 [S50 Release Evidence](release/v6-s50-integration-plan-compiler.md)。

## 已完成实现验收：V6 S49 Context Revision、External Evidence 与 Proposal Adapter

### Implemented

- 新增且仅新增 `test_contexts`、`test_context_revisions`、`context_evidence_items` 三张表；Revision 与
  Evidence Item 均不可原地更新，Context 使用稳定、规范化 Fingerprint，支持 `collecting`、`ready`、
  `incomplete`、`conflicted`、`expired`、`closed`。
- External Evidence Envelope 使用严格 Pydantic 契约，拒绝未知字段、无 Revision 来源、跨租户引用、
  Secret/Token/Cookie/Password/Connection String/PEM、原始 PII 与 Prompt Instruction；Comment、Description
  等内容固定为不可信数据而非指令。Context 初始输入也执行同一敏感值检查，Revision 引用、冲突与 Evidence
  Item 超限返回稳定 409，不产生内部 5xx。
- MCP 增加 begin/requirements/ingest/inspect/close 五个 Context 工具，并使用独立
  `mcp:evidence:write` Scope；旧 `mcp:write` 不继承新权限。既有“组织治理”Service Account 表单可显式
  签发 Evidence 与 Flow Proposal 两个新 Scope。
- Proposal Adapter 复用 `FlowSpecService` 的同一套 Import/Mapping/Validation 路径；默认 Dry Run、强制
  Idempotency-Key，持久化时只创建 Draft，记录 Service Account、`mcp://` 来源、Context Revision 与
  Fingerprint，不 Review、Apply、Publish 或 Execute。
- Alembic 与 Standalone Revision 升级到 `20260828_0046`；PostgreSQL 已完成 `0045 → 0046 → 0045 → 0046`
  往返和无 Drift 检查，Standalone 已验证旧 0045 数据库幂等升级及三表/索引完整性。

### Local Validation

- Backend format、Ruff、Mypy 与全量 Pytest 均通过：`644 passed / 4 skipped`，Coverage `90.29%`。
- Frontend format、lint、Vitest Coverage 与 build 通过：`56 files / 215 tests`，Statements `86.15%`、
  Branches `80.11%`、Functions `85.27%`、Lines `88.37%`。
- 隔离 Compose 真实栈上的 S49 Playwright `1 passed`：覆盖旧 Scope 拒绝、Context/Evidence、Secret
  拒绝且响应与日志零泄漏、Requirements、Dry Run、Draft 持久化、幂等重放与 Close；测试后已清理容器、
  网络和数据卷。

### Intentionally Out of Scope / Remote Validation

- `flowtest.propose_flow_draft` MCP Tool、Integration Plan/Compiler、Visual Proposal、Evidence Adapter、
  Cleanup 与 Preview 分别属于 S50～S55，本阶段不提前注册；没有新建平行 Proposal/Review 状态机。
- PR #50/#51 精确 Head 与实现 Merge SHA Main Push 的适用 Backend、Frontend、Security、Compose
  full/compact、Standalone Windows、Upgrade/Rollback 和 Required Gate 全部 Success；未解决 Review Thread
  为 0，均普通 Squash Merge，无 Admin、Bypass 或 Direct Main。精确 Run ID 见
  [S49 Release Evidence](release/v6-s49-context-evidence.md)。
- 下一门槛：本 Evidence Closure 文档 PR 合并且其 Main Push Required Gate 成功后，才可从最新 Main 创建
  S50 分支。

## 已完成：V6 S48 Contract Freeze 与 Governance Baseline

### Implemented

- 正式起点固定为 `main@6370c6c8b44db51ce7717bc73eaf41f259c9df1b`，Alembic 单 Head 与
  Standalone Revision 均为 `20260823_0045`；Backend `6.0.0.dev0`、API/Frontend `6.0.0-dev.0`，
  Release 保持未发布。
- 完整 V6 方案已复制为 `docs/development-plan-v6.md`；新增 10 份 ADR，冻结外部 LLM、Context Revision、
  Evidence、Proposal Reuse、Plan、FlowSpec v2、Cleanup、Preview、数据分类和 MCP Scope。
- 新增 FlowSpec v2 纯领域契约、确定性 v1→v2、受守卫 v2→v1、新 Fingerprint 与 Golden Contract；现有
  v1 Import/Fingerprint/Workflow/Snapshot 不改写。
- Golden Set 固定 HTTP、Login→Create→Query、WorkflowDefinition、AIChangeSet、MCP Tools、TestDesign、
  OperationIdentity、Snapshot、Standalone Transfer、DB Profile、小型 Java/Spring 与 RuoYi Target。
- Evaluation 标注/统计契约已固定。唯一新 Flag 为 `integration_flow`，Full/Compact/Standalone/Compatibility/
  Upgrade 默认均关闭；没有预建未来空 Flag。
- 本地 Backend 四项门禁通过：`638 passed / 4 skipped`，Coverage `90.21%`；Frontend 四项门禁通过：
  `56 files / 215 tests`，Statements `86.15%`、Branches `80.11%`、Functions `85.27%`、Lines `88.37%`。
- 本分支镜像在隔离 Compose 替代端口全部健康，相关 Playwright 登录 Setup 与 S22 能力/安全/深链
  `2 passed`，随后已清理临时容器、网络和数据卷。依赖 CI Smoke 种子与显式旧 Feature Flag 的全量 E2E
  诊断不记为通过，最终以 Remote Compose Workflow 完整前置结果为准。

### Intentionally Out of Scope

- S48 不增加数据库表或 Migration，不实现 Context/Evidence 持久化、Compiler、Proposal UI、Cleanup Runtime、
  Preview Runtime、自动 Publish、生产执行或内置 Java Provider。
- 不创建 Tag、Release，不把本地测试写成远程 CI，不宣称真实 Key Rotation、公司试点或人工签署完成。

### Review 与 External Validation / 下一门槛

- Requirement、Correctness/Data Consistency/Concurrency、Security/Tenant/Secret/SSRF、End-to-End User Flow
  四类本地 Review 完成。GitHub 自动 Review 在首个 Head 发现 2 个 P2：通配 Binding Map 与规范化后
  错误路径索引；均在最终 Head `13d80a856802d758bbe1e6b1da0c55330a4c8121` 修复并增加回归，2 个
  Thread 均 `resolved=true`、`isOutdated=true`，未解决 Thread 为 0。
- PR #46 最终 Head 的 Backend、Frontend、Security、Compose full/compact、Standalone Windows、Upgrade/Rollback
  和唯一 Required Gate 全部 Success；普通 Squash Merge 后，Merge SHA 的同类 Main Push Workflow 与
  Required Gate 也全部 Success。精确 Run ID 见 [S48 Release Evidence](release/v6-s48-contract-baseline.md)。
- 下一门槛：S48 Evidence Closure 文档 PR 合并且其 Main Push Required Gate 成功后，才可从最新 Main
  创建 S49 分支。

## 进行中：V5 S47 正确性修复与功能闭环

1. S47 在独立 `codex/v5.0` 工作树对 S37～S46 实现先做事实审计，确认并修复
   FlowSpec 跨实例丢失 Service/Operation/Target 语义、批次子项 Checkpoint 粒度错误、
   Resume/Retry 语义重叠、Dispatch 失败孤儿状态、变更边界泛化和结构化失败归因缺失。
2. 新增 typed Evidence Contract 和确定性 Test Engineering Engine，从契约证据生成 Test Intent、
   Scenario、Oracle、Coverage/Gap 和审核要求；新增 Generate → Proposal → Review → Apply 闭环，
   Apply 复用现有 Workflow/TestCase 执行资产，不创建只能展示的平行模型。
3. FlowSpec 保持 `flowtest-flow-spec-v1` Schema，新增 `flowtest-flow-spec-fingerprint-v2`；旧文档
   缺省按 v1 指纹解析，v2 指纹排除实例 UUID，并通过显式 Service/Operation Mapping
   落地多服务工作流。
4. MCP 只读面增加生成、覆盖、源码/DataProfile/Test Evidence、FlowSpec Diff/Validate 和
   Change Impact 工具；受控写入默认 `dry_run=true`，必须提供幂等键，仍只能产生 Draft。
5. 前端新增“测试工程”和 FlowSpec 审核映射界面，补齐 Service/Endpoint Variant
   类型化编辑、连通性、Secret Ref、Impact Preview，失败归因页面升级到 v2 结构化证据。
6. 新增可回滚迁移 `20260823_0041`，扩展 `test_designs` 的 Scenario/Evidence/Warning/
   Confidence/Review Requirement，并将过去被误标为已完成的 Key Rotation 迁移状态
   恢复为 `planned`。真实重加密 Apply/Rollback 仍未实现，是 GA blocker，UI/API 不再声称已完成。
7. 本地 Backend 全量 `440 passed / 3 skipped`（Coverage `90.06%`），Frontend
   `56 files / 211 tests`（Branch `80.10%`），PostgreSQL `0041 → 0040 → 0041`
   往返无 drift；隔离 Compose 通过多 Service FlowSpec、MCP、生成式物化和真实执行
   Smoke，Playwright 通过 Test Engineering Generate → Draft → Review → Apply 主路径。
   未执行的远程 CI、Windows x64 72 小时试点、14 日 RC 观察与人工签署不记为通过。完整事实见
   [S47 V5 功能闭环记录](release/s47-v5-functional-completion.md)。

## 进行中：V5 S47.1 语义正确性与证据闭环

1. OpenAPI 3/Swagger 2 导入把带 location 的 parameter、request body、response status/schema、auth、
   source/revision/completeness 持久化到 APIVersion Canonical Contract；手工/旧 API 使用安全 partial
   backfill，不保存 Header/Query 值，也不伪造 response status。
2. Test Engineering 从持久化契约和最多 10 个、聚合 2 MiB 的 Evidence Bundle 生成 Path/Query/Header/
   Cookie/Body/Auth 场景；DataProfile/Source/Existing Test Finding 真实改变 Scenario、Oracle、Coverage
   和 Knowledge Graph。冲突场景强制 review 且默认不可物化。
3. Workflow request override 与 Runtime 已支持位置化 mutation 和节点级 auth disabled；Response Schema、
   JSON Path 和可支持 expression 物化为 Assert，不支持的 Oracle 返回 blocker。Mock Target 记录并验证
   实际收到的 Path、Query、Header、Body 和认证缺失。
4. FlowSpec 新导出使用 fingerprint v3，保存 pinned/current、source version 和 contract fingerprint；
   pinned 找不到 exact compatible target 时阻断，绝不回退 current。
5. Change Regression 将 Asset Mapping Coverage 与 Test Semantic Coverage 拆分。真实服务集成测试覆盖
   Mapping=100%、旧边界已覆盖时仍发现 999/1000，并使用 Current Canonical Contract 的真实 201/422
   Oracle；审核后复用 TestEngineering 物化 Workflow/TestCase bundle。
6. Evidence value sanitizer 覆盖 JWT、Bearer/Basic、PEM、Cloud Key、高熵值、Email、Phone、Card 和
   URL 凭据；Failure Triage 将收到的 5xx 归为 upstream，并优先使用 service key/endpoint variant。
7. 新迁移 `20260823_0042` 添加 API Contract 快照并 backfill；未进入 main 的 0041 downgrade 已校正，
   不再把 planned key migration 伪造为 migrated。SQLite baseline/增量 backfill 和 Transfer revision
   同步到 0042。
8. 详细事实、兼容策略、门禁和剩余风险见
   [S47.1 语义正确性与证据闭环](release/s47-1-semantic-correctness.md)。远程 CI、Windows x64 试点、
   连续 RC、安全审批和真实 Key Rotation 未执行/未完成，不记为通过。

## 当前恢复点

- V5 当前工作树：独立 `codex/v5.0`，基于 `codex/standalone-runtime@0643732`；S37 已提交
  `6fc3df2`，S38 已提交 `d146520`，S39 已提交 `7fa68ef`，S40 已提交 `185ce87`，S41 已提交 `5a8b2e8`，S42 已提交
  `a2f97a7`，S43 已提交 `969c5c2`，S44 已提交 `1d5fd75`，S45 已提交 `6f493d4`，S46 已完成本地等价验收，
  本阶段提交后暂停。当前脏 `main` 工作区未参与。
- 收口基线：`main@08db725`，PR #37 已完成 S31 质量指挥中心并合并。
- 当前 V4 小型化小阶段由 `codex/s32-runtime-profile-foundation` 承载，从上述干净基线创建；
  用户随后明确要求连续推进 V4 及 S34，因此范围已扩展到 S32～S36 的备份恢复、离线/私有仓库分发、
  事务式无外网升级、容量稳定性、Full↔Compact 兼容、隐私安全诊断和可恢复回滚验收。
- Standalone 代码在独立 `codex/standalone-runtime` 分支继续推进，避免把仍在评审的 Compact Docker
  PR #38 与无 Docker 运行时混在同一提交中。
- 已发布标签：`v1.1.0`、`v1.5.0`、`v1.8.0`、`v2.0.0-rc.1`、`v3.0.0-alpha.1`、
  `v3.0.0-beta.1`、`v3.0.0-beta.2`、`v3.0.0-beta.3`；不得提前创建 `v2.0.0` 或后续 V3 里程碑。
- 用户已明确要求跳过原计划中的等待顺序并开启 V3 开发；该授权不等于完成或豁免 V2 正式发布门槛。
- `FlowTest_V3_UI_CN_HD/` 的 HTML 设计源和 21 张 2560×1440 PNG 基准在 S22 纳入 Git，原始内容保持不变。

## 已完成：V5 S37 V4.9 基线收口（本地等价验收）

1. V5 独立工作树从干净的 `codex/standalone-runtime@0643732` 创建 `codex/v5.0`；当前脏 `main`
   工作区未参与，未执行 reset/stash 覆盖或删除操作。本阶段提交主题为
   `chore(s37): converge v4.9 baseline`。
2. 后端质量门槛全部通过：Ruff format/check、mypy、pytest `380 passed / 3 skipped`，总覆盖率
   `90.22%`。前端 format、lint、coverage、build 全部通过；Vitest `48 files / 195 passed`，
   Statements `86.66%`、Branches `80.41%`、Functions `86.01%`、Lines `88.81%`。
3. 独立 Compact Compose 项目完成六服务健康检查、S32 登录/项目/API/Workflow/不可变发布/执行/
   Snapshot smoke；Chromium 完成首次密码初始化和 `s14-management-workbench` 主路径，覆盖
   OpenAPI/请求体编辑、Params/Headers 批量编辑、Secret 脱敏及项目/团队操作。相关 URL/Swagger、
   Transfer、BodyEditor、Workflow Editor 回归也由后端/前端测试套件覆盖。
4. Alembic 在隔离数据库完成 `20260822_0033 → 20260822_0032 → 20260822_0033`，每步含 upgrade、
   downgrade 和 `alembic check`；V2→V3 原地升级、回滚、再升级脚本完成真实数据与 Artifact 验证。
   本阶段同时修正了验证脚本、Compact 文档和 Standalone ADR 中滞后的 `20260822_0032` 当前 head。
5. 本地 Standalone 等价验收以临时 SQLite 数据目录启动真实 API：`/api/v1/live`、`/api/v1/ready`、
   `/api/v1/runtime-profile` 和前端静态页均返回成功，Runtime Profile 为 `standalone`，SQLite
   `alembic_version` 为 `20260822_0033`。这不替代 Windows x64 公司云桌面 72 小时试点；本阶段不声称
   已取得该实机证据。
6. S37 已完成基线冻结，下一阶段 S38（Service/ServiceEndpoint/RequestTargetResolver）须经用户确认后
   才开始。

## 已完成：V5 S38 请求目标与 Endpoint Variant（等待用户确认）

1. S38 继续使用独立工作树和 `codex/v5.0` 分支，基于 `codex/standalone-runtime@0643732`；当前脏的
   `main` 工作区未参与，未执行 reset、stash 覆盖或删除操作。
2. 新增独立的请求目标领域模型 `Service`/`ServiceEndpoint`，不复用 Contract Hub 服务目录；以
   `service_key` 作为跨实例稳定标识，以 `(environment_id, service_id, variant)` 保证 Endpoint 唯一，
   并在 `20260822_0034` 迁移中为旧项目回填默认 Service/Endpoint。
3. API、Workflow 节点、API Debug/Preview 和 Execution 共用 typed `RequestTargetResolver`。目标优先级为
   `Node Override > API Service > Environment Default Service > Legacy base_url`；变量/请求头按
   `Node > API > ServiceEndpoint > Environment > Project` 合并。执行与 Workflow Snapshot 保存 Service、
   Variant、Revision、最终 URL、脱敏请求目标、Secret Ref、TLS/Proxy/Outbound Policy。
4. 新增请求目标管理 API 和前端“请求目标”页面，支持 Service、环境 Endpoint Variant、环境默认 Service、
   API 默认 Service 管理；Workflow API 节点支持 Service Override/Endpoint Variant，执行结果展示脱敏
   Target Snapshot。OpenAPI 3/Swagger 2 导入会提取 Server 并在 Merge 阶段经过项目/环境校验后映射 Endpoint。
5. Standalone SQLite 增量 Schema、Transfer Manifest、Compact/Full Alembic 基线同步到 `20260822_0034`；
   保留 `Environment.base_url` Legacy Fallback，并维持 `/api/v1` 既有请求结构兼容。
6. S38 阶段退出前必须完成后端 Ruff/mypy/pytest、前端 format/lint/coverage/build、迁移往返、Standalone/
   Compact/Full 兼容、目标解析/导入/脱敏/权限回归及必要的 Compose 验证；完成本地提交后暂停，不自动进入 S39。

## 已完成：V5 S39 Organization、TenantContext 与 Service Account（等待用户确认）

1. 新增 `Organization`、`OrganizationMember`、`ServiceAccount` 领域与持久化模型；用户请求通过
   `X-Organization-Id` 解析 typed `TenantContext`，系统管理员可切换组织，普通用户必须具备组织成员关系。
2. `20260822_0035` 创建组织/成员/服务账号表，并为旧 Project、Runner Pool、Audit Log 增加组织索引和外键；
   迁移会创建默认组织、回填旧资产和审计记录、为既有用户生成兼容成员关系。Standalone 增量 Schema、
   Transfer 基线和 Compact/部署文档同步到 `20260822_0035`。
3. Project 创建、列表和详情先经过组织上下文；Service/ServiceEndpoint、Execution、Artifact、Evidence、
   Workflow、Test Plan 等项目资产继续沿用 Project 授权边界；Dashboard/Search、Runner Pool/Task/Lease/Event
   查询增加组织过滤，旧 NULL 组织字段仅作为迁移兼容回退。
4. 新增组织、成员和 Service Account 管理 API。Service Account 只返回一次明文令牌，数据库仅保存哈希，支持
   scope 校验、过期、轮换、撤销和 `TenantContext` 认证结果；AuditService 自动写入组织索引并继续脱敏详情。
5. 新增跨组织项目/Service Account API 回归、Runner 查询隔离回归；真实 PostgreSQL 完成
   `20260822_0034 → 20260822_0035`、旧用户/项目/Runner/审计数据回填、降级、再升级和 `alembic check`。
   本阶段只完成本地等价验证，未声称 Windows 公司云桌面实测或远程 CI 证据。
6. S39 已完成本地 Git commit 并暂停；S40 在用户确认后继续推进。

## 已完成：V5 S40 FlowSpec v1（等待用户确认）

1. 新增独立 FlowSpec v1 Domain 合约和 Pipeline：Parse → Normalize → Validate → Compatibility，支持
   稳定规范化、跨实例语义 Fingerprint、按节点/边稳定 ID 的递归 Diff、置信度/未解析证据以及实例资源引用告警。
2. 导出支持 Workflow Draft 和已发布版本；导入不直接改库，而是复用 AI ChangeSet/ChangeItem 物理表创建
   `source_type=flow_spec` 的 Draft，保存源快照、校验/兼容结果、目标 Revision 和指纹，必须经过 Review
   Accept 后 Apply，并在应用前检查目标快照防止陈旧覆盖。
3. 新增 `/api/v1/projects/{project_id}/flow-specs` 下的 Export、Validate、Diff、Import、ChangeSet
   List/Detail、Review、Apply API；新增前端类型化 FlowSpec service，未暴露 Secret 明文，仅支持
   `secret://` Secret Ref。既有 AI ChangeSet 查询继续只返回 `source_type=ai`，保持原 API 行为。
4. `20260822_0036` 将 Impact/Risk/AI Job 与 Suggestion 关系改为可空，新增来源、操作者、应用时间字段和约束；
   PostgreSQL 已完成 `0035 → 0036` upgrade、downgrade、再 upgrade 与 `alembic check`。Standalone 基线、
   Transfer Manifest 和 Compact/部署文档同步到 `0036`；旧 SQLite ChangeSet 表增加了可恢复的表重建路径，
   保留已有 AI 数据后再承载 FlowSpec Draft。
5. 本地验证：后端 Ruff format/check、mypy、pytest `389 passed / 3 skipped`，覆盖率 `90.04%`；前端
   format、lint、coverage、build 全部通过，Vitest `50 files / 198 passed`，Statements `86.8%`、
   Branches `80.28%`、Functions `86.19%`、Lines `88.97%`；Standalone/Transfer 回归 `19 passed`。
   验证使用本地等价环境，未声称 Windows 公司云桌面实机或远程 CI 证据。
6. S40 完成后提交本地 Git commit 并暂停；下一阶段 S41 为 MCP Read，须经用户确认后开始。

## 已完成：V5 S41 MCP Read（等待用户确认）

1. 新增只读 MCP Application Service 与 `/api/v1/mcp/read` REST Gateway；服务账号必须具备
   `mcp:read` Scope，并在认证时建立 `TenantContext`。MCP 认证不会更新 `last_used_at`，避免只读调用
   产生业务状态变化；跨组织项目统一返回不可枚举的 404。
2. 只读结果统一使用 `data/evidence_refs/confidence/redactions/trace_id/warnings` Envelope。项目、Service/
   Endpoint Variant、API Contract、Workflow Draft 和 Run Evidence 均采用 allow-list 投影；请求头、变量、
   Cookie、Secret Ref 明文、认证配置、请求/响应 Body、Execution Snapshot、上下文和错误详情不返回，
   Endpoint URL 仅保留安全 Origin，审计详情也不记录原始参数或令牌。
3. 使用官方 Python MCP SDK，并锁定 `mcp` 2.x 当前解析版本 `2.0.0`；新增 `flowtest-mcp` CLI，支持
   stdio 和 Streamable HTTP 两种传输。工具、Resource Template 和 Prompt 稳定排序，Prompts 明确只读、
   不写入/不执行且需要人工确认；MCP Gateway 仅通过 HTTP Application API 访问，不直连 ORM、PostgreSQL、
   Redis 或 MinIO。
4. 新增 MCP Domain 合约、typed HTTP Client、SDK contract test、服务账号/租户隔离/脱敏/审计回归；
   后端 Ruff format/check、mypy、pytest 全部通过，`394 passed / 3 skipped`，覆盖率 `90.01%`。前端未新增
   S41 页面或业务代码，但 format、lint、coverage、build 基线全部通过，Vitest `50 files / 198 passed`，
   Statements `86.8%`、Branches `80.28%`、Functions `86.19%`、Lines `88.97%`。
5. 本阶段无数据库模型或迁移变更；临时 PostgreSQL 已完成从空库升级到 `20260822_0036`、`alembic check`、
   降级到 `20260822_0035`、再升级和再次 `check`，临时数据库已清理。未把正在运行的旧 Compact 镜像当作
   S41 证据，未声称 Windows 云桌面实机或远程 CI 验证。
6. S41 已完成本地等价验证并提交；S42 已完成本地等价验证，提交后暂停；下一阶段 S43
   （Durable Execution Command、Checkpoint、Idempotency、Resume、Retry 与 Fencing）须经用户确认后开始。

## 已完成：V5 S42 TestIntent/TestCase/Test Design 与 MCP Controlled Write（等待用户确认）

1. 新增纯 Domain Test Design 合约：TestIntent、Knowledge Graph、State Model、Oracle、Coverage 和
   稳定 Fingerprint。图节点/边、状态/迁移和 Oracle 标识均在进入 Application Service 前完成 typed 校验；
   Test Design 是设计聚合，不替换既有可执行 TestCase 数据模型。
2. 新增 `TestDesign` 与 `ChangeSetApproval` 持久化模型及可回滚迁移 `20260822_0037`；统一 ChangeSet
   继续复用 `ai_change_sets/ai_change_items` 物理表，仅扩展 `test_design` 变更项类型。MCP 提案使用
   `source_type=mcp`、`source_ref`、`actor_type=service_account`、`actor_id`，既有 AI ChangeSet 查询
   仍保持只显示 `source_type=ai` 的兼容行为。
3. 新增 `/api/v1/mcp/write/change-sets` Application API 和官方 MCP SDK 的
   `flowtest.propose_test_design` 工具。MCP 只可提交 Draft；低置信度 Oracle 强制进入 Review，高/危风险
   写入必须先建立人工批准记录，批准后仍须逐项审核，不能自动发布、执行、修改权限或创建 Credential。
   人工 Review 通过既有 TestCase Application Service 创建 TestCase，并在接受 Design 后落库 approved 设计。
4. 受控写入对 Secret、凭据、Authorization、Token、Card/Email 等敏感值只返回安全路径错误，允许的运行时
   参数使用 `secret://` 引用；响应、审计和 ChangeSet 元数据均不记录令牌或 PII。MCP 继续通过 Application
   Service 访问，不直连 ORM/数据库；新增 `mcp:write` Service Account Scope 与独立 TenantContext 校验。
5. Standalone SQLite 增量 Schema 会创建新表，并对旧 `ai_change_items` 进行可恢复表重建以加入 `test_design`
   约束；Transfer 表清单由 72 增至 74，Manifest 版本保持兼容。PostgreSQL 已完成 `0036 → 0037` upgrade、
   `alembic check`、downgrade 到 `0036`、再 upgrade 和再次 check。
6. 本地验证：后端 Ruff format/check、mypy、pytest `399 passed / 3 skipped`，覆盖率 `90.01%`；新增
   Domain、MCP API/SDK、人工审批、敏感信息、Standalone/Transfer 回归。前端保持既有 `50 files / 198 passed`
   与 format、lint、coverage、build 基线；本阶段未新增 UI 业务页面。验证为本地等价环境，未声称 Windows
   公司云桌面实机或远程 CI 证据。
7. S42 已完成本地 Git commit 并暂停；用户确认后进入 S43 Durable Execution 实施。

## 已完成：V5 S43 Durable Execution（等待用户确认）

1. 新增纯 Domain Durable Execution 合约，固定 `s43-durable-v1` Schema Version，定义
   `ExecutionCommand`（Start/Resume/Retry/Cancel）、幂等键、命令状态、Checkpoint 状态和
   可恢复节点判断；Domain/Engine 不依赖 FastAPI、Celery、SQLAlchemy Model 或具体基础设施客户端。
2. 新增 `ExecutionCommand`、`ExecutionCheckpoint` 持久化模型及可回滚迁移 `20260822_0038`。命令保存
   请求摘要、幂等键、响应/错误和 Fence 信息；Checkpoint 保存节点、Attempt、输入哈希、脱敏上下文、输出
   Digest、提取变量和 Lease/Fence 证据，敏感值不会进入命令或 Checkpoint 明文。既有 `RunnerTask`
   Lease/Fencing 状态机继续作为执行事实源。
3. Workflow Start/Resume/Retry、Standalone Recovery 和 Runner Control Plane 共用 Durable Execution
   Application Service。相同幂等键返回同一 Execution；已完成节点恢复时跳过，失败节点从连续 Attempt
   继续；远程 Runner 重启后恢复已持久化 Checkpoint，旧 Lease/Fence 不能覆盖新状态，终态命令只完成一次。
4. 新增 Runner Checkpoint 上报 API、命令/Checkpoint 查询 API，并在 Lease 校验、Payload 大小、脱敏、重复
   Checkpoint 和旧 Fence 场景增加回归。Coordinator 使用独立短事务写入终态 Checkpoint，避免取消轮询刷新
   与回调写入互相污染 SQLAlchemy Session 状态；Standalone 启动时会恢复 queued/running 的加密执行计划。
5. 执行控制台修正 queued 状态轮询、完成后 Replay/Debug 操作可见性和执行面事件展示；Runner 事件查询保留
   `/api/v1` 既有 `limit <= 100` 契约。Standalone、Compact、Full 继续共享业务状态语义，Transfer/Standalone
   Schema 与迁移 head 同步到 `20260822_0038`，Transfer 表清单为 76。
6. 后端验证：`uv run ruff format --check .`、`ruff check .`、`mypy app` 全部通过；pytest `406 passed /
3 skipped`，总覆盖率 `90.01%`。前端 format、lint、TypeScript、生产 build 全部通过；Vitest `50 files /
198 passed`，Statements `86.8%`、Branches `80.29%`、Functions `86.19%`、Lines `88.97%`。
7. 真实 PostgreSQL 已完成 `20260822_0037 → 20260822_0038` upgrade、`alembic check`、downgrade 到
   `0037`、再 upgrade 和再次 `check`；本轮验证栈最终 `alembic check` 无漂移。S11 基线和 S29 Runner
   故障转移/恢复冒烟通过，包含 Attempt=2、Fence=2、Runner B 接管及 Drain；干净 Compose 数据卷上的
   Playwright 全量 `20/20` 通过，API 上限修正后追加 S29 页面 `1/1` 通过。
8. 验证运行于本地 macOS/ARM，因现有 Compact 环境占用默认端口使用隔离的高端口 Compose 项目；未将该结果
   虚构为 Windows 公司云桌面实机、72 小时试点或远程 CI 证据。当前脏 `main` 工作区未参与，未修改附件原始
   计划文件；S43 已完成本地提交后暂停，S44 等待用户确认。

## 已完成：V5 S45 Change-Aware Regression（等待用户确认）

1. 新增 `ChangeRegressionRun` 与 append-only `ChangeRegressionStage`，把 Change → Impact → Regression Selection →
   Missing Test → Review → Execution → Evidence → Release Gate → Failure Triage 串成一条可追溯链路；复用既有
   Impact、Test Plan、Test Design、AI ChangeSet、Execution 和 Release Gate Application Service，不绕过应用层直接操作 ORM。
2. 新增人工审核与执行控制：缺失测试以置信度 `0.65` 生成 Test Design Draft，必须逐项 Review；存在待审核项或未批准时不能执行，
   运行结果、证据引用、失败分诊和发布门禁判定均回写阶段记录。CI 入口使用独立 `analyze:change-regression` Service Account Scope，
   复用 Idempotency 记录，重复请求返回同一条回归运行。
3. 新增项目级变更回归 API 和前端“变更回归”页面，支持 Git Diff/OpenAPI Diff/Schema Diff 来源、测试计划与 Release Policy 绑定、
   缺失测试 Draft 审核、批准、执行、证据查看和 Release Gate 评估；S45 页面继续遵守 Secret/PII 脱敏和标准错误 Envelope 约束。
4. `20260823_0040` 创建回归运行/阶段表并扩展 ChangeSet 来源约束；Standalone SQLite 增量 Schema、Transfer Manifest 基线和
   Compact/Full 迁移 head 同步到 `20260823_0040`，Transfer 表清单由 78 增至 80，原有 `standalone-compact-transfer-v1` 版本保持不变。
   首次真实 `alembic check` 捕获并修正了迁移中多余的 `status` server default，随后往返检查无漂移。
5. 后端质量门槛全部通过：Ruff format/check、mypy、pytest `411 passed / 3 skipped`，总覆盖率 `90.09%`；前端 format、lint、
   TypeScript、production build 和 coverage 全部通过，Vitest `52 files / 205 passed`，Statements `86.28%`、Branches `80.02%`、
   Functions `85.10%`、Lines `88.36%`。Standalone/Transfer 定向回归 `19 passed`。
6. 临时 PostgreSQL 完成空库 `upgrade → alembic check → downgrade -1 → upgrade → alembic check`；隔离高端口 Compose 完成源码构建、
   服务健康检查和 Playwright 冒烟：管理员首次登录改密、创建项目、项目导航和 S45“变更回归”页面渲染均通过。验证使用本地 macOS/ARM
   和独立临时数据卷，验证结束后已清理；未声称 Windows 公司云桌面实机或远程 CI 证据。
7. S45 已完成本地 Git commit 并暂停；随后按用户继续指令进入 S46 稳定性与 GA 收口。

## 已完成：V5 S46 稳定性、安全与 GA 收口（等待用户确认）

1. S46 只做发布收口：新增 GA Gate、Full/Compact/Standalone 兼容矩阵、故障注入与恢复 Runbook，并补充
   S37–S45 的升级/回滚边界；原始 V5 计划附件未修改。当前迁移 head 为 `20260823_0040`，Transfer Manifest
   仍为 `standalone-compact-transfer-v1`，`/api/v1` 兼容基线和三个 Runtime Profile 行为保持冻结。
2. 标准错误边界完成安全硬化：HTTP 404/405 等错误统一返回带 trace ID 的 Error Envelope；Pydantic 校验错误、
   Application Error 详情和验证输入按敏感字段脱敏，password/token/authorization/cookie/api key 等原始值不再
   回显。Mock 多方法路由拆分为显式 Operation，消除 OpenAPI 重复 operationId。
3. 后端门禁全部通过：Ruff format/check、mypy、pytest `417 passed / 3 skipped`，总覆盖率 `90.10%`；前端
   format、lint、coverage、build 全部通过，Vitest `52 files / 205 passed`，Branches `80.02%`。Standalone
   SQLite 与 Transfer 定向回归 `19 passed`。
4. 隔离 PostgreSQL 完成空库 `upgrade → alembic check → downgrade -1 → upgrade → alembic check`，最终
   revision 为 `20260823_0040`。Backend/Frontend S46 镜像均构建通过；pip-audit、pnpm audit 通过，Grype
   扫描未发现未登记的可修复 High/Critical，CPython `3.13.15` 精确例外已在本阶段复核并更新下次复核日期。
5. 独立高端口 Compact 栈完成六服务健康检查、S32 登录/项目/Artifact/Workflow/Snapshot smoke；20 秒 Soak
   采样 9 次、失败 0、ready p95 `0.047471s`；100 请求/10 并发 API p95 `0.022282s`，4 条工作流/2 并发
   全部通过，队列无积压。Full↔Compact 双向兼容演练通过；停止 Worker 后重新启动、健康检查和工作流验收再次通过。
6. Playwright 在同一独立 Compact 栈完成管理员登录、Dashboard 和 S45“变更回归”页面渲染冒烟；MCP 租户隔离、
   脱敏、只读/受控写入和红队静态面由 S46 Gate 测试覆盖。验证环境为本地 macOS/ARM 和临时数据卷，不声称
   Windows x64 公司云桌面 72 小时试点、生产备份恢复、人工安全审批或远程 CI 证据。
7. S46 已完成本地 Git 提交后暂停；下一步仅在用户确认后进行发布评审或 GA 外部环境验证，不再自动增加大功能。

## 已完成：V4 S44 Enterprise Collaboration（等待用户确认）

1. 新增纯 Domain 配额策略与治理决策模型，支持 `observe`、`warn`、`soft_limit`、`hard_limit` 四种模式，
   覆盖 Project、User、Runner 并发、Execution 并发、AI 日请求和 Artifact 存储六个维度；硬限制通过统一
   错误 envelope 返回 429，精确达到上限仍允许当前操作。治理初始化使用 PostgreSQL/SQLite 幂等插入，
   避免组织管理页并行加载产生重复键 500。
2. 新增 `OrganizationGovernance`、`OrganizationKeyVersion` 及可回滚迁移 `20260822_0039`。审计保留、Quota、
   Runner Pool 类型/Runtime/注册审批策略均按组织保存；密钥生命周期支持 Prepare → Apply → Rollback，数据库
   只保存外部引用、SHA-256 指纹和迁移状态，不保存原始密钥材料。
3. Project、成员、Execution、AI 请求、Artifact、Runner Pool/Claim 和 Retention Cleanup 已接入组织配额；
   审计查询支持动作、资源和时间范围过滤，审计清理遵循组织保留天数。Service Account 增加治理、审计、密钥
   轮换和 Runner 管理 Scope，继续只在签发/轮换响应返回一次性明文令牌。
4. 新增组织治理 API 与前端“组织治理”页面，覆盖组织角色、最小权限 Service Account、Quota/Runner Governance、
   Audit Query、Key Rotation 和 Support Bundle Redaction。支持包明确 `internal-redacted` 分类并排除密码、密钥、
   Token、密文和私钥字段。
5. Standalone Schema、Compact/Full Alembic head 和 Transfer 同步到 `20260822_0039`；Transfer 表清单由 76
   增至 78，Manifest 版本保持冻结为 `standalone-compact-transfer-v1`，新导出包以向后兼容字段声明可迁移数据、
   仅引用/哈希数据和排除数据分类。旧 `Environment.base_url`、`/api/v1` 和三档 Runtime 业务语义保持兼容。
6. 后端质量门槛：Ruff format/check、mypy 全部通过；pytest `410 passed / 3 skipped`，总覆盖率 `90.12%`。
   前端 format、lint、TypeScript、production build 和 coverage 全部通过；Vitest `51 files / 202 passed`，
   Statements `86.1%`、Branches `80.00%`、Functions `84.96%`、Lines `88.18%`。Standalone/Transfer 定向回归
   `19 passed`，Transfer Manifest 回归 `8 passed`。
7. 真实 PostgreSQL 临时验证栈完成空库升级至 `20260822_0039`、`alembic check`、降级到 `20260822_0038`、
   再升级和再次 `alembic check`；最终 head 为 `20260822_0039`。独立 Compose 高端口验证栈完成 PostgreSQL、Redis、
   MinIO、Backend、Frontend 健康检查和镜像构建；Playwright CLI 完成管理员登录、组织治理入口及组织与角色、
   Service Account、Quota/Runner、Audit/Security 四个页签渲染，Backend 日志无 500、Traceback 或重复键异常。
8. 空 SQLite 从最早 Alembic 链全量升级仍会在既有 `20260809_0002` 的 PostgreSQL 专用 `DEFAULT '{}'::json` 处
   失败；这是 S44 之前的迁移兼容问题，本阶段不改写旧迁移。Standalone SQLite 使用 metadata/bootstrap 与 `0039`
   基线的本地等价路径及定向回归通过；未将本地 macOS/ARM 结果声称为 Windows x64 公司云桌面或远程 CI 证据。
9. S44 已完成本地等价验收并提交；下一阶段 S45 已在用户继续指令后完成，当前等待用户确认是否进入 S46。

## 进行中：V4 Standalone 无 Docker 云桌面部署

1. Standalone 新增独立 `standalone` 运行档位；Full/Compact 的 PostgreSQL、Redis、MinIO 和
   Celery 拓扑保持不变，不把 SQLite 数据迁移回 Docker 档位。
2. Standalone 使用 SQLite WAL、本地附件目录、进程内事件总线、固定窗口限流和后台调度器；
   API、Web、工作流和测试计划在一个 Python 进程内运行，启动时自动创建当前模型基线并记录
   `20260822_0033` Alembic revision。
3. Performance Lab、Environment Lab、Runner Fabric 在该档位固定关闭；事件历史、限流桶和未完成
   进程任务在重启后不恢复，业务状态、附件和加密 Snapshot 持久化到 `data\`。
4. 新增 Windows PowerShell 安装前检查、启动、停止、Readiness/档位验收、备份和离线包构建脚本；离线包可携带
   Python 3.13 运行时与 wheels，公司云桌面无需 Docker、WSL2、Node.js、uv 或数据库服务。
5. 已完成 Standalone 核心单元测试、SQLite/本地存储真实 smoke 和完整应用 lifespan smoke；
   已新增不依赖 Docker 的 Windows 长时稳定性探针 `deploy/standalone/soak.ps1`，只记录健康状态、
   延迟和进程元数据，并在 Windows Bundle CI 中执行短窗口验证；已新增
   `standalone-compact-transfer-v1` 逐表/逐 Artifact 迁移工具及 Windows/Compact 包装脚本；试点与迁移
   责任人、证据字段和签署模板见 `docs/operations/standalone-pilot.md`，当前仍需 Windows x64 云桌面
   实机 72 小时真实观察与 Standalone→Compact 真实迁移演练。

## 已完成：V4 S32～S36 小型化与公司可部署性

1. `full` 保持现有隔离 Worker 拓扑；`compact` 显式使用合并 Worker，并公开可机器验收的
   `/api/v1/runtime-profile` 运行契约。
2. Compact 与 Full 共享 PostgreSQL/Alembic、Redis 和 MinIO 语义；不引入 SQLite、本地 Artifact
   或进程内队列产品分支。
3. Compact 基线收缩为 Web、API、合并 Worker/Beat、PostgreSQL、Redis 和 MinIO 六个容器；
   默认容器内存上限合计约 2.6 GB，只向 Loopback 发布 Web 与 MinIO API。
4. 配置层会拒绝 Compact 误开 Performance Lab 或 Environment Lab，避免将任务发送到缺少
   k6/DinD 的运行时。
5. ARM64 真实 Compose 已完成源码构建、六服务健康检查、Readiness 和 S32 业务 smoke；
   smoke 覆盖登录、项目/API/Workflow 创建、不可变发布、合并 Worker 执行与 Snapshot。
   空闲实测约 918 MiB，未发现 Backend/Worker ERROR、CRITICAL 或 Traceback。
6. Docker-only 备份已对非空 PostgreSQL 和 1 个 MinIO Artifact 生成 custom dump 与 SHA-256 清单；
   备份后项目数从 2 增加到 3，覆盖恢复后回到 2 且新项目不存在，对象集哈希相同。
   恢复后再次执行上传、Workflow 发布和合并 Worker 验收通过。
7. S33 已将基础 Compose 与源码构建 Overlay 分离；Backend/Worker 复用单一镜像，
   私有仓库脚本为 5 个镜像输出 `repository@sha256` 不可变引用。
8. ARM64 真实离线包为 353 MiB；在删除离线 Tag 后从 `images.tar` 重新导入，逐文件摘要、
   5 个镜像 ID/架构、`--pull never --no-build` 六服务启动及 S32 业务 smoke 全部通过。
9. 无外网升级演练先对 5 个真实 Artifact 生成一致性备份，再切换新包的 5 个镜像；
   升级后 Readiness、Artifact 上传/下载、Workflow 发布与执行均通过。
10. S34 实测 1000 次 Live API 在 25 并发下零失败，吞吐约 462 req/s、P95 约 154 ms；
    24 次真实持久化 Workflow 在 6 并发下零失败，P95 约 453 ms，全部 Celery 队列归零。
11. 短周期稳定性探针零失败、零容器重启、零队列积压；Full↔Compact 直接共享卷切换已
    双向验证两组 Project、Artifact、Workflow Version 和 Execution Snapshot。72 小时真实试点不以短测代替。
12. 本机回环 Registry 已真实推送 Backend、Frontend、PostgreSQL、Redis 和 MinIO 五个 ARM64 镜像，
    输出 5 条仓库返回的 `repository@sha256` 引用；发布 Tag 带架构后缀。
13. 当前完整门槛：后端 348 passed/3 skipped、总覆盖率 90.54%；前端 43 文件 167 passed，
    Statements 87.71%、Branches 80.76%、Functions 86.42%、Lines 89.69%；格式、Ruff、mypy、Lint、
    TypeScript、生产构建、Compose 解析和真实 Chromium 登录/质量总览均通过。
14. S35 真实诊断目录含 13 个白名单文件、9 个成功探针和逐文件 SHA-256；精确扫描确认管理员口令、
    数据加密密钥、应用密钥和 MinIO 口令均未命中，且不收集 `.env`、原始日志、对象名称/内容或业务载荷。
15. ARM64 回滚演练对 11 个对象生成一致性备份；一次性 Project/Artifact 在首次恢复后消失，恢复后
    再次写入成功，第二次恢复后探针再次消失且 6 服务健康。S35 离线开发包的 23 个内部文件摘要
    全部通过并包含 5 个新运维工具；PR #38 的 amd64 远程 CI 已复验，自动化不能代替维护窗口审批。
16. S36 使用不同离线 Tag 完成真实双版本演练并以最终脚本对 12 个对象复跑：新版本 6 服务全部健康后
    注入失败，自动恢复旧数据、Artifact 和旧镜像，命令保持非零，证据为 `rolled_back`；失败路径未向新目录
    复制 `.env`。随后正常升级为 `passed`，新目录以 `0600` 激活旧配置，运行镜像全部切换到 S36，
    S32 登录、Artifact、Workflow 发布/执行及 Snapshot 业务 smoke 通过。
17. 双版本演练发现离线主机安装 Git 但解压目录不是仓库时，旧备份脚本会因 `git rev-parse` 失败；
    现由新升级器调用新备份工具并显式记录旧包 `SOURCE_REVISION`，普通离线备份也会回退读取包内元数据。
    两份升级 JSON 均未命中管理员口令、数据加密密钥、应用密钥或 MinIO 口令；PR #38 的 amd64
    远程 CI 已复验失败自动回滚、正常升级和业务 smoke。
18. GitHub 首页和公司电脑快速部署手册已补齐联网源码、Windows/WSL2、私有仓库与完全离线三条入口，
    并明确首次登录、内网 TLS、备份、事务式升级及 Secret/业务数据不得提交 Git 的边界。
19. PR #38 提交 `24ce92d` 的 Backend Test/Integration、Compact/Full Compose、Security 和 V2→V3 Upgrade
    六项远程检查全部通过。Compact CI 在所有验收结束后保留 7 天的 `amd64` 离线候选包与外部
    SHA-256，目标公司电脑无需 Git、Python 或 Node.js；候选包不等于正式 Release 或试点签署。

## 已完成：S30 Failure Intelligence 与 AI Draft Change Set

1. 已实现 Failure Cluster、Regression Baseline、可解释 Release Risk 与不可变证据指纹；AI Change Set
   固定 Impact/Risk 来源，只允许逐项接受或拒绝，接受后仅生成 Test Case/Workflow 草稿。
2. AI 不能通过旧 Suggestion 接口绕过 Change Set 审核，不能发布、执行、修改权限或创建 Credential；
   目标草稿发生漂移时以稳定冲突错误拒绝覆盖。
3. `20260813_0027` 已在真实 PostgreSQL 完成升级、`alembic check`、降级和再次升级；前端 3 个原失败
   场景、MSW Handler、Ant Design 弃用 API 与异步动画竞争均已修复。
4. 本地完整质量检查曾达到后端 300 passed/3 skipped、总覆盖率 90.43%，前端 150 passed，
   Statements 87.12%、Lines 89.08%；独立干净 Compose 完成 S3–S30 smoke 与 Playwright 回归。
5. PR #33 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images 和 Compose
   Smoke 五项检查全部通过；最终提交经评审后于 2026-08-14 squash 合并至 `main@bfa80fd`。

## 已完成小阶段：S31 Release Gate 与全局搜索

1. 新增独立 `ReleasePolicy` 与无 `updated_at` 的 `ReleaseDecision`；每次判断固定策略、质量、契约、
   Impact、Release Risk、性能和 Runner 证据快照，并保存 SHA-256 指纹与六类可解释 PASS/BLOCK 原因。
2. Release Decision API 只提供创建、列表与详情，不提供更新/删除；ORM 更新与删除事件也会拒绝变更。
   策略后续修改不影响历史 Snapshot 和指纹，跨项目、证据不匹配、停用策略和未知证据均使用稳定错误码。
3. 新增中文“发布门禁”页面，可配置阈值、绑定六类证据、生成判断并查看只读历史；页面 Statements
   96.92%、Branches 80.43%、Lines 98.33%。禁用的 V3 证据能力按 `/v3/features` 停止查询，避免将
   预期的 404/409/503 当作页面错误；Quality Gate 非必需策略可在不绑定 Gate 时创建。
4. 新增受项目/团队权限约束的全局搜索，覆盖项目与 API、Workflow、Case、Suite、Plan、Environment、
   Mock、Performance、Contract、Impact、Quality、Risk、Release Policy 等核心资产；不索引 Credential、
   Secret、执行日志、请求体或响应体，且对 SQL LIKE 通配符进行字面量转义。
5. `20260813_0028` 已在独立 PostgreSQL 完成全链升级、`alembic check`、降至 `0027`、再次升级和
   `alembic check`；临时数据库已删除，原数据卷未修改。
6. 当前全量本地证据：后端 342 passed/3 skipped、总覆盖率 90.86%；Release Gate Domain 100%、
   Service 98%、Repository 98%、API 100%。前端 159 passed，Statements 87.36%、Branches 80.50%、
   Functions 85.96%、Lines 89.33%，格式、Lint、TypeScript 与生产构建通过。
7. 已增加 `smoke_s31.py`、S31 Playwright 场景和 Compose CI 入口；当前源码重建后全部服务健康，smoke
   验证 PASS/BLOCK、快照不变、无 Decision 写入口和全局搜索，Playwright CLI 与仓库 Chromium 场景
   1/1 均完成“搜索 → 发布门禁 → PASS → 只读证据”；除未登录时预期的 Refresh 401 外无控制台错误。
8. 复用数据卷含 55,247 条 Workflow Execution 时，首页原实现会读取近 7 天完整 ORM/JSON 记录并阻塞
   单 Worker；现改为 PostgreSQL/SQLite 按本地日期与状态聚合。真实卷上首页汇总约 0.15 秒、搜索约
   0.11 秒，避免全局搜索被首页请求拖死。
9. PR #34 实现提交 `d885610` 的 Backend Test（2 分 50 秒）、Backend Integration（1 分 24 秒）、
   Frontend Build（8 分 54 秒）、Security Source/Images（10 分 19 秒）和 Compose Smoke
   （21 分 29 秒）五项远程检查全部通过；Compose 同一提交覆盖 S31 主路径、Team 100 Workflow/
   1000 Queue、Scale 500 Workflow/5000 Queue 和隔离备份恢复；随后已 squash 合并至
   `main@2beb2f0`，合并后 main 五项检查亦全部通过。
10. 正式 S31 仍包含完整容量/安全/备份恢复演练、全部页面试点签署及真实 14 天 RC；
    短时自动化不替代这些门槛。

## 已完成小阶段：V2→V3 原地升级与回滚

1. 演练固定并验证 `v2.0.0-rc.1@06699d54bceee091a2efac838e426cf7ef5c9c9e`，从该 tag
   导出干净源码并构建 V2 Backend/Mock 镜像，不使用当前脚本伪造 V2 应用行为。
2. V2 在 `20260812_0018` 创建真实 Project、Environment、API、Workflow、Execution 和
   Report；备份并用 `pg_restore --list` 验证 PostgreSQL custom-format dump，并对非空 MinIO
   对象生成 SHA-256 清单。
3. 同一数据集已完成 `0018 → 0028 → 0018 → 0028`；两次升级后 `alembic check`
   无漂移，V3、回滚后 V2 和重新升级后 V3 均能读取旧资产、保留旧报告并完成新执行。
4. 演练在首次升级后创建 V3-only Release Policy，并确认 destructive downgrade 会删除该
   V3 证据，但不损坏 V2 资产；三个阶段的 MinIO 对象集和哈希均与升级前清单一致。
5. 新增 `deploy/upgrade/compose.yaml`、`verify_v2_v3_upgrade.sh`、资产验证器和独立
   `V2 to V3 Upgrade CI`；每次使用独立 Compose Project/卷/端口，成功或失败都清理临时资源。
6. 2026-08-14 本地 ARM64 Docker Desktop 完整演练通过；PR #35 实现提交
   `3b7921a` 的 V2 to V3 Upgrade CI（7 分 52 秒）与 Security CI（13 分 26 秒）均通过。
7. 上述自动化证据不等于 V2/V3 连续 14 天 RC，不得因此创建 `v2.0.0` 或
   `v3.0.0` 正式标签。

## 已完成小阶段：S31 服务目录产品化

1. 新增项目级 `/projects/{projectId}/services` 独立路由、侧栏入口和兼容跳转；页面继续复用 S27
   Contract Hub 服务接口，没有复制业务模型或建立第二套目录数据。
2. 页面展示真实服务数量、OpenAPI/Pact 契约数量、失败验证、协议类型、Consumer/Provider 角色、
   依赖数量和更新时间，并提供到契约中心及影响分析的稳定资产深链，不伪造健康状态。
3. Contract Hub Feature Flag 关闭时保留路由并停止服务、摘要和依赖图请求；Viewer 只读，登记表单
   使用与后端一致的服务标识约束，页面和搜索结果不读取 Credential、Secret 或执行敏感数据。
4. 全局搜索的 `contract_service` 结果改为服务目录路径并保留稳定 UUID `focus` 参数；真实 Compose
   Chromium 已完成“页面登记服务 → 搜索 API 返回服务目录深链 → 键盘选择 → 聚焦行 → 契约链接”验收。
5. 本地完整门槛：后端 343 passed/3 skipped、总覆盖率 90.83%；前端 164 passed，Statements
   87.53%、Branches 80.60%、Functions 86.21%、Lines 89.51%，服务目录页面 Lines 96.92%；格式、
   Lint、mypy、TypeScript 和生产构建全部通过。S31 Playwright 文件 2/2 通过，Compose 功能开关及
   既有持久卷在验收后已恢复原状态，15 个服务均健康。
6. Draft PR #36 的 Compose CI 在新增测试项目后暴露全局项目选择器只加载首页 100 条，使旧项目
   深链被误判为不可访问。现在有项目深链时立即并行使用已授权的项目详情 API 按 ID 补取，不等待首页列表，
   并在列表返回后合并到选择器；
   只有详情 API 确认不可访问才返回全局首页。含 183 个项目的复用数据卷上，V1 通过全局搜索进入旧项目与
   S31 两个 Chromium 场景合计 3/3 通过，V1 深链刷新另外连续 10/10 首次通过。
7. PR #36 最终源码提交 `6e738e5` 的 Backend（run `31825085814`）、Frontend（run
   `31825085872`）、V2→V3 Upgrade（run `31825085810`）、Security（run `31825085819`）和
   Compose（run `31825085974`）五项 CI 全部通过。Compose 完成 18/18 非 S29 浏览器、S29 浏览器、
   Team 100 Workflow/1000 Queue、Scale 500 Workflow/5000 Queue 与隔离备份恢复；Playwright 注解
   无 flaky、Retry 或失败。
8. 本小阶段不等于完成其余 V3 页面试点、容量/安全/备份恢复签署或 V2/V3 连续 14 天 RC；未创建
   正式标签，也未开始 V4 S32。

## 已完成（本地）：S31 质量指挥中心产品化

1. 将原“工作台/首页”产品化为 16 张 V3 UI 基准中的“质量指挥中心/质量总览”，保留全局
   `/dashboard` 与项目 `/projects/{projectId}/dashboard` 深链，不改变项目上下文选择规则。
2. 全局视图只使用现有 Dashboard 聚合接口，展示授权范围内的项目、API、Workflow、今日执行、
   终态通过率、7 日趋势和最近运行；不向任意项目发起 Risk、Impact、Flaky 或 Release 请求。
3. 项目视图读取真实 Dashboard Summary、最新 Release Risk/Failure Cluster/Recommended Test、
   Impact Coverage/Gap、Flaky 资产及不可变 Release Decision；所有“最新”记录均复用服务端
   `created_at DESC` 顺序，不在前端伪造风险、覆盖率或发布状态。
4. `quality_intelligence` 和 `impact_engine` 关闭时停止对应 API 请求并展示明确能力状态；Flaky 与
   Release Decision 继续使用既有项目授权接口。首页只读展示历史 Fingerprint 和阻断原因，不提供
   重算、修改、发布或自动执行推荐测试入口。
5. 页面提供影响分析、质量洞察和发布门禁稳定深链；导航文案同步为“质量总览”，认证 Setup、V1
   深链及 S15 资产验收同步使用新名称。
6. 本地门槛：后端 343 passed/3 skipped、总覆盖率 90.86%；前端 43 文件 167 passed，Statements
   87.71%、Branches 80.74%、Functions 86.42%、Lines 89.69%，Dashboard 页面 Lines 100%、
   Branches 90.78%；格式、Lint、mypy、TypeScript 和生产构建全部通过。
7. 真实 Compose 使用显式开启的 Contract Hub、Impact Engine 和 Quality Intelligence 完成 S31
   Chromium 3/3 首轮通过，其中新增“创建不可变 PASS 判断 → 质量指挥中心 → 候选版本/深链”场景
   用时 654 ms；恢复默认关闭状态后 V1 Chromium 1/1 通过，15 个服务均健康。
8. PR #37 源码提交 `74d76ef` 的 Frontend（run `31857200389`）、Security（run
   `31857200448`）和 Compose（run `31857200387`）三项受影响路径 CI 全部通过；本次未修改
   Backend、迁移或升级脚本，因此 Backend 与 V2→V3 Upgrade 工作流按 `paths` 规则不触发，后端
   四项门槛使用上述本地结果。Compose 完成 19/19 非 S29 浏览器、S29 浏览器、Team 100 Workflow/
   1000 Queue、Scale 500 Workflow/5000 Queue 与隔离备份恢复；Playwright 注解无 flaky、Retry
   或失败。
9. 本小阶段仍须完成 PR #37 最终评审与 squash 合并；它不等于其余 V3 页面试点、发布签署或
   V2/V3 连续 14 天 RC，未创建正式标签，也未开始 V4 S32。

## 已完成（本地）：S29 PostgreSQL Runner Fabric 与 Worker Plane

1. 新增管理员 Worker Pool、一次性注册令牌、Runner 身份/心跳、Drain/Resume/Disable、Task、
   Lease、Fence 和 Event API；高熵 Token 只保存 SHA-256 查找哈希，明文只返回一次。
2. `20260812_0026` 扩展 Pool/Runner/Project 容量字段，并创建 Registration Token、
   Runner Task、Lease 和 Event；唯一约束、检查约束、索引和降级路径完整。
3. Workflow 在 Runner Fabric Flag 开启时将加密 Snapshot 固定到 PostgreSQL Task；Claim 通过
   `SKIP LOCKED` 认领并原子递增 Fence，Complete/Fail/Renew/Progress 必须同时匹配
   Runner、Lease、Task 和 Fence，旧 Worker 无法重复写入终态。
4. 高并发实测曾发现 Runner/Pool/Project 行锁与 Event 外键 Key Share 的反向锁链；最终改为
   分命名空间的 PostgreSQL 事务 advisory lock，并把 Progress 续租与 Event 合并为同一事务。
   修复后最终容量时间窗无 `deadlock detected`、429 或 500。
5. Runner 控制面使用独立的按 Token 限流桶，默认 5000/分钟；通用用户写接口仍保持
   120/分钟，没有为容量测试放宽业务安全门槛。
6. 独立 Async Runner Agent 在执行前校验计划 SHA-256，运行现有 Workflow Engine 与 Host/CIDR
   出站策略，对 408/425/429/5xx 和传输错误保持存活；结果类型、节点唯一性和 8 MiB
   上限由控制面再验证。
7. Docker Runner 以 UID/GID 65532、只读根文件系统、Drop ALL 和 `no-new-privileges`
   运行；Kubernetes 参考 Deployment 还禁用 ServiceAccount Token、开启 RuntimeDefault seccomp、
   设置资源上限并规定每 Token 单副本。S29 不接收用户 Compose、Shell、Plugin 或宿主凭据。
8. 中文“执行面”页面展示 PostgreSQL 事实源摘要、Pool/Runner/Task/Lease/Fence/Event，支持
   Pool/注册令牌创建、Drain/恢复/停用和事件详情；空状态、错误、分页与中文选择器均有测试。
9. 后端全量 Ruff format/check、mypy 264 个源文件、依赖边界与 pytest 通过：293 passed、
   3 skipped，总覆盖率 90.57%，Runner Fabric Service 96%、Repository 99%、Domain 96%。
10. 前端格式、ESLint、TypeScript strict、145 项测试、覆盖率和生产构建通过：Statements
    86.92%、Branches 80.72%、Functions 85.06%、Lines 88.90%；执行面页 Statements 92.37%。
11. 真实 PostgreSQL 17 在一次性容器中完成 `0025 → 0026 → 0025 → 0026` 与
    `alembic check`；PostgreSQL/Redis/MinIO 集成测试 3 passed。
12. 最终 ARM64 Compose 容量夹具 `df313b29-5827-496d-b0db-ca81fc48ea74` 确认
    5000 个唯一排队任务和加密计划，500/500 Workflow、500/500 Task、1000 个唯一节点终态、
    0 重复、0 Active Lease、0 制品冲突、2 个实际 Worker；提交 P95 2.141591 秒，总耗时
    144.893 秒。
13. 最终故障转移夹具项目 `521b8519-96b3-4867-83ad-5fe7e07f8c38`：Agent A 认领后中断，
    Agent B 以 Fence 2 完成第 2 次尝试，Workflow passed 且只有 3 条预期节点终态。Playwright
    在真实 Compose 中 1/1 通过，覆盖真实登录、侧栏、事实告警、expired/terminal Event、
    Drain/恢复、详情、Pool 与注册令牌。
14. 整套 Compose 从最终代码重建后 Backend、Frontend、General/Data/AI/Performance/Environment Worker、
    Beat、PostgreSQL、Redis、MinIO、Redpanda 和目标服务全部健康；Dockerfile 默认最终阶段已恢复
    Application Runtime，Beat/AI Worker 不再误用 Runner Entrypoint。
15. Ruff 安全规则、Python/前端依赖审计和 `flowtest-runner:ci` Grype v0.116.1
    High/only-fixed 门槛通过；只使用现有 CPython 3.13.15 精确误报台账，本轮没有新增例外。
16. S29 决策记录为 `ADR 0025`，架构、部署、监控/容量、升级/回滚和威胁模型已同步。
17. 实现提交 `030ed2a` 与本地验收文档提交 `a1c2814` 已推送并创建 Draft PR #32。首轮
    Backend Test（2 分 22 秒）与 Integration（1 分 17 秒，run `31614733014`）、Frontend Build
    （8 分 22 秒，run `31614732898`）和 Security Source/Images（9 分 8 秒，run
    `31614732960`）通过。
18. 首轮 Compose Smoke（run `31614733061`）实际启动并在 S5 失败，不是账户计费阻塞：Job 级
    `FLOWTEST_FEATURE_RUNNER_FABRIC_ENABLED=true` 使旧 S5 Workflow 进入 PostgreSQL Runner Queue，
    但 S29 Runner 尚未注册，因而执行一直处于 queued。最小修复将 S29 功能开关限制在 S29
    Smoke、浏览器和容量窗口，并在其余回归中恢复 Celery；为保证 Backend 重建后不丢失 S18–S28
    功能开关，这些既有开关提升为 Job 级环境。修复后必须重跑五项 CI。
19. 编排修复提交 `7e40dfc` 的 Backend Test（2 分 18 秒）与 Integration（1 分 10 秒，run
    `31616461170`）、Frontend Build（8 分 20 秒，run `31616461166`）和 Security Source/Images
    （10 分 36 秒，run `31616461286`）通过。Compose（run `31616461215`）已通过 S3–S11、S29
    Smoke 与 S29 浏览器、Runner→Celery 恢复，但 S22 浏览器用例仍假设 Runner Pool 为空；S29
    Smoke 已按设计持久化 Pool，因此旧空表文案不存在。S23 在 CI 首次选择器超时、重试通过，本机
    资源抖动下又耗尽 90 秒场景预算，后端未收到 Reflection POST；将真实 GraphQL+gRPC 双链路预算
    调整为 180 秒，并把可见“明文”分段定位限定到具体 Dialog/Tab。S22 最小修复改为验证 Runner
    清单列结构；两处均保留请求成功和 S29 真实 Pool/Runner/Fence 的原有业务断言。本机保留 S29
    Pool 的 Celery 栈上 S22 通过（13.6 秒）；S23 复跑期间 Docker Desktop 全局失去调度，`/live`
    同步超时且安全策略请求由 Nginx 返回 504，不能记作通过，最终以全新 Linux CI Runner 为准。
20. 浏览器稳定性修复提交 `e8ef455` 的 Backend Test（2 分 19 秒）与 Integration（1 分 7 秒，run
    `31620507777`）、Frontend Build（8 分 1 秒，run `31620507771`）和 Security Source/Images
    （9 分 39 秒，run `31620507745`）通过。Compose run `31620507971` 首次在构建 PostgreSQL
    镜像时从 GitHub Release 下载固定校验和 WAL-G 遇到 `curl (56) Connection died`，属于外部下载
    瞬断；同一提交只重跑失败 Workflow 后 attempt 2 在 27 分 58 秒内通过。
21. Compose attempt 2 完成 S3–S29 冒烟、S29 Runner→Celery 双向切换、S29 浏览器 1 passed 和
    非 S29 浏览器 15 passed（1.9 分钟，无 flaky）、Kafka 兼容、API/Workflow/1000 任务容量与隔离卷
    备份恢复。S29 CI 容量项目 `6d4554fc-8009-47ed-8aac-d260998e6a02` 完成 5000 个唯一排队执行与
    加密计划、500/500 Workflow 和 Task、1000 个唯一终态节点、0 重复、0 Active Lease、0 制品
    冲突、2 个实际 Worker；提交 P95 3.376032 秒，总耗时 218.597 秒。最终文档提交仍须重跑五项
    CI；未合并、未开始 S30，也未创建任何新 V3 标签。
22. 最终文档提交 `113458a` 的 Backend Test（2 分 22 秒）与 Integration（58 秒，run
    `31623263953`）、Frontend Build（8 分 5 秒，run `31623263861`）和 Security Source/Images
    （8 分 35 秒，run `31623263885`）通过。Compose run `31623263871` 已通过 S3–S11、S29 Smoke、
    S29 浏览器与 Runner→Celery 恢复，但 S15 首次运行通过资产创建后，计划资产类型用无作用域文本
    点击且未等待条件字段，耗尽 90 秒；Playwright 重试又复用同一名称，创建请求未被显式验证。
    最小修复为每次重试加入唯一后缀，所有 UI 创建操作等待并验证对应 POST 2xx 和 Dialog 关闭，
    Ant Select 使用可见 Dropdown 作用域，并将完整 S15 真实链路预算调整为 180 秒。修复后必须重跑
    完整五项 CI。本机缩减非必要服务后的真实 Compose 栈 S15 1/1 通过，场景 18.2 秒；前端
    145 项覆盖率、格式、ESLint、TypeScript strict 与生产构建再次通过。未合并、未开始 S30，
    也未创建任何新 V3 标签。

## 已完成：S28 变更影响引擎与确定性测试选择

1. 新增 Git Unified Diff、OpenAPI、GraphQL SDL 与 gRPC Proto 四类受控变更源；领域解析器不访问外部
   Git、不接收仓库凭据或脚本，只处理有界文本和已登记 Schema，限制 2 MB、500 文件、100,000 行与
   5,000 个规范化变更。
2. 新增项目级显式 Asset Mapping，将精确或尾部 `*` Source Selector 映射到现有 Test Case、Workflow、
   OpenAPI Contract、Pact Contract 或 Performance Scenario；拒绝跨项目、未知目标和超过 2,000 条映射。
3. `explicit_mapping_v1` 选择器按稳定键排序并去重，不使用不可解释启发式推断；未命中的变更保留为
   Coverage Gap，不会被虚构为已有测试覆盖。
4. 每次 Impact Run 持久化规范 Changes、Change→Impacted→Recommended 图、选择原因、Coverage Matrix、
   Gap、摘要与 SHA-256 Fingerprint，并独立保存 Test Selection 与 Coverage Snapshot，支持历史审计。
5. 中文“变更影响分析”提供 Mapping 管理、四类 Diff 输入、三列影响图、证据原因、Coverage Matrix、
   Gap 与历史下钻；S28 只给出推荐集合，不自动执行测试或改变既有发布门禁。
6. 新增双向迁移 `20260812_0025`；真实 PostgreSQL 已完成 `0024 → 0025 → 0024 → 0025`，最终
   `alembic check` 无漂移。
7. 后端 Ruff format/check、mypy strict、依赖边界及 278 passed/3 skipped 通过，总覆盖率 90.58%，
   Impact Domain 98%；Python 依赖审计和 Ruff 安全规则无已知问题。
8. 前端格式、ESLint、TypeScript strict、142 项测试与生产构建通过；Statements 86.70%、Branches
   80.50%、Functions 84.89%、Lines 88.72%。前端生产依赖审计无已知高危漏洞。
9. 真实 ARM64 Compose 冒烟完成四类 Diff、显式映射、确定性去重、100% Coverage、四条解释边和
   PostgreSQL 持久化；项目 `34869b0f-a790-4c73-a57b-3f2c4e868c97` 的 Impact Run
   `f44a2916-289c-46a8-982b-4da2cfc9d027` 指纹为
   `09af485bf9b86debe1febcd5a1e42970201fd58d865e73f4060d97d812b1e6d2`。
10. 真实 Chromium 已完成“创建 Mapping → Git Diff 分析 → 三列图与原因 → Coverage Matrix → 历史”
    1/1，场景耗时 8.9 秒、总耗时 11.1 秒；过程中修复 Ant Select Portal 与成功提示造成的选择器歧义，
    最终复跑通过。
11. 实现提交 `54a4061` 与本地验收文档提交 `a464fa2` 已推送并创建 Draft PR #31，架构边界记录于
    `ADR 0024`。本地没有 Grype/Trivy 二进制，因此 Backend/Frontend 镜像交由 Draft PR 的 Security
    Source/Images 使用既有 High/Critical 门槛扫描；结果见下一项。在最新提交五项 CI 全绿前不合并、
    不创建 `v3.0.0-beta.3`，也不开始 S29。
12. Draft PR #31 的提交 `5f3f7d4` 已通过 Backend Test（2 分 12 秒，run `31597011115`）、Backend
    Integration（1 分 13 秒，同一 run）、Frontend Build（7 分 28 秒，run `31597011124`）、Security
    Source/Images（9 分 43 秒，run `31597011152`）和 Compose Smoke（14 分 47 秒，run
    `31597011135`）。Compose 同一提交完成 S3–S28、Apache Kafka 兼容、API/Workflow 容量、1000 任务
    持久队列和隔离卷备份恢复；最终验收文档提交仍须复跑全部 CI。
13. 最终文档提交 `5f5da5a` 的 Backend Test（2 分 10 秒）与 Integration（1 分 9 秒，run
    `31598296375`）、Frontend Build（5 分 39 秒，run `31598296441`）、Security Source/Images
    （9 分 57 秒，run `31598296383`）和 Compose Smoke（17 分 54 秒，run `31598296388`）五项全绿。
    PR #31 随后标记 Ready 并 squash 合并至 `main@05e7cc3eb4229b40c4c63619469879d00b1386fc`，
    远端 `agent/s28-impact-intelligence` 已删除。
14. 合并提交触发的 Backend（run `31599845096`）、Frontend（run `31599845036`）、Security（run
    `31599844926`）和 Compose（18 分 47 秒，run `31599844971`）全部成功；Compose 再次通过 S3–S28、
    Kafka、容量与隔离恢复。S15 浏览器用例首次未找到新建行，Playwright 自动重试后通过，工作流留下
    flaky 注解但最终 14 passed。满足门槛后，annotated `v3.0.0-beta.3` 已固定到 `05e7cc3` 并推送。

## 已完成：S27 Pact 契约中心与发布兼容矩阵

1. 新增项目服务目录、不可变 Pact Contract Version、Provider Verification 和 Deployment
   Compatibility Check；Pact 导入自动登记 Consumer/Provider，使用规范 JSON SHA-256 去重。
2. 领域解析器仅支持有界 HTTP Exact Matcher，拒绝 Message Pact、Matching Rule、Generator、
   Plugin、认证/Cookie/Secret、超大文档和过深结构；解析后的类型 Snapshot 不保存原始敏感内容。
3. Provider 验证只接受无凭据、Query、Fragment 和 Path 的 HTTP/HTTPS Origin，关闭重定向和
   系统代理，每个 Interaction 执行项目出站策略；Provider State 只能请求同 Origin 固定路径。
4. 可选 Pact Broker 的 Origin 和 Token 只由部署配置，用户坐标经路径编码，Token 不持久化或回传；
   Broker 和 Provider 出站拒绝均转换为稳定、可审计错误证据。
5. OpenAPI Contract Run 可绑定服务和 Provider 版本。Deployment Check 聚合指定版本的最新 Pact
   验证和 OpenAPI Breaking Change：阻断证据为 `unsafe`，证据缺失为 `unknown`，全部通过才为 `safe`。
6. 中文“契约中心”统一展示 OpenAPI/Pact 资产、服务依赖图、动态 Provider 兼容矩阵、
   验证失败证据和持久化发布判断；页面允许合法 Compose 内部 HTTP Origin。
7. 新增双向迁移 `20260812_0024`；真实 PostgreSQL 完成 `0023 → 0024 → 0023 → 0024`，
   `alembic check` 无漂移。
8. 后端全量 273 passed、3 skipped，总覆盖率 90.28%，Pact Domain 99%；Ruff format/check、mypy
   strict、依赖边界和 Bandit 规则通过。前端 139 passed，Statements 86.34%、Branches 80.49%、
   Functions 84.37%、Lines 88.39%，格式、ESLint、TypeScript strict 和生产构建通过。
9. 真实 ARM64 Compose 冒烟已请求 `mock-target` Provider，验证 Pact 成功、Exact Body Mismatch、
   OpenAPI 绑定、兼容矩阵以及 safe/unsafe 判断；项目
   `5205f2c2-a239-4b61-bda4-cc9e236bff60` 的两条发布判断证据均已持久化。
10. 真实 Chromium 完成“Pact 导入 → Provider 验证 → OpenAPI 绑定 → 矩阵 → 安全发布判断 →
    统一资产” 1/1，最终耗时 5.0 秒；首轮检出 Ant Modal Portal 选择器歧义，已改为可见 Modal/
    精确 Combobox 定位并复跑通过。
11. Python 与前端依赖审计无已知漏洞；本轮重建的 Backend/Frontend 镜像使用 CI 相同
    Grype 0.116.1、`only-fixed` High/Critical 门槛通过，无新增漏洞豁免。
12. 架构边界已记录于 `ADR 0023`；实现提交为 `8ec92a3`，本地验收文档提交为
    `f9ba039`。最终文档提交 `0daab31` 的 Backend Test（2 分 16 秒）、Backend Integration（1 分
    4 秒）、Frontend Build（7 分 32 秒）、Security Source/Images（10 分）和 Compose Smoke（18 分
    32 秒）五项全部通过；Compose 同一提交完成 S3–S27 回归、Apache Kafka 兼容性、API/Workflow 容量、
    1000 任务持久队列和隔离卷备份恢复。
13. PR #30 首轮 Backend Test 在测试前的 Ruff format 门槛失败：本地从仓库根目录格式化
    `scripts/smoke_s27.py` 时未套用 `backend/pyproject.toml` 的 100 字符配置，CI 在 `backend` 工作目录使用
    项目配置后识别出差异。已使用 CI 的精确命令重新格式化，并在本地通过对全部 Backend 与
    `scripts/*.py` 的 Ruff format/check、mypy 以及依赖边界检查；该失败是真实格式门槛，不归因于计费或容量。
14. PR #30 标记 Ready 后已 squash 合并至 `main@83375d20a2726c1088d1afaa6c660863246fed5f`，远端
    `agent/s27-contract-matrix` 已删除；合并后的 main 工作流全绿，annotated tag
    `v3.0.0-beta.2` 已固定到同一提交并推送。

## 本地验收完成：S26 签名环境实验室

1. 新增管理员注册、创建版本和停用的 `EnvironmentTemplate`，版本保存规范 JSON、SHA-256 与平台
   HMAC-SHA256-v1 签名；普通项目成员只能 Provision 已启用的签名版本。
2. 声明式契约只允许固定 Digest 镜像、依赖顺序、受限环境变量、HTTP/TCP Health Check、资源上限、
   TTL 和平台内置 `HTTP_GET_V1` Seed；不接收 Compose、命令、Entrypoint、脚本、Secret、设备或卷。
3. 镜像同时受 OCI Digest 校验和部署级精确白名单约束。独立 `environment` Celery 队列由 UID/GID 65532、
   只读根文件系统、Drop ALL 和 `no-new-privileges` 的 Worker 消费，不挂载宿主 Docker Socket。
4. 独立 DinD daemon 不发布宿主端口；Runner 将签名契约翻译为固定 Docker CLI 参数数组，创建隔离 bridge、
   非 root/只读/无 Capability 容器、随机宿主端口及 CPU、内存、PID 上限，不经过 Shell。
5. `EnvironmentInstance` 保存模板 Snapshot、签名、Fencing Token、端点、Seed 证据、TTL 和 Cleanup 状态；
   Idempotency-Key、Label 枚举、Beat Reconciler 与同一清理任务覆盖失败、超时、取消、TTL、消息重投和
   Runner 重启后的幂等回收。
6. 新增中文“环境实验室”深链接，覆盖模板注册、版本、停用、项目 Provision、状态、端点、Seed/隔离
   证据和清理；页面没有任意 Compose 或脚本入口。
7. 新增双向迁移 `20260812_0023`；真实 PostgreSQL 已完成 `0022 → 0023 → 0022 → 0023`，最终
   `alembic check` 无漂移。
8. 后端最终全量为 270 passed、3 skipped、总覆盖率 90.05%；Ruff、mypy strict、依赖边界和
   Python 依赖审计通过。镜像白名单启动校验已收紧为完整 OCI Digest 格式并有回归测试。前端 133 项通过，
   Statements 85.99%、Branches 80.14%、Functions 84.00%、Lines 88.15%，格式、Lint、TypeScript
   strict 与生产构建通过。
9. 真实 ARM64 Compose 已完成模板 v2、独立队列 Provision、Health、Seed、端点、Worker 停止/恢复、
   队列清理和重复 Cleanup；最终实例 `f61af547-4813-4529-bda3-2499da147ea1` 已清理。真实 Chromium
   最终复跑完成“注册 → 新版本 → Provision → Ready/证据 → Cleanup”1/1，耗时 27.5 秒。
10. Python 与前端依赖审计通过。Environment Runner、定制 Docker 29.7.2/containerd v2.3.3 daemon
    和固定 nginx fixture 均通过既有 Grype `only-fixed` High/Critical 门槛；没有新增漏洞豁免。
11. 实现提交 `5c68bdf` 已推送并创建 Draft PR #29；最新提交 `2455da3` 的 Backend Test、Backend
    Integration、Frontend Build、Security Source/Images 和 Compose Smoke 全部通过，PR 随后标记 Ready
    并 squash 合并至 `main@2434db3`。GitHub 已自动删除远端 S26 分支。
12. 合并提交触发的 Backend、Frontend、Security 与 Compose 主分支工作流全部通过；Compose 再次完成
    S3–S26、Kafka 兼容、API/Workflow 容量、1000 任务持久队列和隔离备份恢复。满足发布门槛后，annotated
    tag `v3.0.0-beta.1` 已固定到 `2434db3` 并推送。

## 本地验收完成：S25 声明式性能实验室

1. 新增 `PerformanceScenario` 不可变版本、`PerformanceRun`、门禁评价和 `20260812_0022` 增量迁移；
   支持 REST 与纯 HTTP Workflow 目标、固定 VU 和阶梯升压。
2. 固定 `K6ScenarioCompiler` 只接受带类型结构化配置，确定性生成 k6 程序与 SHA-256；拒绝用户脚本，
   关闭重定向并默认丢弃响应体。
3. 新增独立 Celery `performance` 队列和固定 digest 的 k6 2.2.0 Runner；容器以 UID/GID 65532
   非 root 运行，根文件系统只读，移除全部 Capability 并启用 `no-new-privileges`。
4. Runner 执行前重新编译并校验 Snapshot 哈希，再次执行 SSRF/DNS/CIDR 策略；超时、Runner 缺失、
   非法汇总、超限指标和阈值失败均返回稳定错误码；敏感 Header/Query/Body 在进入 Snapshot 前拒绝。
5. 原始 k6 NDJSON 指标以 Artifact 写入 MinIO，P95、失败率、请求率和计数写入 PostgreSQL；同场景
   上一次成功运行自动成为基线，并把 P95 回归与阈值证据写入现有 Quality Gate。
6. Web 新增中文“性能实验室”深链接，提供声明式场景、发布、运行、基线、阈值、门禁和 Artifact 下钻；
   内部 Compose 主机 URL 与公网 URL 均可在前端校验后交由后端安全策略处理。
7. 后端 262 passed/3 skipped，总覆盖率 90.07%，k6 编译器和进程边界均为 100%；Ruff、mypy strict、
   依赖边界通过。前端 130 项全量测试通过，语句 85.78%、分支 80.15%，生产构建通过。
8. 真实 PostgreSQL 完成 `0021 → 0022 → 0021 → 0022`，`alembic check` 无漂移；演练发现并修复
   PostgreSQL 63 字节约束名截断问题。
9. 真实 ARM64 Compose 两次 k6 验收均通过，第二次固定第一次基线，原始指标进入 MinIO；真实 Chromium
   完成“创建 → 发布 → 独立队列运行 → 阈值与产物下钻”1/1。
10. 本轮共修复五项门槛问题：前端分支覆盖率、PostgreSQL 约束名漂移、歧义 VU 选择器、内部主机 URL
    误拒绝和中文展开按钮选择器；所有对应门槛已重跑通过。
11. Draft PR #28 已创建。第二轮远端 Backend、Integration、Frontend 和 Security 全绿；Compose 已通过
    S3–S25 功能、Kafka 兼容和 API 容量，在 Workflow 容量边界失败，随后完成 CI 抖动容差修复。
12. PR #28 首轮 Security CI 发现 k6 2.1.0 二进制的 `golang.org/x/text` 和 gRPC 高危依赖已有
    上游修复版本；已升级至官方 k6 2.2.0 多架构 digest，不添加漏洞豁免。相同 Grype 0.116.1 高危
    扫描已通过，ARM64 固定编译产物完成真实 HTTP 负载兼容验证。
13. 首轮 Compose 在 S3–S25 全部功能闭环通过后，GitHub 两核共享 Runner 的 300 请求/30 并发容量
    P95 为 1.423 秒、0 失败，超过旧 CI 专用 1.2 秒阈值；保留工作量和零失败规则，将非参考宿主的
    抖动容差校准为 1.8 秒，8C/16G 正式容量基线不变。
14. 修复后 Compose 的 100 个真实 Workflow 全部通过且无丢失，P95 60.069 秒仅超过旧 CI 门槛
    68 毫秒；保留 100 并发与零失败条件，将两核共享宿主的 Workflow P95 抖动容差校准为 75 秒，
    正式参考机的 100/1000 门槛不变。
15. `3438f4a` 推送后的五项 GitHub Actions 均在 3–4 秒内、执行任何步骤前终止；Check Annotation 明确
    指向账户付款失败或 Actions spending limit。该次结果被正确记录为外部计费阻塞，而不是代码失败。
16. 2026-08-12 14:45（Asia/Shanghai）已对 `9eab87d` 的 Backend `31569796643`、Frontend
    `31569796638`、Security `31569796687` 和 Compose `31569796736` 执行重跑；五个新 Job
    `94033432944`、`94033432935`、`94033432495`、`94033431994`、`94033432684` 均在约 3 秒内失败，
    新 Check Annotation 仍明确提示近期账户付款失败或 Actions spending limit 需要提高，且无任何步骤日志。
    这仍是外部计费阻塞，不是代码失败。
17. 仓库公开后，PR #28 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images
    和 Compose Smoke 已全部重新执行并通过；PR 随后标记 Ready、squash 合并至 `main@eb2f0c8`，远端
    `agent/s25-performance-lab` 分支已删除。公开仓库已开启 Secret Scanning 和 Push Protection。

## 已完成：S24 Kafka、WebSocket 与 Exchange

1. 新增不可变 `EventSource`、`20260812_0021` 增量迁移和 `EVENT_PROTOCOLS` Feature Flag，Kafka
   固定 Bootstrap/Registry，WebSocket 固定 URL，配置 SHA-256 随 Workflow Snapshot 保存。
2. 新增 Avro、JSON Schema 2020-12、Protobuf 消息 Schema 与兼容 Registry 导入；编码/解码支持
   Confluent Wire Format，并拒绝 Schema ID 不匹配、损坏消息和超过 4 MB 的负载。
3. 新增 `kafka.produce/consume` 与 `websocket.connect/send/await/close/exchange` 七个 Capability；
   REST 输出可结构化绑定到 Kafka 消息/Correlation 和 WebSocket 消息，Endpoint/Topic/Schema 不可动态改变。
4. Kafka 使用 `confluent-kafka`，禁用 Admin、Topic 自动创建、自动提交和 Offset Store；Consume 最多
   1000 条/300 秒，Correlation 命中立即返回。WebSocket Session 固定在单次 Runner，结束无条件清理，
   连接丢失统一返回 `SESSION_LOST`。
5. 中文多协议工作台新增 Kafka Registry、Produce/Consume、WebSocket Exchange、事件源版本和 Context
   Inspector；React Flow 支持创建和配置三个常用事件节点。
6. Compose 新增固定 digest 的 Redpanda `v26.2.1`、Schema Registry 与 WebSocket Echo Mock；CI 另用
   固定 digest 的 Apache Kafka `4.3.1` 验证稳定客户端兼容性。
7. `smoke_s24.py` 已在真实 Compose 完成 Registry 导入、调试、REST→Kafka/WebSocket 混合 Workflow、
   结构化绑定及事件源/Schema Snapshot 校验；真实 Chromium 主路径 2/2 通过。
8. 后端 236 passed/3 skipped，总覆盖率 90.11%，事件运行时 95%；Ruff、mypy strict 和依赖边界通过。
   前端全量覆盖率 Statements 85.58%、Branches 80.35%、Functions 83.27%、Lines 87.75%，生产构建通过。
9. 冒烟过程中发现并修复 Kafka 命中 Correlation 后仍等待完整超时，以及纯消息 Protobuf 被错误要求
   包含 gRPC Service、损坏 Avro 泄漏底层异常三项真实缺陷。
10. 真实 PostgreSQL 已完成 `0020 → 0021 → 0020 → 0021` 和 `alembic check`；首次演练发现并修复
    Kafka Schema 阻断旧约束恢复的 downgrade 顺序缺陷。Python 与前端生产依赖审计无已知漏洞。
11. 固定 digest Apache Kafka `4.3.1` 兼容验证、Draft PR #27 的 5 项远程 CI 均通过，随后 squash
    合并至 `main@bad2b51`。

## 已完成：S23 GraphQL、gRPC 与多协议工作台

1. 新增不可变 `SchemaArtifact` 与 `20260812_0020` 增量迁移，支持 GraphQL SDL/Introspection、
   Proto/Protoset 和受 SSRF 策略约束的 gRPC Server Reflection；同内容按 SHA-256 去重。
2. 新增 `graphql.request@3.0.0` 与 `grpc.call@3.0.0` Capability，GraphQL 支持 Query/Mutation，gRPC
   支持 Unary/Server Streaming、TLS/mTLS，明确拒绝 Subscription、Client/Bidi Streaming 和超限消息。
3. Workflow 发布与加密执行计划固定 Schema/Descriptor ID、版本、哈希和规范内容；mTLS Credential
   只写、加密且绑定目标，公开 Snapshot 只保存 Credential ID。
4. 结构化绑定只允许 REST/上游输出写入 GraphQL `variables.*` 或 gRPC `request.*`，不能动态改变
   Endpoint、方法、TLS 或 Credential。
5. Web 新增中文“多协议工作台”，提供版本清单、导入、GraphQL/gRPC 真实调试、Context Inspector；
   React Flow 可创建和配置协议节点、mTLS 与结构化绑定。
6. Compose 新增确定性 GraphQL 与带 Reflection 的 gRPC 目标服务；`smoke_s23.py` 覆盖导入、调试、
   REST→GraphQL/gRPC 并行绑定及 Snapshot 固定，Playwright 覆盖真实中文工作台主路径。
7. 后端 Ruff、mypy strict、依赖边界和 236 passed/3 skipped 通过，总覆盖率 90.53%；
   `protocol_nodes.py` 96%，`protocol_runtime.py` 95%。Python 与前端生产依赖审计无已知漏洞。
8. 前端格式、Lint、TypeScript、118 项 Vitest 与生产构建通过；Statements 85.35%、
   Branches 80.01%、Functions 83.17%、Lines 87.46%，多协议工作台 Branches 92%。
9. 真实 PostgreSQL 已完成 `0019 → 0020 → 0019 → 0020`，`alembic check` 无漂移；运行中
   应用会持有 DDL 锁，因此回滚演练明确要求维护窗口内停止 API/Worker。
10. Compose 全栈健康，S3–S11、S18、S19、S21–S23 共 14 个真实冒烟链路通过；
    Playwright 在重复数据卷上 10/10 通过，并修复 S14 异步保存、S15 资产前置与 S21 名称冲突的测试隔离问题。
11. Draft PR #26 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images
    和 Compose Smoke 全绿后已 squash 合并，并创建 `v3.0.0-alpha.1`。

## 已完成：S22 Capability SDK V3

1. 已建立不可变 `CapabilityManifest`、12 个 V2 内置 Manifest、Legacy Adapter、显式 Capability
   节点契约和 Schema SHA-256；旧 Workflow 不修改存量数据。
2. 调度器统一生成 `NodeResult`，节点执行记录保留兼容字段并新增脱敏结果包；纯引擎层
   `ExecutionEvent` 增加单调序号、Attempt 与 Fencing Token 契约。
3. 已定义 Runner Control Plane 类型接口，新增 Plugin、Capability、Runner Pool、Runner 增量模型与
   `20260812_0019` 双向迁移；分布式 Lease 的 PostgreSQL 事实源保留至 S29。
4. Plugin Manifest 校验固定 OCI Digest、签名身份、能力所有权、禁网声明和容器加固开关；安装入口
   在 Cosign 与隔离 Runner 完成前保持关闭。
5. 新增 `/api/v1/v3/features`、`capabilities`、`plugins`、`runner-pools` 和 Manifest 校验接口；
   三个 Feature Flag 默认关闭，Compose 验收只开启 Capability SDK。
6. 前端新增中文“能力与插件中心”深链接、真实能力清单、Plugin/Runner 管理员边界和右侧
   Context Inspector；采用 `#5b5cf0` / `#101936` V3 Token。
7. 当前本地证据：后端 214 passed、3 skipped、覆盖率 90.85%，Ruff/mypy 通过；前端 104 项通过，
   Statements 85.01%、Branches 80.70%、Functions 82.84%、Lines 87.04%，格式/Lint/TypeScript/构建通过。
8. `0018 → 0019 → 0018 → 0019` 已在隔离真实 PostgreSQL 完成，`alembic check` 无漂移；现有 V2
   Compose 数据原地升级至 `0019`，API、Web、PostgreSQL、Redis、MinIO、General/Data/AI Worker 与 Beat 健康。
9. S22 冒烟完成 Legacy Start/End 与显式 `flow.delay@2.0.0` 混合执行，验证 Capability 版本、Schema
   哈希和 NodeResult 固定入 Snapshot；Playwright 登录、平台深链接、能力/插件/Runner 边界 2/2 通过。
10. 单 Worker 与四 Worker 均完成 100 个真实 Workflow、请求侧并发 100、零失败容量基线；分别为
    P95 3.442 秒/27.44 execution/s 与 P95 3.100 秒/31.47 execution/s，测试后恢复单 Worker。
11. 全量回归曾发现 5 项失败均源于 `skipped` NodeResult 原因码被误判为非法错误；契约调整为
    `passed` 禁止错误、`failed` 必须有错误、`skipped/cancelled` 可携带解释原因，5 项回归现全部通过。
12. Draft PR #25 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images 和
    Compose Smoke 共 5 项全部通过，随后 squash 合并至 `main@3eac7ec`。

## 已完成：S20 企业与可观测性

1. OIDC Authorization Code + PKCE、state/nonce 一次性消费、邮箱域名 JIT 和固定无权限初始身份。
2. Team 授权、Vault KV v2 Credential Provider 与本地 AES-256-GCM Provider。
3. API → Celery → Workflow → Node 的 OpenTelemetry Trace、队列/Worker 指标和 Grafana 模板。
4. 可选 WAL-G 加密归档、隔离 PITR 演练和回滚保护。
5. PR #22 首轮 Compose 容量门槛在共享 Runner 出现 P95 1.074 秒、零失败；阈值按共享 Runner 基线调整为 1.2 秒后，第二轮 5/5 CI 全绿并合并。业务零失败规则与本地 1.0 秒门槛未放宽。

## 已完成：S21 AI 助手

### 后端与数据

1. 新增 `AIJob`、`AISuggestion`、项目样本共享开关和可升降级迁移 `20260812_0018`。
2. 新增 `/api/v1/ai/status`、项目策略、Job 列表/详情、Suggestion 列表和逐项接受/拒绝接口。
3. AI Job 通过独立 Celery `ai` 队列异步执行；网关关闭或失败不影响现有产品能力。
4. OpenAI-compatible Provider 禁止重定向，生产强制 HTTPS，使用 JSON Schema 2020-12 严格输出。
5. 输入执行深度、节点数和字节上限；Password、Authorization、Cookie、Token、Secret、API Key、Bearer、Basic 与 JWT 统一脱敏。
6. 默认只发送 Schema 和脱敏元数据；样本必须由项目 Owner 显式开启并逐次脱敏，Editor 提交被拒绝。
7. 建议只能人工接受、编辑后接受或拒绝；只有接受的 Test Case/Workflow 才创建草稿，AI 不能发布、执行、创建 Credential 或修改权限。
8. 审计保存模型、提示模板版本、输入摘要哈希、Token 用量、脱敏路径和审核结果，不保存 Secret。
9. 新增离线隐私评测集 `backend/tests/fixtures/ai_redaction_evaluation.json`。

### 前端

1. 新增中文“AI 助手”项目路由、关闭状态、模型/样本策略、任务列表和人工审核工作台。
2. 支持 Schema 用例、断言、Workflow 草稿和失败归因任务；样本输入只在 Owner 开启策略后显示。
3. 接受前可编辑 JSON，畸形 JSON 在浏览器端阻断；拒绝不发送编辑内容；已审核建议不可重复操作。Job 从 pending/running 进入 completed 时会切换 Suggestion 查询键并自动刷新，避免缓存空结果。
4. 页面明确展示“AI 不读取 Secret、不自动发布、不自动执行”。

## 当前验证证据

- 后端：Ruff format/check、mypy strict、依赖边界通过；206 项通过、3 项环境跳过；总覆盖率 90.58%。
- AI 专项：Service 97%、OpenAI-compatible HTTP 100%、Redaction Domain 97%；15 项专项测试通过，另有离线隐私评测集。
- 前端：格式、Lint、TypeScript、99 项测试与生产构建通过；Statements 83.71%、Branches 80.80%、Functions 81.72%、Lines 85.67%。AI Feature Statements 92.10%/Branches 100%，AI 审核页 Branches 92.45%。
- 已验证边界：队列故障、网关断网/拒绝/畸形响应、重复 Worker 幂等、样本权限、超限审核内容、无效草稿、接受后才落库。
- 迁移：真实 PostgreSQL 完成两轮 `0017 → 0018 → 0017 → 0018`，`alembic check` 无漂移；曾发现并修复时间戳默认值与唯一约束的模型/迁移不一致。
- Compose：API、Web、PostgreSQL、Redis、MinIO、General/Data/AI Worker 与 Beat 健康；S21 真实队列/脱敏/人工接受闭环以及 S11/S18/S19 回归通过。
- Playwright：S21 中文 AI 页面真实浏览器链路 2/2 通过（包含登录 Setup）；测试曾发现并修复完成态 Suggestion 不自动刷新问题。
- 依赖与镜像安全：Python、前端生产依赖和 API/Web/Mock 发布镜像扫描全部通过。
- GitHub CI：PR #23 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images 和 Compose Smoke 共 5 项全部通过；Compose 同一提交完成 S1-S21 回归、100 并发 Workflow、1000 持久队列任务和隔离备份恢复。

## 尚未完成的发布门槛

1. 将 `v2.0.0-rc.1` 部署到真实试点环境，记录 API/Web/Worker 镜像摘要、Compose 配置、宿主机规格、试点项目和负责人。
2. 在同一 RC 候选上完成连续 14 个自然日观察和试点签署；该真实时间门槛不能由短时自动化代替。
3. RC 期间如有代码修复，必须创建新的 RC 候选并重新开始连续观察，不沿用旧候选天数。

## 下一步

1. 从 PR #38 成功的 Compact CI 下载固定 Commit 的 `amd64` 离线候选包和 SHA-256，通过公司受信
   渠道交付，在目标 Windows/WSL2 或 Linux Docker 主机完成首次安装、备份恢复和回滚演练；Standalone
   试点按 `docs/operations/standalone-pilot.md` 记录。
2. 在同一候选 Commit 上完成至少 72 小时公司真实试点，由业务负责人、运维和安全审批人共同签署；
   任何代码修复都生成新候选并重新开始观察。
3. 试点通过后完成 PR #38 Compact 与 PR #39 Standalone 最终评审和合并；未完成真实试点与人工签署前
   不创建 V4 正式标签。
4. 继续 S31 剩余页面产品化、容量、安全、备份恢复和 V3 试点；未完成这些门槛前不宣告 V3 GA。
5. 并行推进 `v2.0.0-rc.1` 的真实试点与连续 14 个自然日观察；只有签署、恢复演练、扫描和容量证据
   全部通过后创建 `v2.0.0` 正式标签。

## S47.2 V5 最终正确性与安全闭环（2026-08-23）

### 已完成实现

- Canonical Contract 采用统一 allowlist sanitizer，覆盖 OpenAPI/Swagger 导入、APIVersion 持久化、既有数据
  迁移、REST/MCP 读取、Test Engineering 和 fingerprint；危险示例和值级 Secret/PII 不再进入稳定契约。
- Project、Environment、ServiceEndpoint、API、Runtime 五层请求合并后执行 Header/Query/Cookie suppression；
  `auth_mode=disabled` 优先于旧 alias，并按 Bearer/Basic/OAuth/API Key carrier 删除认证值。
- Semantic Coverage 使用 Service/Operation/Location/Field/Value/Category 身份，区分 Project Known 与 Current
  TestPlan；pinned 版本缺失不回退 current，未发布 WorkflowVersion 不算覆盖。
- Change Regression 支持 Body、Path、Query、Header、Cookie 位置化变化并从当前 Canonical Contract 生成
  Oracle；Evidence 冲突对称、provenance 完整，观察统计不会冒充规范性约束。
- Swagger/OpenAPI 3.0 与 3.1 exclusive boundary 以及 Source AST 的 `<`、`<=`、`>`、`>=` 已保持精确语义。
- 迁移 head 升级为 `20260823_0043`，Standalone baseline/incremental schema 和 Transfer revision 同步。

### 能力与发布边界

V5 FlowSpec 正式基线仅为 fingerprint v3；开发期 v1/v2 不承担正式兼容承诺。Pairwise 仍是有界代表组合，
State Model 未实现并明确不可用，Knowledge Graph 只表达可追溯 Evidence 关系。真实 Key Rotation、Windows
实机、长时 Standalone/Compact、连续 RC 观察和人工安全审批仍未完成，所以 `GA_READY` 保持 `NO`。

本地与远程验证结果以
[S47.2 最终正确性与安全闭环](release/s47-2-final-correctness-security.md)为准；远程 GitHub Actions
未真实完成前不得用本地结果替代。

## S47.3 V5 最终语义完整性闭环（2026-08-23）

- Coverage Token 绑定 Oracle Set Fingerprint，Status/Response Schema 改变不再被值覆盖隐藏。
- Current Plan Gap 成为 Approve/Execute/Release 硬门禁；Add-to-Plan 和人工逐 Gap Waiver 重算 Coverage。
- Waiver 可过期、可审计、进入 Release Evidence，Service Token 无权创建。
- ChangeSet 冻结 Operation/API/Version/Service/Route/Fingerprint；多 Service 同路由不会选第一个。
- AST 区分规范控制流与普通分支，不可满足约束阻断生成/物化。
- Canonical Schema 增加严格 Keyword Value/Range/Budget 校验；敏感 Enum 只保留 Count。
- `20260823_0044` 使用冻结 Migration Support 清理历史数据并持久化 Waiver，Standalone/Transfer 同步。
- MultipleOf 相邻值使用 Decimal 精确对齐。

详细证据见 [S47.3 最终语义完整性闭环](release/s47-3-final-semantic-integrity.md)。真实 Key Rotation、
Windows 实机、长时运行、RC 观察和安全审批未完成，`GA_READY` 仍为 `NO`。

## S47.4 V5 最终评审修复（2026-08-25）

- Operation Coverage 统一比较 API Definition/Version/Fingerprint/Service/Route/Portable Ref，
  v1 不再覆盖 v2，Contract 指纹变化不再算已覆盖，跨实例 Portable 等价仍可匹配。
- Python AST 证据记录条件深度和分支上下文；If/Try/Loop/Match 中的局部约束仅作
  `supporting_condition`，不进入全局 Boundary/Oracle。
- 多 Service 歧义经人工选择后，使用所选 API 固定版本和 Canonical Contract 重新生成
  Proposal，显式绑定 Change Item，已审核/已物化项不允许静默改写。
- 过期 Waiver 可续签为新 Revision，保留历史和 Supersede 链；同一 Gap 仅最高有效
  Revision 进入 Release Evidence，Service Token 仍无权豁免。
- Published Workflow Assert 增加图可达性分析：线性和 post-join 必达可形成覆盖；条件分支仅
  Partial，断开节点不计覆盖，循环不确定时要求 Review。
- `20260823_0045` 增加 Waiver Revision/Supersede 持久化；真实 PostgreSQL 完成
  `0044→0045→0044→0045` 和 `alembic check`。
- 隔离 Compose 中三轮 `S14→S47→S14` 全部通过。根因是管理面板成功后全局 Query
  invalidation 使共享 loading 状态阻止后续 Secret 提交；已改为项目级定向失效并为 E2E
  创建独立项目。

详细证据见 [S47.4 最终评审修复](release/s47-4-final-review-fix.md)。本地门禁不替代最终
HEAD 的 GitHub Actions；PR 保持 Draft，真实 Key Rotation 和外部证据未完成，`GA_READY: NO`。

# S47.5 Release Evidence Integrity Closure（2026-08-26）

- Semantic Coverage 已与 Missing Draft 开关解耦；关闭草案生成仍计算并阻断 Plan Gap。
- Plan Gate 使用 TestPlanItem 固定资产/Workflow 版本，TestCase 使用已发布 Version Definition。
- Release Gate 使用本次 TestPlanRunItem 快照且只接受 Passed Item；Quarantined/Cancelled 不计覆盖。
- Current OpenAPI Fingerprint 为权威身份，精确失败不再回退旧 Route Contract。
- Generated Workflow/TestCase 经人工发布后可在同一 Run 显式加入计划并重新计算，不自动执行。
- Migration Head 保持 0045；完整证据见 `docs/release/s47-5-release-evidence-integrity.md`。
- 本地 Backend `571 passed / 3 skipped`、Frontend `215 passed`、隔离 PostgreSQL Migration
  往返和隔离 S47 Compose Smoke 均通过；最终状态仍以精确 HEAD 远程 CI 为准。

# S47.6 Runtime Release Evidence Closure（2026-08-27）

- Release Gate 先锁定并验证 TestPlanRun 终态；Queued/Running 返回 409，不修改 Change Regression
  状态、Evidence、Stage 或 Release Decision。
- Release Coverage 从 Passed RunItem 继续追踪 WorkflowExecution、实际 Passed API Node、最终 HTTP
  Request Observation 和实际 Passed Assert；Skipped/Cancelled/未进入分支、运行时值不匹配及未执行
  Dataset Row 不计覆盖。
- Failed/Cancelled TestPlanRun 成为不受宽松 Release Policy 绕过的明确硬阻断，并保存安全的执行结果
  代码；Failed Run 继续生成 Failure Triage。
- Current Plan Coverage 按固定 SuiteVersion 展开 TestCaseVersion；VERSION_MISMATCH 与
  CONTRACT_MISMATCH 支持人工 Replace Plan Item Version、审计和重新计算。
- 页面展示 Runtime Node Evidence 基础、实际匹配 Fact/API Node/Execution 数量和 Replace Version 动作。
- Migration Head 保持 `20260823_0045`；本地与远程完整门禁记录见
  [S47.6 Runtime Release Evidence Closure](release/s47-6-runtime-release-evidence.md)。

# S47.7 Autonomous Functional Acceptance & Merge（2026-08-27）

- 同步 `origin/main` 后完成 Requirement/Correctness/Security/User Flow 四轮独立自动审计。
- Runtime Coverage 对已分配 Service 改为与 Observation 精确匹配；legacy `unassigned`
  仍保留兼容语义。
- 已完成 Release Gate 的重复评估返回同一不可变 Decision/Evidence/Stage，不被后续
  Plan 修改或 Waiver 过期重新解释。
- Change Regression Missing Test 仍聚焦变更字段生成，但物化请求现在保留完整
  Current Contract 的其他必填字段；独立 Compose 中 5 个固定版本工作流实际通过。
- Credentialed CORS 拒绝通配符、非 HTTP(S)、UserInfo、Query、Fragment 和非根 Path。
- 独立 `S14→S47.7→S14` 通过，Release Evidence 基于 Runtime Node Observation 且无 Waiver。
- 开发代码合并不再等待人工 Reviewer；仍必须通过本地门禁、精确 HEAD Remote CI
  和分支保护。完整记录见
  [V5 自主功能验收](release/v5-autonomous-functional-acceptance.md)。
