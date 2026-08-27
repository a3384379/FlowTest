# FlowTest V6.0 S48 契约基线

## 1. 基线身份

| 项目 | 冻结值 |
| --- | --- |
| V6 起点 Main SHA | `6370c6c8b44db51ce7717bc73eaf41f259c9df1b` |
| Alembic 单 Head | `20260823_0045` |
| Standalone Schema Revision | `20260823_0045` |
| 产品列车 | V6.0 Core，S48～S56 |
| Release 状态 | 未发布；不是 Alpha、Beta、RC 或 GA |

该 SHA 是 H0 合并、主线 Required Gate 全绿后的正式 V6 开发起点，不是 S48 合并提交。后续每个阶段仍需
独立 PR、Required Gate、合并后 Main Green 和 Review Thread 闭环。

## 2. 版本关系

| 表面 | 版本 | 说明 |
| --- | --- | --- |
| Backend Python package | `6.0.0.dev0` | PEP 440 开发版本 |
| Backend application/API | `6.0.0-dev.0` | 健康检查展示版本 |
| Frontend package | `6.0.0-dev.0` | 与 API 同一开发序号 |
| Product | `V6.0 Core development` | 只表示开发列车 |
| GitHub Release / Tag | 无 | S48 不创建 Tag 或 Release |

版本号不代表 V6 运行时能力已实现。S48 只冻结契约、Golden Set、评测口径和治理基线。

## 3. FlowSpec 兼容矩阵

| 能力 | v1 | v2 |
| --- | --- | --- |
| Schema | `flowtest-flow-spec-v1` | `flowtest-flow-spec-v2` |
| Fingerprint | v1/v2/v3 继续验证 | `flowtest-flow-spec-v2-fingerprint-v1` |
| Import | 保持支持 | 契约已冻结，运行接入由后续关闭态 Feature Flag 控制 |
| Export | 保持支持 | 后续迭代接入，不改变历史导出 |
| v1→v2 | 确定性、保留全部 v1 语义 | N/A |
| v2→v1 | N/A | 仅无 v2-only 语义时允许，否则阻断 |
| Unknown fields | 拒绝 | 拒绝 |
| Historical Execution Snapshot | 不迁移 | 不改写现有 `1.0` Snapshot |

详细决策见 [ADR 0038](../adr/0038-flowspec-v2.md)。S48 没有数据库变更，Rollback 只需回退代码；v1
资产始终可读。未来已包含 v2-only 语义的资产不能自动有损降级。

## 4. Golden Contract 与 Fixture

`backend/tests/fixtures/v6_golden/` 冻结以下资产：

- FlowSpec v1、Fingerprint v1/v2/v3、FlowSpec v2 与 v2 Fingerprint；
- WorkflowDefinition、AIChangeSet、TestDesign、OperationIdentity、Execution Snapshot；
- MCP Server Identity、Read Schema 与现有 16 个 Tool；
- Standalone Transfer Schema/Revision；
- 小型 HTTP Contract、Login→Create→Query、DB Profile；
- 不执行被分析代码的小型 Java/Spring Fixture；
- RuoYi Full Target Manifest（单元测试不构建完整 RuoYi）。

`backend/tests/test_v6_golden_contracts.py` 以真实领域模型解析样本，固定语义哈希、v1/v2 转换、v1
Workflow Roundtrip、Snapshot Shape、MCP Tool Set、静态源码 SHA-256 与评测统计。

## 5. Evaluation 标注与统计

标注版本为 `flowtest-v6-evaluation-v1`。每条记录固定 Case/Fixture、Metric、Label、Expected/Observed Ref、
Evidence Ref、Source Revision、Annotator Ref 与 Note；未知字段拒绝。

| Metric | 分子 | 分母 | 空分母 |
| --- | --- | --- | --- |
| Operation/Binding Candidate Precision | true positive | true positive + false positive | `null` |
| Compiler Success / Preview First Pass | pass | pass + fail | `null` |
| Manual Edit / Evidence Conflict Rate | yes | yes + no | `null` |

