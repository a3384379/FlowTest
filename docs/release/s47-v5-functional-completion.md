# FlowTest V5 S47 功能闭环记录

状态：本地功能闭环已验证，未达 GA（2026-08-23，Asia/Shanghai）

审计分支为 `codex/v5.0`，开始于 `1101e5aedac12a7f5c6cd4f76bea5b3cac8a2ddd`。
本文档区分“代码已实现”、“本地已验证”和“外部待验证”；任何未实际执行的门槛
都不记为通过。

## 1. Phase 0 事实审计

审计基线的 Alembic head 为 `20260823_0040`。针对 FlowSpec、Execution/Runner、
TestDesign/MCP、Change Regression/Triage、Organization Key Lifecycle 和对应 UI 完成路由、
Application Service、Domain、Repository、Migration 与测试的双向追踪。

确认的缺陷：

1. FlowSpec 导出/导入会丢失 Service、Operation、Endpoint Variant 和部分依赖/映射语义；
   指纹包含实例 UUID，不能证明跨实例语义等价。
2. 批次 Runner 以批次而不是子项写 Checkpoint；Resume 与 Retry 可走到相同路径；
   Dispatch 失败可留下不可观测的孤儿状态；部分 Checkpoint 上报缺少完整 Fence 校验。
3. TestDesign 主要是 DTO/存储结构，缺少 Evidence 驱动的确定性生成和到可执行
   Workflow/TestCase 的审核物化闭环。
4. MCP 缺少生成、Coverage、源码/DataProfile/Test Evidence、FlowSpec Diff 和 Change Impact
   等只读能力；受控写入没有完整的幂等/默认 dry-run 协议。
5. Change Regression 只能生成泛化场景，不保留边界语义；Failure Triage 缺少
   结构化证据、置信度、受影响 Service/Operation 和建议回归。
6. Key Rotation 仅改元数据却可标记为已迁移，没有数据重加密、分批进度、验证和回滚；
   这不是真实完成的 Key Rotation。
7. 前端缺少 Test Engineering、FlowSpec Mapping/Review 主路径，Service Target 与
   Failure Triage 页面也未暴露已存在的类型化业务信息。

## 2. 实际修复与主链路

```mermaid
flowchart LR
    E[Typed Evidence] --> G[Test Engineering]
    G --> D[ChangeSet Draft]
    D --> R[Human Review]
    R --> M[Workflow + TestCase]
    M --> X[Durable Execution]
    X --> V[Run Evidence]
    V --> I[Regression + Failure Triage]
```

- 新增 `flowtest-evidence-v1` typed contract，要求每条 Finding 包含来源类型、`source_ref`、
  revision、subject/path、confidence 和 deterministic；限制条数/字节数，拒绝敏感键值。
- 契约 Evidence Provider 从 typed Operation Contract 提取请求字段、required/nullable、边界、
  enum/pattern、auth 和 response contract。Python Source Provider 只处理 allowlist 中的有界
  `.py` 快照，使用 AST 分析，不执行代码。DataProfile 只接受结构元数据和已遮罩示例。
- 生成器输出稳定 Test Intent、Scenario、Oracle、Coverage/Gap、Evidence Ref、Confidence
  与 Review Requirement。字段和场景排序固定，同一证据/策略指纹一致。
- REST 主路径为 `generate → proposals → review → apply`。Apply 复用现有 Workflow 和
  TestCase Service，保存 approved TestDesign 和可执行资产引用。默认物化 Happy Path；
  审核人可显式选择其他可执行场景。
- 物化前会将 API 绑定的 Service 与目标环境的 Endpoint Variant 一起校验并固化到
  Proposal 快照。只有一个可用 Variant 时可自动选择；多个 Variant 时 API/UI 要求
  明确选择，避免生成“可物化但不可执行”的 Workflow。
- `auth_missing` 通过节点级 `auth_disabled` 安全物化；Runtime 会跳过定义级认证，Snapshot 只保存
  模式、不保存 Secret，并由真实 Mock Target 验证 Authorization/API Key/Cookie 未发送。

