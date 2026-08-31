# FlowTest V6.0 Core RC 验收证据

## 1. 当前判定

| 项目           | 判定                                                                      |
| -------------- | ------------------------------------------------------------------------- |
| H0_READY       | YES                                                                       |
| V6_ALPHA_READY | YES                                                                       |
| V6_BETA_READY  | YES                                                                       |
| V6_RC_READY    | YES — PR #67 复审、Remote CI、显式 RC 重门禁、普通合并与 Main Push 已闭环 |
| GA_READY       | NO — 连续 RC、公司实机、安全审批和人工签署尚未完成                        |

本文件记录 RC 候选的可复现证据，不创建 Tag 或 GitHub Release，也不把开发 Fixture 结果冒充公司试点或
GA 外部签署。

## 2. Identity 与版本

| 项目                       | 值                                                              |
| -------------------------- | --------------------------------------------------------------- |
| Branch                     | `codex/v6-s56-rc-evidence`                                      |
| Branch Head                | `39a532fd90762c92177fd5d04a334b6c774f8367`                      |
| Merge Commit               | `3c25a19959d0463582522b5263940ed5322368ae`                      |
| Tree Equivalence           | Head/Merge Tree 均为 `6e4bd6344088f3318ba1d05be284b82861e42c74` |
| Alembic Head               | `20260831_0051`                                                 |
| Standalone Schema Revision | `20260831_0051`                                                 |
| Skill                      | `flowtest-generate-integration-flow@1.0.0-rc.1`                 |
| Minimum MCP Version        | `s55-sandbox-preview-v1`                                        |

S56 RC 候选本身没有新增数据库表或迁移，当时保持 S55 的 `20260830_0050`。
后续跨阶段审计 PR #69 为 API Version 增加可移植 Service Identity，将当前 Alembic/Standalone
单 Head 提升为 `20260831_0051`。Skill 包、Golden Evaluation 与文档可代码回滚，不能改变历史
Workflow/Execution Snapshot。

## 3. Alpha → Beta → RC 链路

| 阶段  | 证据                                                                                                                       | 结论                             |
| ----- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| Alpha | S51 Context → Evidence → Plan → Compile → MCP Dry Run/Draft → Visual Review，见 `v6-s51-mcp-visual-proposal.md`            | 已合并并完成主线 CI              |
| Beta  | H1 真实 Key Rotation 与 S55 Sandbox Preview/Cleanup/Approval，见 `v6-h1-real-key-rotation.md`、`v6-s55-sandbox-preview.md` | 已合并；S55 Main 7 项 CI 全绿    |
| RC    | Flagship Skill、模型无关 Evaluation、兼容性、文档与重门禁后移                                                              | PR #67 已合并；RC 自动化证据闭环 |

## 4. Flagship Skill Contract

- 安装包：`skills/flowtest-generate-integration-flow/`。
- Manifest 固定 Version、Minimum MCP Version、Required/Optional Tools、Scopes、外部只读 Code/DB MCP、
  Human Approval、Stop Conditions、Security Rules、Stages 与 Evaluation 路径。
- 标准链路为 Project → Context → Missing Evidence → External Evidence → Ingest → Plan → Compile → Dry Run
  → Propose Draft → Visual Review；Preview 仅为显式可选分支。
- Skill 不提供 Accept、Apply、Publish、生产执行、Credential、权限修改、任意代码、写 SQL、删除或自动 Repair。
- `quick_validate.py` 与 `test_s56_core_rc.py` 共同验证可安装结构和实时 MCP Tool/Scope 契约。

## 5. Model-independent Golden Evaluation

| Metric                                                 |       精确结果 | 发布策略                    |
| ------------------------------------------------------ | -------------: | --------------------------- |
| Operation Candidate Precision                          | 3/3 = 1.000000 | Fixture 基线，不设 95% 门槛 |
| Binding Candidate Precision                            | 2/3 = 0.666667 | Fixture 基线，不设 90% 门槛 |
| Compiler Success                                       | 1/1 = 1.000000 | 必须 1.0                    |
| Manual Edit Rate                                       | 0/1 = 0.000000 | Fixture 基线                |
| Preview First-pass                                     | 1/1 = 1.000000 | 必须 1.0                    |
| Evidence Conflict Rate                                 | 1/1 = 1.000000 | 故意包含冲突的 Fixture 基线 |
| Evidence Conflict Detection                            | 1/1 = 1.000000 | 必须 1.0                    |
| Static Validation                                      | 1/1 = 1.000000 | 必须 1.0                    |
| Secret Leak / Cross-Tenant / Stale Overwrite           |         各 0/1 | 必须 0                      |
| Unreviewed Apply / Production MCP Preview              |         各 0/1 | 必须 0                      |
| Arbitrary Code / Write SQL                             |         各 0/1 | 必须 0                      |
| Cleanup Silent Failure / Product Defect Auto-Weakening |         各 0/1 | 必须 0                      |

