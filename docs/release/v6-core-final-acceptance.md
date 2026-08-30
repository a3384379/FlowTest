# FlowTest V6.0 Core 最终验收报告

## 1. 验收基线与范围

| 项目                | 最终事实                                                                          |
| ------------------- | --------------------------------------------------------------------------------- |
| 验收日期            | 2026-08-31（Asia/Shanghai）                                                       |
| 仓库                | `a3384379/FlowTest`                                                               |
| 范围                | V5 Post-Merge H0、V6 S48～S56、H1、跨阶段最终审计                                 |
| 最终修正            | PR #69 `fix: close V6 review security gaps`，已普通 Squash Merge                  |
| Alembic Head        | `20260831_0051`（单 Head）                                                        |
| Standalone Revision | `20260831_0051`                                                                   |
| Main 治理           | Ruleset `21653796` Active；Required Gate；Review Thread 必须解决；无 Bypass Actor |
| 发布动作            | 未创建 Tag/GitHub Release，未声称 GA                                              |

本报告以代码、迁移、GitHub PR/Review/Actions 与合并后 Main 证据为事实源。方案文档中的
未来态描述不代替实际验收结果。

## 2. 串行阶段与 PR 闭环

| 阶段         | 主要内容                                                | PR       | 结论                 |
| ------------ | ------------------------------------------------------- | -------- | -------------------- |
| H0           | V5 Post-Merge 正确性、安全与仓库治理                    | #42～#45 | 已闭环               |
| S48          | Contract Freeze、FlowSpec v2、V6 Governance Baseline    | #46～#47 | 已闭环               |
| S49          | Context Revision、External Evidence、Draft-only Adapter | #49～#52 | 已闭环               |
| S50          | Multi-Operation Plan 与 Executable Compiler             | #53～#54 | 已闭环               |
| S51          | MCP Flow Draft 与 Visual Proposal Alpha                 | #55～#57 | Alpha Exit 已满足    |
| S52          | Java/DB Evidence Adapter 与 Entity Mapping              | #58～#59 | 已闭环               |
| S53          | Data Recipe、Cross-API/DB Oracle                        | #60～#61 | 已闭环               |
| S54          | Cleanup / Compensation Runtime                          | #62      | 已闭环               |
| H1           | 真实 Key Rotation                                       | #63      | 代码与主线验收已闭环 |
| S55          | Sandbox Preview Beta                                    | #64      | Beta Exit 已满足     |
| CI Bootstrap | RC 重门禁后移且保留 Required Gate                       | #65～#66 | 已闭环               |
| S56          | Flagship Skill、Evaluation、Compatibility、RC Evidence  | #67～#68 | RC Exit 已满足       |
| Final Audit  | 跨阶段语义、兼容性与敏感值收口                          | #69      | P0/P1 清零并普通合并 |

各阶段均使用独立分支、PR 复审、适用的远程门禁和普通 Squash Merge；没有 Admin Merge、
Ruleset Bypass、Force Push 或直接推送 Main。

## 3. V6 Core 能力验收矩阵

| 能力面             | 关键验收点                                                                      | 结果              |
| ------------------ | ------------------------------------------------------------------------------- | ----------------- |
| Context / Evidence | 不可变 Revision、稳定 Fingerprint、Conflict/Completeness、TTL                   | Pass              |
| External Adapter   | Java/Spring 静态证据、DB Schema/Profile、映射候选与冲突                         | Pass              |
| Plan / Compiler    | 多 Operation、证据绑定、确定性编译、可执行 FlowSpec                             | Pass              |
| MCP Proposal       | Dry Run 无持久化、Draft-only、幂等、Stale/Scope/Tenant 阻断                     | Pass              |
| Visual Review      | Existing/Proposed Diff、Accept/Reject、无自动 Apply/Publish                     | Pass              |
| Data / Oracle      | Synthetic、Cross-API Assert、参数化只读 DB Oracle                               | Pass              |
| Cleanup            | Main/Cleanup Phase、Budget、Retry、Cancel、Checkpoint、Report                   | Pass              |
| Sandbox Preview    | Test/Sandbox-only、一次性 Approval、Budget、Evidence、Production 硬拒绝         | Pass              |
| Key Rotation       | Re-encrypt、Verify、Activate、Rollback、Audit                                   | Pass（代码/主线） |
| Skill / Evaluation | 可安装 Skill、MCP Tool/Scope 契约、Golden 硬门槛                                | Pass              |
| Compatibility      | FlowSpec v1/v2/v3、Workflow/Snapshot、Standalone/Compact/Full、Upgrade/Rollback | Pass              |

## 4. H0 四项基线缺陷

| H0 缺陷                      | 原风险                                           | 最终状态             |
| ---------------------------- | ------------------------------------------------ | -------------------- |
| Project 创建权限绕过         | Organization Viewer 可绕过 `create_project` 能力 | 已修复并回归         |
| URL Import DNS Rebinding     | DNS 校验与真实连接存在 TOCTOU                    | 已修复并回归         |
| Organization USER_COUNT 配额 | 新增成员未强制配额且可并发超限                   | 已修复并回归         |
| Standalone 0044→0045         | 旧 SQLite 不会完整推进 Waiver Schema             | 已修复并验证增量升级 |