## 3. Scenario、Oracle 与 Coverage 语义

| 维度 | 已实现的确定性规则 |
|---|---|
| required/nullable | 必填缺失、必填 null、可选缺失；nullable 决定 null 的正/负类别 |
| numeric | `minimum-1`、`minimum`、`maximum`、`maximum+1` |
| string | `minLength-1`、`minLength`、`maxLength`、`maxLength+1`、每个 enum 值、pattern |
| array/type | min/maxItems 两侧边界与类型错误 |
| auth | required auth 生成 missing-auth 负场景，物化限制如实报错 |
| pairwise | 策略显式启用时，对有证据的字段值做稳定成对组合 |

Oracle 优先使用契约中明确的 response status/schema，并指向对应 Evidence Ref。无法从
确定性证据得出的预期不伪造为高置信断言，而是降低置信度并加入人工复核。
Coverage 同时记录各维度目标、已覆盖 Evidence/Scenario 和未覆盖 Gap，而不是仅输出一个百分比。

## 4. FlowSpec 兼容与可移植性

- Schema 版本继续为 `flowtest-flow-spec-v1`。S47.1 新导出使用
  `flowtest-flow-spec-fingerprint-v3`，指纹的语义投影排除 project/workflow/asset UUID，
  并加入 pinned/current、source version 与 contract fingerprint。
- 不带 `fingerprint_version` 的旧 FlowSpec 按 `flowtest-flow-spec-fingerprint-v1` 解析和验证，
  不会因新指纹算法被误判为篡改。
- v3 显式保存 portable Service、Operation、Target/Variant、Dependency、Binding 和 API Version
  Strategy。导入者
  必须将 Service/Operation 逻辑键映射到目标项目资产；缺失、歧义或跨项目映射会
  成为 compatibility blocker，不会在 Apply 时静默丢弃。
- UI 支持粘贴/导出 JSON、Validate/Compatibility、Service/Operation Mapping、Diff、
  ChangeSet Draft、Review 和 Apply。

## 5. Durable Execution 正确性

| 命令/阶段 | 语义 |
|---|---|
| Start | 幂等键对应一个 Execution，计划成功后才进入可调度状态 |
| Resume | 使用原 Execution，按子项 Checkpoint 跳过已完成工作，失败子项从后续 Attempt 继续 |
| Retry | 新建 Execution 和新命令，不将旧 Execution 的完成 Checkpoint 当作新运行的跳过事实 |
| Batch | 每个子项拥有独立 Checkpoint 键、Attempt、输入哈希和输出 Digest |
| Dispatch/Fence | Dispatch 失败写可观测失败终态；过期 Lease/Fence 不得写 Checkpoint 或覆盖新状态 |

## 6. MCP 工具与 Scope

`mcp:read` 工具稳定排序为：

`analyze_test_coverage`、`diff_flowspec`、`discover_services`、`export_flowspec`、
`generate_test_design`、`inspect_change_impact`、`inspect_contract`、`inspect_data_profile`、
`inspect_flow`、`inspect_project`、`inspect_run_evidence`、`inspect_source_evidence`、
`inspect_test_evidence`、`list_projects`、`validate_flowspec`。

`propose_test_design` 是 `mcp:write` 受控工具：必须提供幂等键，默认 `dry_run=true`，
真写也只能创建 Draft。相同组织/项目/操作者/幂等键/请求返回同一结果，载荷冲突
显式拒绝。本阶段没有自动发布、执行、删除、权限变更或 Credential 工具。

## 7. Change Regression 与 Failure Triage

- Contract Diff 保留字段路径、变更类型和 before/after 边界。例如 `maximum: 100 → 999`
  精确生成 `999/1000` 新边界与 `100/101` 旧边界回归，不降级为“增加一个边界测试”。