Golden 注解的每个 `pytest://` Evidence Ref 必须解析到真实测试函数；空分母为
`insufficient_evidence`，发布硬门槛不能把它当作 Pass。`scripts/evaluate_v6_core.py --check` 对提交的
Baseline 做确定性比较并在任一硬门槛缺证或失败时退出非零。

## 6. Compatibility

| Surface                                | 证据与判定                                                                      |
| -------------------------------------- | ------------------------------------------------------------------------------- |
| V5 FlowSpec Import / Fingerprint       | v1/v2/v3 Golden Fingerprint、v1→v2、受守卫 v2→v1、未知字段拒绝                  |
| V5 Workflow Draft / Published Workflow | v1 Workflow Roundtrip 与既有 Review/Apply/Publish 回归，不改写历史版本          |
| V5 Execution Snapshot                  | Golden `1.0` Snapshot 解析，历史 Snapshot 不迁移                                |
| V5 TestCase / Suite / Plan             | Backend 全量回归与既有 Schema 保持通过                                          |
| Existing MCP Tools                     | Golden MCP Tool 列表与官方 SDK Contract Test；Skill Tool 必须为其子集           |
| MCP stdio / Streamable HTTP            | 同一 `flowtest-mcp` Server/Gateway 契约，关闭 MCP 不影响 Web/API                |
| Standalone Upgrade                     | Windows Bundle、Standalone Schema `20260831_0051` 与升级回归                    |
| Compact / Full                         | Compose 核心 Smoke；复审清除 P0/P1 后显式 `run_rc_gates=true` 执行 Compact RC   |
| Backup / Restore                       | Compose 隔离卷恢复与 Compact 非空备份恢复                                       |
| Upgrade / Rollback                     | V2→V3 CI 与 Compact Offline Upgrade 自动回滚证据                                |
| Standalone → Compact                   | `storage_transfer.py` 与 `standalone-transfer-manifest.json` 双端 Revision 校验 |

## 7. CI 执行策略

普通 PR 与 Main Push 运行 Backend、Frontend（适用时）、Security、Standalone、Upgrade 和核心 Compose
Smoke。Compact 验收及 API/Workflow/1000-task/S29 容量门禁保留在同一 Compose Workflow，但仅在最新复审
无 P0/P1 后显式 `workflow_dispatch` 且 `run_rc_gates=true` 时执行。Required Gate 普通路径只等待核心
`smoke`，避免每个小修重复消耗 RC 级资源；`skills/**` 仍由 Backend 与 Security 门禁覆盖。该策略已由
普通合并的 Bootstrap PR #65/#66 固化；S56 RC 合并前已记录一次成功的显式重门禁运行。

## 8. Local Tests 与 Coverage

当前已完成：

- Skill Creator `quick_validate.py`：PASS；
- S56 Skill/Evaluation 与 V6 Golden 定向集：`17 passed`；
- S48～S55 Evidence/Compiler/Stale/Conflict/MCP/Preview/Cleanup 跨阶段定向回归：`26 passed`；
- Ruff Format、Ruff、Mypy：PASS；
- `evaluate_v6_core.py --check`：PASS。

PR #67 Remote Backend CI 已完成仓库全量 Pytest 与 Coverage 门槛；本节只记录门槛结果，不从定向子集
外推或伪造全库覆盖率。

## 9. Remote CI、Compose 与 Review

### S55 合并后 Main 基线

| Workflow                  |        Run ID | Conclusion |
| ------------------------- | ------------: | ---------- |
| Backend CI                | `33308150863` | success    |
| Frontend CI               | `33308150850` | success    |
| Security CI               | `33308150847` | success    |
| Standalone Windows Bundle | `33308150815` | success    |
| V2 to V3 Upgrade CI       | `33308150821` | success    |
| Compose Smoke Test        | `33308150834` | success    |
| Required Gate Controller  | `33308150818` | success    |

### S56 PR #67

| Workflow                  |        Run ID | Conclusion                              |
| ------------------------- | ------------: | --------------------------------------- |
| Backend CI                | `33313742956` | success                                 |
| Security CI               | `33313742934` | success                                 |
| Standalone Windows Bundle | `33313742979` | success                                 |
| V2 to V3 Upgrade CI       | `33313743120` | success                                 |
| Compose Smoke Test        | `33313743066` | success；`compact-smoke` 按普通路径跳过 |
| Required Gate Controller  | `33313743086` | success                                 |
| Frontend CI               |        未触发 | PR 不含 Frontend 变更                   |