H0 同时建立了 Main Ruleset 和始终可汇总路径适用门禁的 Required Gate；V6 S48 只在 H0
合并且 Main 门禁通过后开始。

## 5. 测试、迁移与兼容证据

- 各阶段保留各自的 Backend/Frontend 全量覆盖率、定向回归、Compose/Playwright、迁移往返与
  敏感日志扫描证据，详见各 `v6-s*.md` 阶段记录。
- S56 定向验收：Skill/Evaluation/Golden `17 passed`；S48～S55 跨阶段集
  `26 passed`；`evaluate_v6_core.py --check` 通过。
- 显式 RC Compose `33314854497` 通过 Full/Compact、API/Workflow 容量、1000-task 持久队列、
  S29 5000-queue/500-workflow 与 Backup/Recovery。
- 最终审计修正只在每次小修后运行 Ruff/Mypy 与相关定向回归；P0/P1 清零后才执行一次
  最终远程全量门禁，避免重复容量消耗。
- Alembic 与 Standalone 现为同一单 Head `20260831_0051`；V2→V3、Standalone Windows Bundle 与
  FlowSpec/Change Regression 历史兼容回归在 #69 候选门禁中全部通过。

## 6. 最终远程 CI 与主线证据

### PR #69 最终候选

| Workflow                  |        Run ID | Conclusion |
| ------------------------- | ------------: | ---------- |
| Backend CI                | `33337955148` | success    |
| Frontend CI               | `33337955365` | success    |
| Security CI               | `33337955142` | success    |
| Compose Smoke Test        | `33337955143` | success    |
| Standalone Windows Bundle | `33337955134` | success    |
| V2 to V3 Upgrade CI       | `33337955164` | success    |
| Required Gate Controller  | `33337954097` | success    |

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

关键阶段 Closure 合并后 Main Required Gate：S49 `33138252316`、S50 `33146326391`、
S52 `33258344270`、S53 `33274908154`，均为 Success。S55 与 S56 的 PR/Main 全量运行细节
分别记录于 `v6-s55-sandbox-preview.md` 和 `v6-core-rc-acceptance.md`。

## 7. 最终安全审计结论

- PR #69 最新 GitHub `@codex review` 明确返回未发现重大问题；P0=`0`、P1=`0`。
- 最终修正覆盖跨 Service Operation Identity、历史 Fingerprint、Service Target Override、
  递归容器、参数/映射/断言/条件/Extract 以及嵌套 JMESPath Literal 的凭据防泄漏。
- 敏感值在 MCP Flow Proposal 持久化之前 Fail Closed；标准错误信封不回显原值，动态路径和
  `secret://` 引用保持可用。
- 历史 PR #50～#53 的 P1 已标注由 #69 修复；P2 按批准的发布策略接受为 V6.1 技术债。
  相关线程已全部回复并关闭。
- PR #38～#69 共 32 个 PR 已汇总核对，未解决 Review Thread 为 `0`。
- 未实现自动 Apply/Publish、Production Preview、任意代码或写 SQL；Secret 仍为只写引用并加密存储。

## 8. 未完成范围与后续路线

### GA 外部门槛

- 连续 RC 观察期；
- Windows x64 公司实机/云桌面长时运行；
- 真实外部 Backup/Restore、Upgrade/Rollback 和 Standalone→Compact 迁移签署；
- 独立安全审批、生产发布授权与人工签署。

### 后续版本

- V6.1：S57/S58，处理已接受 P2、增强 Built-in Provider/Repair 与完整 Change Maintenance。
- V6.2：S59/S60，扩展企业规模化与长期运行能力。

上述项目不影响 V6 Core 的 Alpha/Beta/RC 代码验收，但在未取得真实外部证据前不得将
`GA_READY` 标记为 YES。

## 9. 最终判定

| 门槛           | 判定 | 依据                                                                    |
| -------------- | ---- | ----------------------------------------------------------------------- |
| H0_READY       | YES  | 四项 Post-Merge 缺陷、历史线程与 Main 治理已闭环                        |
| V6_ALPHA_READY | YES  | S51 可视化 Proposal 全链路与主线证据已闭环                              |
| V6_BETA_READY  | YES  | H1 + S55 Sandbox Preview/Cleanup/Approval 已闭环                        |
| V6_RC_READY    | YES  | S56 Skill/Evaluation/Compatibility、显式 RC 重门禁与 #69 最终审计已通过 |
| GA_READY       | NO   | 连续 RC、公司实机、外部恢复演练、安全审批与人工签署尚未完成             |

最终结论：FlowTest V6.0 Core 的开发、跨阶段正确性/安全修正与 RC 自动化验收已闭环；
当前可作为 RC 基线，不可作为 GA 签署。