`not_applicable` 不进入分子或分母。统计按 Metric 枚举顺序输出，值保留六位小数；Golden 中 Preview 为
`not_applicable`，不虚报 S55 能力。

## 6. Feature Flag

S48 只新增 `FLOWTEST_FEATURE_INTEGRATION_FLOW_ENABLED`，默认 `false`，API 字段为
`integration_flow=false`。它服务于紧接的 S49～S51 接入，在明确阶段验收前不得默认开启。没有为 Preview、
Cleanup、Repair、Skills 或 V6.1/V6.2 预建空 Flag。

## 7. Repository Governance

- GitHub Ruleset ID：`21653796`，名称 `main-required-gate`，状态 Active。
- Default Branch 生效，无 Bypass Actor；当前操作者 `current_user_can_bypass=never`。
- Pull Request、Conversation Resolution、Up-to-date、Deletion/Non-fast-forward 保护启用。
- 唯一 Required Context：`Required Gate`，GitHub Actions App Integration ID `15368`。
- H0 Closure PR #44 已普通 Squash Merge；Main Push 的 Required Gate 与适用 Workflow 均为 Success。

S48 的仓库内 PR 模板进一步固定 Scope/Non-goals、兼容迁移、数据安全、四维 Review、验证和回滚证据。

## 8. Non-goals 与风险

- 不实现 Context 持久化、Evidence Intake、Compiler、Proposal UI、Cleanup Runtime 或 Preview Runtime。
- 不新建未来迭代暂时不用的表、Scope 或 Feature Flag。
- 不创建 Tag、Release，不宣称 Alpha/Beta/RC/GA，也不声称真实公司试点已完成。
- Key Rotation 本阶段只冻结数据分类和轮换元数据边界；没有真实密钥轮换授权或证据。S55 开始前必须按
  长任务约束验证真实授权，缺失时停止而不能模拟完成。

## 9. 四类 Review 与本地验证

| Review | 当前代码结论 | 证据 |
| --- | --- | --- |
| Requirement Conformance | Pass，无 P1/P2 | 10 份 ADR、18 个 Golden 文件、方案源文件 `cmp` 一致、唯一 Flag 默认关闭 |
| Correctness / Data Consistency / Concurrency | Pass，无 P1/P2 | v1 Fingerprint v1/v2/v3、v1→v2 确定性、受守卫降级、Workflow Roundtrip；无 Migration，0045 单 Head |
| Security / Tenant / Secret / SSRF | Pass，无 P1/P2 | 新 Domain 无 FastAPI/Celery/SQLAlchemy 依赖；Fixture 无凭据/PEM/连接串；Scope 与 Production Preview 硬边界已冻结 |
| End-to-End User Flow | Pass（S48 适用范围） | Login→Create→Query Golden 可解析、验证、转换；隔离 Compose 的登录 Setup + S22 能力/安全/深链 Playwright `2 passed` |

本地 Required Checks：Backend format/Ruff/Mypy/Pytest 全绿，`638 passed / 4 skipped`，Coverage `90.21%`；
Frontend format/lint/coverage/build 全绿，`56 files / 215 tests`，Branch Coverage `80.11%`。这些结果不替代
PR 精确 Head Remote CI。

隔离 Compose 使用本分支构建镜像并在替代端口全部健康；相关 Playwright `2 passed` 后已删除该临时项目的
容器、网络与数据卷。全量 21 条 E2E 曾作为诊断启动，但未按成功计：S19 依赖 CI Smoke 预先创建的固定
项目，S21/S23～S26 依赖 CI Job 显式开启既有 Feature Flag；日志分别为缺少种子和预期的 409
`FEATURE_DISABLED`。本次未修改这些历史测试或放宽门槛，Remote Compose Workflow 将按其完整前置运行。