- `s47-failure-triage-v2` 从 typed Failure Signal 确定性分类 Product/Bad Test/Bad Data/
  Environment/Endpoint/Contract/Auth/Network/Timeout/Flaky/Cancelled/Unknown，输出 Primary、
  Secondary、Confidence、Reason Code、Affected Service/Operation、Evidence Ref、Retry Signal 和
  Recommended Regression。旧记录显式标为 legacy，不伪造 v2 证据。

## 8. 迁移与运行档位

S47 的 Alembic head 从 `20260823_0040` 升级为 `20260823_0041`；S47.1 再升级为
`20260823_0042`。0041 为 `test_designs`
增加 `scenarios`、`evidence_refs`、`warnings`、`confidence`、`review_requirements`，
提供完整 downgrade；0042 为 `api_versions` 增加 canonical contract、fingerprint 和 completeness，
并安全 backfill 旧版本。Standalone SQLite 增量 Schema 和 Transfer 明确表/列处理同步到新 head。

迁移同时将无真实重加密证据却标记为 `migrated` 的 Organization Key Version 恢复为
`planned`。当前 Key Rotation 仅可创建计划，Apply/Rollback 明确返回 409；它在真实
数据重加密、分批进度、验证和回滚完成前仍是 GA blocker。

## 9. 验证记录

| 证据 | 环境 | 结果 |
|---|---|---|
| S47 定向功能/Golden/Standalone/Transfer | 本地 macOS/ARM，`--no-cov` | `27 passed` |
| Backend 全量 Ruff/mypy/pytest | 本地 macOS/ARM，Python 3.13 | 通过；`440 passed, 3 skipped`，Coverage `90.06%` |
| Backend 架构/依赖审计 | 本地 macOS/ARM | Import Linter 1 份契约通过；`pip-audit` 无已知漏洞 |
| Frontend 全量 format/lint/coverage/build | 本地 macOS/ARM，Node 22 | `56 files / 211 tests` 通过；S/B/F/L `86.11/80.10/85.28/88.28%`；Build 通过 |
| PostgreSQL upgrade/check/downgrade/upgrade/check | 隔离 Compose PostgreSQL 17 | `0041 → 0040 → 0041` 通过；每次 `alembic current/check` 无 drift；5 列降级删除/再升级恢复 |
| Compose S47 API + MCP + 物化 + 执行 Smoke | `flowtest-s47-gate` 隔离项目 | 通过；源工作流、跨项目多 Service 导入和生成工作流共 3 次真实执行成功；MCP dry-run/幂等通过 |
| Playwright Test Engineering UI E2E | 隔离 Compose Frontend/Backend | 通过；登录→选 API/环境/Variant→Generate→Draft→Review→Apply，物化 1 Workflow + 1 TestCase |
| 远程 GitHub CI | 远程 | 未执行 |
| Windows x64 公司云桌面 72 小时试点 | 外部实机 | 未执行 |
| 连续 14 日 RC、安全审批、人工签署 | 外部/人工 | 未执行 |

## 10. 现存限制与发布判定

已知未完成项：

1. Key Rotation 真实重加密/校验/回滚未实现，是明确 GA blocker。
2. 完整 value-partition pairwise covering array 与显式 State Model 尚未实现；State 开关会返回
   unavailable，不会静默声称支持。
3. Source Evidence 当前仅支持有界 Python AST 快照；DataProfile 是 typed 脱敏适配入口，
   不代表已经对任意外部数据库建立生产连接。
4. 远程 CI、Windows 72 小时试点、14 日 RC 和人工签署尚无 S47 证据。

当前发布判定为 **LOCAL FUNCTIONAL COMPLETION VERIFIED / NOT GA READY**。本地全量
门槛、真实迁移往返、Compose 主链路与 Playwright UI 主路径已通过，可进入 V5
功能完成审核。Key Rotation 和上述外部/时间型门槛未完成，因此不等于 GA Ready。

## 11. S47.1 语义正确性补充

