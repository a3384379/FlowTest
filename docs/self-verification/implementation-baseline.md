# MCP 原生自测体系：S0 实施基线

记录日期：2026-10-23。固定源码基线：`70e4b513e734c2c47053ecc314db0bbd092f16db`。
方案来源：[自测体系建议共享对话](https://chatgpt.com/share/6ada32ad-a520-83ea-85f4-205d681992f6)及用户提供的完整 v2 附件。

本文保留实施前 S0 的事实和待验证项。后续实现、实际协议发现、运行和检查结果统一记录在[开发验证记录](validation.md)，下文的“尚未运行”仅描述 S0 当时状态。

## 证据与完成边界

已完整阅读主方案、源码证据矩阵、Codex 分阶段提示词和 MCP 专篇；本文冻结最小实施契约与各阶段验收集合。
完整矩阵的 94 项是整体验收目录；本文不把静态核对、源代码中的测试定义或效果图记成运行通过。
受控工作区初始 HEAD 与方案基线一致；原工作区 AGENTS/README/Playwright 本地修改保留。
锁定 MCP SDK 为 2.2.0；源码声明 54 个工具。实际协议版本与 tools/list schema digest 待 S1 真实连接取证，静态声明不能替代。
附件是需求资料，不授予推送、部署、生产访问或外部模型费用权限。

| 已读附件                              | SHA-256                                                            |
| ------------------------------------- | ------------------------------------------------------------------ |
| FlowTest_自我验证体系_完整开发方案.md | `048db9d998d04df4494da430624ac29be8756634dfbaf551e3e13fd8c1a70882` |
| FlowTest_源码证据与验收矩阵.md        | `6bec22c6df268b1e24eecef22db8e8c8779a6b2b9eb0a699c4db59db76e0c144` |
| FlowTest_自测Codex分阶段实施提示词.md | `99ee1d0b82045424736383c7bd592e3b8e1f3e731ba6f14cfb66507f9a4fa1d6` |
| FlowTest_MCP生成用例与自测闭环设计.md | `5aea7d749e471467a2678b77d26ecee65596f145779eb188c16fc0f89a72aa8a` |
| FlowTest_自测界面设计规格.md          | `098dc2273784fb3e1434b313e9621b3c992a75846c9d74e48c112386a758ee32` |
| FlowTest_自测界面生成提示词.md        | `ee52297a26e9ccc475b492f90abc12dc323c5f0d6d99fd7015f121e253e2e834` |

## 已核对的复用入口

| 能力            | 源码入口                                                                                                                                          | 已有行为                                                                                              |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| 生成服务        | [test_engineering.py](../../backend/app/services/test_engineering.py)                                                                             | `TestEngineeringService.generate()` 校验项目只读权限，调用现有生成器，返回 Design 与指纹              |
| 精确版本读取    | [test_engineering.py](../../backend/app/services/test_engineering.py)                                                                             | `contract_for_api(version_number=...)` 支持历史版本，校验项目归属，使用该版本的 Service 身份          |
| 确定性生成      | [test_engineering.py](../../backend/app/domain/test_engineering.py)                                                                               | `TestEngineeringEngine.generate()` 根据 Contract、策略和证据生成场景、Oracle、覆盖与审核要求          |
| 设计模型与指纹  | [test_design.py](../../backend/app/domain/test_design.py)                                                                                         | `TestDesignDocument`、`ScenarioCandidate`、`OracleSpec` 及 `fingerprint_design()` 已存在              |
| 原生场景编译    | [test_engineering_proposals.py](../../backend/app/services/test_engineering_proposals.py)                                                         | `_scenario_workflow()` 接收固定 API 版本，将场景编译为原生 `WorkflowDefinition`，无需经 FlowSpec 转换 |
| Oracle 可执行性 | [test_engineering_proposals.py](../../backend/app/services/test_engineering_proposals.py)                                                         | `_expected_status()` 与 `_scenario_oracles()` 校验确定性状态码及支持的断言，拒绝未解决审核项          |
| 请求覆盖        | [contracts.py](../../backend/app/engine/contracts.py)、[workflow_snapshots.py](../../backend/app/services/workflow_snapshots.py)                  | `ApiNodeRequestOverrides` 定义参数、Body、认证与抑制字段；快照构建消费这些配置                        |
| MCP 读取链      | [server.py](../../backend/app/mcp/server.py)、[client.py](../../backend/app/mcp/client.py)、[mcp_read.py](../../backend/app/services/mcp_read.py) | `flowtest.generate_test_design` 经网关调用现有生成服务，返回 `persisted: false`                       |
| 审核与物化      | [test_engineering_proposals.py](../../backend/app/services/test_engineering_proposals.py)                                                         | `propose()`、`review()`、`apply()` 及 `materialize_reviewed_design()` 已提供受控持久化路径            |

原生编译器生成 schema `1.0` 的 Start、API、Status Assert、可选 Schema/Expression Assert 与 End。
请求节点包含 API ID、固定版本及可选 Endpoint Variant；路径变量、Query、Header、Cookie、JSON Body
和认证禁用通过已有覆盖模型表达。非确定性场景、待审核场景与无法表达的 path omission 会被拒绝。

## 真实缺口与实施约束

本节为固定基线 `70e4b51` 的 S0 历史发现。当前已实现的版本冻结、编译入口、只读证据、journal 和调度修复见[编译说明](design-compilation.md)与[开发验证记录](validation.md)。

1. [生成请求模型](../../backend/app/schemas/test_engineering.py)与 MCP 工具签名没有 API 版本入参，
   `generate()` 目前按最新版读取；内部精确版本能力尚未贯穿该接口。
2. MCP 生成结果包含 Design 指纹，但缺少明确的 resolved API version 与 Contract fingerprint。
3. [REST 生成路由](../../backend/app/api/v1/endpoints/test_engineering.py)先调用 `generate()`，再读取
   Contract 组装响应；两次读取之间存在 API 版本变化的风险，尚未通过并发测试验证。
4. `propose()` 会生成 Design；`apply()` 为核对冻结输入会再次生成，并拒绝已变化的目标版本或 Contract。
   `materialize_reviewed_design()` 接受已有 Design，但仍读取最新版并写入 Workflow、TestCase、TestDesign。
5. 因而现有物化服务不能直接充当只读固定设计适配器；后续应复用原生编译逻辑，保持固定 Design、
   API 版本、Contract 指纹、场景选择与 Oracle 的关联，避免通过重新生成掩盖来源变化。
6. 生成读取需保留项目只读权限；审核、应用与资产创建需保留现有编辑及审核约束。
   MCP 的 `propose_test_design` 与测试工程 Proposal 服务是不同入口，后续须核对实际调用及审核路径。
7. S2 只读适配同时要求 `mcp:read` 与 `mcp:flow:propose`；按冻结 Contract/policy/evidence 重生仅用于来源指纹校验，
   不能改用 latest 生成物再编译。输出不创建提案、不落库、不审核/发布/执行、不调用目标。
8. 当前 Quick 未将状态断言同步到 API `expected_statuses`，401/404 负向必须走保真完整路线；body=null/未提供 body、
   重复参数等须 characterization。现有 `_request_overrides` 在 body=None 时不输出覆盖，不能预先声称全保真。
9. Mock `last_*` 单槽需批次 journal；CI 已有启动、quality-gate、JUnit，但没有 `read:execution`。
   JUnit 未强制终态、普通质量零分母可为100%，均不能独自证明自测通过。
10. Plan claim 并发、late-ack 重投、父 passed 子非终态及取消竞态是待复现关注点，先测试再最小修复。
11. 项目路由没有 DELETE project；首条可完整回收的 CRUD 使用 B 环境资源（MCP 专篇§7.1），项目仅作 disposable scope 由启动器收尾。
    项目创建/查询/修改仍在 S1 整体范围，不虚构删除接口或用环境任务代替全部项目验收。

## 冻结的最小数据契约

以下属于新增 Harness/Observer 契约；严格模型拒绝未知字段，引用已有 typed Design/Workflow，列表有界，UUID/版本/摘要受校验。

| 契约         | 字段与约束                                                                                                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| PackManifest | format=flowtest-selftest、format_version=1、pack_id/version/digest、minimum_workflow_schema、profiles、scenario_ids、scenarios、limits、default_plan_retries=0；原生资产包仍为 flowtest-test-assets v1 |
| 批次         | batch_id、binding_id、profile、batch_kind=fixed_baseline或mcp_generated；固定pack/policy/runner/target/fixture/verifier摘要；MCP批次另有任务/来源摘要                                                  |
| 场景身份     | `(scenario_id, variant_key)` 唯一；ID沿用完整ST-*；generation_attempt与execution_attempt分开，不能旧Run抵新批次                                                                                        |
| 集合         | expected_scenario_set非空；required_scenario_set非空且为其子集；actual与expected精确一致、无重复；verification_scope=full_pack/selected_suites/diagnostic_subset                                       |
| 预期/观测    | expected_outcome固定原始终态、error_code、node_id、phase、次数与required_evidence；observed_outcome记录白名单事实及全部attempt，不执行后改预期                                                         |
| 映射         | mapping保存服务端真实ID、发布版本、指纹、归属及步骤receipt；每文件SHA-256，manifest去自身digest后规范化摘要；不含Token/Cookie/秘密                                                                     |
| 预算         | 默认maximum_batch_seconds=600、maximum_requests=500、maximum_fixture_run_depth=1；普通场景60秒、控制120秒、初始化180–300秒；既有更严上限优先                                                           |
| 生成任务     | task_id/version/digest、业务目标、允许API/fixture引用、独立业务期望、required_oracle_ids、冻结缺陷变体、工具/时限/attempt预算；不预置最终Workflow/Case                                                 |
| 来源         | 实际catalog/schema/protocol/SDK与工具摘要→API版本/Contract→Design→编译/Oracle映射→proposal/item/review→物化/发布Workflow与Case→Suite/Plan展开→RunItem/Execution/snapshot→O                             |
| 报告         | execution.junit.xml保留原始失败；verification.junit.xml独立生成；不通配混合，不用零failures判断终态                                                                                                    |

所有选入 expected 的可选场景也必须完整 matched。0条、缺项、quarantine、截断/过期证据、清理失败与错构建均不能passed。
固定回归与本轮MCP生成分别统计；recorded_replay仅辅助，正式generation_mode只有deterministic_mcp/host_llm_mcp。

| 状态字段                       | 固定枚举                                                                                                         |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| execution_status               | queued/running/passed/failed/cancelled；Plan item另有quarantined；不写timed_out/verified_pass                    |
| verification_status            | pending/matched/mismatched/incomplete/error/unsupported                                                          |
| batch_verdict                  | pending/passed/failed/blocked                                                                                    |
| evidence_integrity、provenance | complete/missing/expired；local_untrusted/trusted_ci，彼此与核验结论正交                                         |
| phase                          | preflight/installing/executing/verifying/cleaning/completed/cancelled                                            |
| generation_stage               | discovering/reading_contract/designing/compiling/proposing/awaiting_review/publishing/ready/blocked/cancelled    |
| generation_readiness           | ready/needs_input/needs_review/unsupported/blocked；聚合优先级blocked→unsupported→needs_review→needs_input→ready |

S2输入固定Design+fingerprint、origin API/version/Contract/policy/evidence、非空唯一scenario_ids（最多50）、授权环境/context/auth/fixture引用与预算。
输出persisted=false、execution_status=not_run、proposal_route、typed payload、workflow_slot Case模板、逐Oracle→Assert映射及诊断；
总节点建议上限500且服从更严现有限制。缺Oracle、来源/输入错误、不支持项均不静默丢弃。slot仅逻辑槽，真实Workflow发布后H回填UUID/版本；
原REST apply的stale拒绝不放宽。独立黄金规范决定分母与预期，编译说明不自证正确。

## A/B/M/H/O 与授权边界

| 角色       | 隔离与权限                                                                                                                                         |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| A 执行器   | 候选控制/执行实例，仅自测资产域；同实例只读/live smoke。MCP ftsa只持任务所需scope，无审核/Observer凭据                                             |
| B 被测实例 | 独立进程、数据、队列、存储、签名/加密密钥与Cookie；破坏性任务只指本批disposable scope；只执行allowlist fixture                                     |
| M 目标     | 业务监听与Observer管理监听分开；batch/scenario journal、epoch/TTL/容量有界；引擎不能重置receipt或修改响应序列                                      |
| H Harness  | 只安装/真实协议驱动/触发/观察/清理，不代跑业务HTTP；初始化、MCP、执行、审核身份分离；review_mode=ci_fixture、actor_kind=fixture_actor，不冒充human |
| O Observer | 独立进程和黄金规则，不导入候选比较器/成功汇总器；S1受控JWT读证据，S2拟增read:execution；可信上传来自部署/CI管理域，owner自签不得升级trusted_ci     |

绑定核对实例/构建/网络allowlist/数据域，不以test勾选或不同域名证明隔离；保留出站保护，不全局关闭SSRF访问loopback。
stdio环境显式允许列表，HTTP每次Bearer；秘密不进包/runtime变量/日志。Full/Compact/Standalone分别留证，必需能力不支持则blocked。
本地结果默认local_untrusted；网页/owner/MCP不得写Required Gate。历史真实宿主[ R06账本](../release/mcp-closed-loop-acceptance.md)仍未执行。

## 首条 S1 真实协议链与黄金任务

首个纵向任务为B环境资源创建→列表核对→修改→删除，字段与状态取冻结B OpenAPI/typed schema；第二任务为前序ID/随机marker传递及假值类型保留。
第三组为对称正向、HTTP200业务失败与故意错误断言canary：固定actual=1，断言1应passed、断言2应failed+WORKFLOW_ASSERTION_FAILED。
O在运行前核对生成图并冻结具体断言node_id及phase=main；不得报错后反推或接受任意failed。

1. 启动器建立A/B/M/O隔离域与合成账号，记录构建与ownership，检查健康/readiness后读取OpenAPI。
2. 真实stdio子进程或HTTP监听启动MCP，锁SDK兼容客户端发现、tools/list，保存实际schema/protocol；两种传输分别验收。
3. inspect_connection→ensure_*按需dry-run/提交→preview_contract_import→固定preview后commit→inspect_contract，取得真实ID/版本。
4. generate_test_design/analyze_test_coverage现场生成，串行核对前后版本/指纹；从本次Design派生有限typed Quick steps，或版本一致的IntegrationPlan→validate→compile；不预写最终图/断言。
5. propose_simple_flow/propose_flow_draft先dry-run、独立结构核对再持久化；H准确review/apply，读回草稿并显式发布Workflow。
6. MCP propose_test_design引用刚发布Workflow真实ID/版本和固定环境；H按实际风险审批、逐item accept，读回Case并显式发布。
7. 现有REST创建并发布非空Suite，创建至少一成员、无schedule、max_retries=0的Plan；禁用计划正式运行前启用，不虚构Plan发布接口。
8. 原生执行Plan，O读取全部RunItem/Execution/attempt、B后置状态/M journal，核对来源、业务断言和完整集合，分别写两份JUnit。
9. 先采集证据/处理在途任务，再按本批真实ID逆序清理；全新栈重复初始化、连续两轮重新生成/运行，再做坏目标与删receipt/改状态canary，缺证据必须非零退出。

S1文件范围为selftest/packs/core-v1、mcp-core-v1、严格schemas、scripts/selftest的bootstrap/run/verify/evidence/cleanup/protocol/generation/review/provenance及定向测试，按职责拆分；不先增页面或业务表。
运行前需锁依赖、可用隔离启动器/端口/临时目录或Compose资源、A/B独立密钥、合成账号、网络allowlist及H/O权限。
真实Host另需已授权Host/Skill/model/外发范围/预算；缺失保留NOT_RUN，确定性链不可抵扣。

## 已定位的回归文件

以下仅列出源码中已有测试及其用途，不表示本次已运行或通过。

- [test_test_engineering.py](../../backend/tests/test_test_engineering.py)：生成预算、证据冲突、认证禁用、真实 JSONPath Assert 和不可物化场景。
- [test_mcp_read.py](../../backend/tests/test_mcp_read.py)：生成与覆盖读取不写入 Design/ChangeSet、MCP Scope、跨租户隔离和工具注册。
- [test_s50_integration_plans.py](../../backend/tests/test_s50_integration_plans.py)：固定历史 API 版本与原始 Service 身份，以及现有集成编译行为。
- [test_flow_spec.py](../../backend/tests/test_flow_spec.py)：测试工程 Generate、Proposal、Review 与 Apply 现有链路。
- [test_test_engineering_assets.py](../../backend/tests/test_test_engineering_assets.py)：物化资产回执、刷新恢复、Viewer 权限和外项目引用。
- [test_mcp_materialized_design.py](../../backend/tests/test_mcp_materialized_design.py)：精确物化 Design 只读查询及审核/资源关联校验。
- [test_s47_2_correctness_security.py](../../backend/tests/test_s47_2_correctness_security.py)：认证载体、请求抑制与场景请求语义。

后续开发按 [AGENTS.md](../../AGENTS.md) 和 [参与开发说明](../../CONTRIBUTING.md)运行命名定向测试、
相关 Ruff 与类型检查；核心及跨模块变化再扩大集成范围。定向结果、当前提交远程门禁和发布验收分别留证。

## 完整矩阵中的精确阶段验收集合

| 阶段 | 验收集合与边界                                                                                                                                                                                                                                             |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S0   | 固定SHA、SDK/实际协议能力、工具schema、OpenAPI/Contract、manifest/rubric、任务/缺陷变体与权限预算；静态记录不抵真实发现证据                                                                                                                                |
| S1   | ST-INIT-001/002/004；ST-API-001登录基础、003–007、009基础发布、010–012；ST-ENG-001基础、002、003 if、004 Repeat/ForEach、007、009、012；ST-CAN-001/002/005；ST-CI-001本地双JUnit；ST-MCP-001–006、009、011、014/015、017–020、023–026最小变体；必要cleanup |
| S2   | 扩充核心P0变体；ST-SEC-001/003/004、ST-CAN-003/004协议、ST-RUN-002/003/005/006；ST-MCP-007/008/010/012/013/016/021/022/027/037–040；journal、只读证据及固定Design薄适配                                                                                    |
| S3   | ST-CI-001远端、002/003；ST-MCP-028风险路由、029–036真实Host/Skill/LLM；缺配置/授权/预算为NOT_RUN，不能用确定性抵扣                                                                                                                                         |
| S4   | ST-GUI-001–003；ST-INIT-003恢复；ST-SEC-002上传；ST-CAN-004封存重放API；ST-RET-001外键/保留期；复用现有审核、资产和报告                                                                                                                                    |
| S5   | ST-API-008；ST-ENG-005/013/015/016完整变体；ST-RUN-004全故障矩阵及额外feature/profile；不能把核心MCP延后                                                                                                                                                   |

以上沿用矩阵§4.6；范围只省重复ST-前缀。阶段表未逐列的ST-API-002、ST-ENG-006/008/010/011/014、ST-RUN-001保持目录P0，
按S2“扩充核心P0变体”收口；这是阶段归属澄清，不删任何ID/变体。MCP专篇54个子点仅映射正式ST-MCP-001–040，不额外计入94项。
阶段完成须列profile/variant/命令/退出码/证据，局部覆盖不能宣称整个ID或整包通过。当前尚无本轮协议/Run/Host执行证据。
原始执行失败与独立核验是否匹配应分别记录；选中场景子集不能代表完整模板通过。
确定性协议回归不能代替真实 LLM 生成，真实 Skill/宿主/模型未运行时不得补写成功结果。
本文不声明当前提交 CI 门禁通过或达到发布条件。

## 本文检查记录

- 文档格式与本地相对链接检查：以本次实际检查命令及结果记录在交付说明中。
- 业务单元测试、集成测试、Compose、浏览器、真实 MCP/宿主/模型链路和远程门禁：本次均未运行。