2026-08-28 开 PR 前重新获取 GitHub 事实：`origin/main` 仍为冻结 SHA，Open PR 为 0；Ruleset 仍为 Active、
无 Bypass，Main SHA 对应的 Required Gate Controller、Security 和 Standalone Windows Bundle Push Run 均为
Success。以下第 10 节追加 PR 最终 Head、Review Thread、合并和 Main Push 的远程终态。

## 10. Remote CI、Review 与合并证据

### PR #46 最终 Head

| 项目 | 精确值 |
| --- | --- |
| PR | `#46` |
| Base SHA | `6370c6c8b44db51ce7717bc73eaf41f259c9df1b` |
| Final Head SHA | `13d80a856802d758bbe1e6b1da0c55330a4c8121` |
| Merge State | `CLEAN / MERGEABLE` |
| Merge 方式 | 普通 Squash Merge，未使用 Admin/Bypass |

| Workflow | Run ID | Head SHA | Conclusion |
| --- | --- | --- | --- |
| Backend CI | `33115205385` | `13d80a856802d758bbe1e6b1da0c55330a4c8121` | `success` |
| Frontend CI | `33115205482` | `13d80a856802d758bbe1e6b1da0c55330a4c8121` | `success` |
| Security CI | `33115205483` | `13d80a856802d758bbe1e6b1da0c55330a4c8121` | `success` |
| Compose Smoke Test | `33115205449` | `13d80a856802d758bbe1e6b1da0c55330a4c8121` | `success` |
| Standalone Windows Bundle | `33115205386` | `13d80a856802d758bbe1e6b1da0c55330a4c8121` | `success` |
| V2 to V3 Upgrade CI | `33115205450` | `13d80a856802d758bbe1e6b1da0c55330a4c8121` | `success` |
| Required Gate Controller / `Required Gate` | `33115203520` | `13d80a856802d758bbe1e6b1da0c55330a4c8121` | `success` |

首个 Head `132f97b1b8fdd5be7fb2d342d0cdecd49d9405b7` 的远程结果在 P2 修复后已被取代，不作为合并
证据。GitHub 自动 Review 对该旧 Head 提出 2 个 P2：

- 顶层 `bindings` 使用通配字典，拼写错误的未知键会进入语义指纹；
- 先规范化再校验会使错误路径索引指向排序后而非用户提交的数组。

最终 Head 新增严格 `FlowSpecBindingV2`、在原始提交顺序上校验并补充回归。两个 Thread 均已回复修复
证据，合并前状态为 `resolved=true`、`isOutdated=true`；未解决 Review Thread 为 0，无剩余 P1/P2。

### 合并后 Main Push

| 项目 | 精确值 |
| --- | --- |
| Merge SHA | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` |
| Merged At | `2026-08-27T21:20:15Z` |
| Ruleset | `main-required-gate` / ID `21653796` / Active / 无 Bypass |
| Required Context | `Required Gate` = `success` |

| Workflow | Run ID | Head SHA | Conclusion |
| --- | --- | --- | --- |
| Backend CI | `33117671975` | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` | `success` |
| Frontend CI | `33117672081` | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` | `success` |
| Security CI | `33117672027` | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` | `success` |
| Compose Smoke Test | `33117671974` | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` | `success` |
| Standalone Windows Bundle | `33117671958` | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` | `success` |
| V2 to V3 Upgrade CI | `33117671962` | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` | `success` |
| Required Gate Controller / `Required Gate` | `33117672031` | `588c19719f2fbfc22e1fe65e97e0d0d0f89fd4fe` | `success` |

上述为 GitHub Actions 远程事实，与第 9 节本地结果分开记录。S48 仍只是 V6 契约与治理基线，不因 CI
成功而升级为 Alpha/Beta/RC/GA；真实 Key Rotation、公司试点和人工签署仍未完成。