S47.1 在上述 S47 主链路上补齐 OpenAPI/Swagger Canonical Contract 持久化、参数位置、Evidence
Projection/Conflict、Path/Query/Header/Body/Auth 真实物化、Response Schema Assert、FlowSpec
pinned/current v3 指纹、独立 Test Semantic Coverage、value-level Evidence Redaction、HTTP 5xx
upstream 分类和 0041 downgrade truth fix。详细审计矩阵、Schema、迁移和剩余风险见
[S47.1 语义正确性与证据闭环](s47-1-semantic-correctness.md)。

## 12. S47.2 最终正确性与安全补充

S47.2 在 S47.1 语义链路上增加统一 Canonical Contract allowlist sanitizer、0043 既有数据净化与
fingerprint 重算、五层请求 suppression、Operation/location scoped coverage、位置化 Change Regression、
规范性/观察性 Evidence 分离、对称冲突和 exclusive boundary 精确生成。REST、MCP、Test Engineering、
Execution Snapshot 与 Audit 都不得暴露被移除的敏感值。

V5 FlowSpec 的唯一正式基线是 `flowtest-flow-spec-fingerprint-v3`；开发期 v1/v2 不属于正式兼容范围，
也不是 V5 合并阻断项。Pairwise 仍是有界代表组合，State Model 未实现，Knowledge Graph 仅表达已有
Evidence 的确定性关系；这些能力不得写成完整实现。

最终实现、迁移往返、本地门禁、Draft PR 和远程 CI 证据见
[S47.2 最终正确性与安全闭环](s47-2-final-correctness-security.md)。无论本地功能闭环结果如何，真实
Key Rotation、Windows 实机、长时 Standalone/Compact、连续 RC、安全审批和人工签署未完成前，
`GA_READY` 必须为 `NO`。

## S47.3 补充校正

S47.3 将覆盖语义扩展为 Oracle-aware Token，将 Current TestPlan Gap 升级为审批、执行和发布硬门禁，
并关闭多 Service Operation、物化绑定、AST 控制流、约束可满足性、Canonical Keyword、
敏感 Enum Hash、Decimal MultipleOf 和 0044 迁移确定性问题。S47.2 的旧结论以
[S47.3 最终语义完整性闭环](s47-3-final-semantic-integrity.md)和其最终 HEAD Remote CI 为准。

## S47.4 最终评审补充

S47.4 进一步收紧 Operation Coverage 的 API Version/Contract Fingerprint 身份，阻止嵌套条件
AST 证据成为全局约束，并闭环 Operation Selection 后 Proposal 重生成、Waiver
Revision/Supersede、Published Workflow Assert 必达分析与 E2E 顺序隔离。S47.3 及更早文档
中的合并判定不再单独作为当前证据；以
[S47.4 最终评审修复](s47-4-final-review-fix.md)和精确 HEAD 的 PR CI 证据评论为准。

PR 仍为 Draft，仍需人工 Review；Pairwise/State Model/Knowledge Graph/Key Rotation 能力边界
不变，`RC_READY: NO`，`GA_READY: NO`。
# S47.5 补充门禁

V5 Functional Completion Review 还要求 Missing Draft 开关不能关闭 Semantic Gate、Plan
Coverage 使用固定版本、Release Coverage 使用 Passed RunItem Snapshot、Current OpenAPI
Fingerprint 精确绑定，以及 Generated Asset 可在人工发布后同 Run 显式加入计划。实现和验证
记录见 `s47-5-release-evidence-integrity.md`。

# S47.6 运行时发布证据补充

Release Gate 必须在 TestPlanRun 终止后评估，并且只能由本次实际执行的 Passed
API Node、最终 Request Observation 与实际 Passed Assert 形成语义覆盖。整个 RunItem
Passed 不足以证明分支内节点已执行。Failed/Cancelled 执行固定阻断，Suite 预执行覆盖按
固定版本展开，旧版计划项需人工 Replace Version。实现与验证记录见
`s47-6-runtime-release-evidence.md`。