- 最新 GitHub `@codex review` 于 2026-08-30 完成：P0=`0`、P1=`0`、P2=`3`；审计未使用本地模型自审。
- 显式 RC Compose Run `33314854497` 使用 `run_rc_gates=true`，`smoke` 与 `compact-smoke` 均 success；
  API/Workflow、1000-task durable queue、S29 5000-queue/500-workflow、Backup/Recovery 全部通过。
- PR #67 于 `2026-08-30T14:07:41Z` 普通 Squash Merge，无 Admin/Bypass；Head 与 Merge Tree 完全一致。

### S56 合并后 Main Push

| Workflow                  |        Run ID | Conclusion                              |
| ------------------------- | ------------: | --------------------------------------- |
| Backend CI                | `33316015138` | success                                 |
| Security CI               | `33316015155` | success                                 |
| Standalone Windows Bundle | `33316015132` | success                                 |
| V2 to V3 Upgrade CI       | `33316015179` | success                                 |
| Compose Smoke Test        | `33316015151` | success；Compact/容量步骤按普通路径跳过 |
| Required Gate Controller  | `33316015182` | success                                 |
| Frontend CI               |        未触发 | Merge 不含 Frontend 变更                |

## 10. Security 与 Remaining Risks

已实现硬边界：Production Preview 拒绝、一次性 Approval、Tenant/Project/Service Account 绑定、Secret
只写与脱敏、外部 MCP 不可信、无任意代码、无写 SQL、无自动 Apply/Publish、Cleanup 失败可见、Stale
Revision 拒绝。

最新复审保留三个不阻塞 RC 的 P2：Preview 可选分支应更明确要求已接受且未 Apply 的 Proposal；硬门槛
状态未来应直接比较未舍入的 numerator/denominator；独立安装 Skill 时 Evaluation Assets 与 Evaluator
尚未内置在 Skill 目录。三个 Review Thread 已按用户批准的 P0/P1 阻塞策略记录并 Resolve，后续版本可
独立处理，不能据此扩大当前 Golden Fixture 的质量宣称。

外部门槛仍未宣称完成：连续 RC 观察、公司 Windows 实机/长时运行、独立安全审批和人工签署。代码与
自动化证据已经闭环，因此判定 `V6_RC_READY=YES`；上述外部门槛未满足，`GA_READY` 必须保持 `NO`。

## 11. Post-RC 跨阶段最终审计修正

PR #69 对 S48～S56 的实现与历史复审意见做了一次集中收口，没有改变 RC/GA 判定边界。
主要修正包括：

- FlowSpec 跨实例 Service/Operation Identity 与历史 Fingerprint 兼容，并通过
  `20260831_0051` 回填 API Version Service Identity；
- Change Regression 对历史 Contract Fingerprint 与 Frozen Service Identity 的兼容；
- MCP Flow Proposal 在持久化前拒绝递归容器、映射、参数、断言、条件、Extract 与完整
  JMESPath AST 中的 Secret/Credential/PII 字面量，动态路径与 `secret://` 引用保持允许；
- 历史 PR #50～#53 的 P1 均由 #69 覆盖，P2 按发布策略接受为 V6.1 技术债，相关线程均已回复并关闭。

### PR #69 最终候选门禁

| Workflow                  |        Run ID | Conclusion |
| ------------------------- | ------------: | ---------- |
| Backend CI                | `33337955148` | success    |
| Frontend CI               | `33337955365` | success    |
| Security CI               | `33337955142` | success    |
| Compose Smoke Test        | `33337955143` | success    |
| Standalone Windows Bundle | `33337955134` | success    |
| V2 to V3 Upgrade CI       | `33337955164` | success    |
| Required Gate Controller  | `33337954097` | success    |

最新 GitHub `@codex review` 明确返回未发现重大问题，最终阻塞级结果为 P0=`0`、P1=`0`。
PR #69 随后普通 Squash Merge，未使用 Admin/Bypass/Force Push/Direct Main Push。

### #69 合并后 Main Push

| Workflow                  |        Run ID | Conclusion |
| ------------------------- | ------------: | ---------- |
| Backend CI                | `33339424522` | success    |
| Frontend CI               | `33339424565` | success    |
| Security CI               | `33339424584` | success    |
| Compose Smoke Test        | `33339424592` | success    |
| Standalone Windows Bundle | `33339424561` | success    |
| V2 to V3 Upgrade CI       | `33339424562` | success    |
| Required Gate Controller  | `33339424599` | success    |
