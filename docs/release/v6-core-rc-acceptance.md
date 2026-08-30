# FlowTest V6.0 Core RC 验收证据

## 1. 当前判定

| 项目 | 判定 |
| --- | --- |
| H0_READY | YES |
| V6_ALPHA_READY | YES |
| V6_BETA_READY | YES |
| V6_RC_READY | NO — 等待本 S56 PR 最新 Head 的复审、Remote CI、RC 重门禁与普通合并 |
| GA_READY | NO — 连续 RC、公司实机、安全审批和人工签署尚未完成 |

本文件记录 RC 候选的可复现证据，不创建 Tag 或 GitHub Release，也不把开发 Fixture 结果冒充公司试点或
GA 外部签署。

## 2. Identity 与版本

| 项目 | 值 |
| --- | --- |
| Branch | `codex/v6-s56-rc-evidence` |
| Branch Head | 合并前由 S56 PR 精确记录 |
| Merge Commit | 普通 Squash Merge 后补录 |
| Tree Equivalence | 合并后比较 S56 PR Tree 与 Main Merge Tree |
| Alembic Head | `20260830_0050` |
| Standalone Schema Revision | `20260830_0050` |
| Skill | `flowtest-generate-integration-flow@1.0.0-rc.1` |
| Minimum MCP Version | `s55-sandbox-preview-v1` |

S56 没有新增数据库表或迁移；Migration/Standalone Revision 保持 S55 的单 Head。Skill 包、Golden
Evaluation 与文档可代码回滚，不能改变历史 Workflow/Execution Snapshot。

## 3. Alpha → Beta → RC 链路

| 阶段 | 证据 | 结论 |
| --- | --- | --- |
| Alpha | S51 Context → Evidence → Plan → Compile → MCP Dry Run/Draft → Visual Review，见 `v6-s51-mcp-visual-proposal.md` | 已合并并完成主线 CI |
| Beta | H1 真实 Key Rotation 与 S55 Sandbox Preview/Cleanup/Approval，见 `v6-h1-real-key-rotation.md`、`v6-s55-sandbox-preview.md` | 已合并；S55 Main 7 项 CI 全绿 |
| RC | Flagship Skill、模型无关 Evaluation、兼容性、文档与重门禁后移 | 本 PR 收口中 |

## 4. Flagship Skill Contract

- 安装包：`skills/flowtest-generate-integration-flow/`。
- Manifest 固定 Version、Minimum MCP Version、Required/Optional Tools、Scopes、外部只读 Code/DB MCP、
  Human Approval、Stop Conditions、Security Rules、Stages 与 Evaluation 路径。
- 标准链路为 Project → Context → Missing Evidence → External Evidence → Ingest → Plan → Compile → Dry Run
  → Propose Draft → Visual Review；Preview 仅为显式可选分支。
- Skill 不提供 Accept、Apply、Publish、生产执行、Credential、权限修改、任意代码、写 SQL、删除或自动 Repair。
- `quick_validate.py` 与 `test_s56_core_rc.py` 共同验证可安装结构和实时 MCP Tool/Scope 契约。

## 5. Model-independent Golden Evaluation

| Metric | 精确结果 | 发布策略 |
| --- | ---: | --- |
| Operation Candidate Precision | 3/3 = 1.000000 | Fixture 基线，不设 95% 门槛 |
| Binding Candidate Precision | 2/3 = 0.666667 | Fixture 基线，不设 90% 门槛 |
| Compiler Success | 1/1 = 1.000000 | 必须 1.0 |
| Manual Edit Rate | 0/1 = 0.000000 | Fixture 基线 |
| Preview First-pass | 1/1 = 1.000000 | 必须 1.0 |
| Evidence Conflict Rate | 1/1 = 1.000000 | 故意包含冲突的 Fixture 基线 |
| Evidence Conflict Detection | 1/1 = 1.000000 | 必须 1.0 |
| Static Validation | 1/1 = 1.000000 | 必须 1.0 |
| Secret Leak / Cross-Tenant / Stale Overwrite | 各 0/1 | 必须 0 |
| Unreviewed Apply / Production MCP Preview | 各 0/1 | 必须 0 |
| Arbitrary Code / Write SQL | 各 0/1 | 必须 0 |
| Cleanup Silent Failure / Product Defect Auto-Weakening | 各 0/1 | 必须 0 |

Golden 注解的每个 `pytest://` Evidence Ref 必须解析到真实测试函数；空分母为
`insufficient_evidence`，发布硬门槛不能把它当作 Pass。`scripts/evaluate_v6_core.py --check` 对提交的
Baseline 做确定性比较并在任一硬门槛缺证或失败时退出非零。

## 6. Compatibility

| Surface | 证据与判定 |
| --- | --- |
| V5 FlowSpec Import / Fingerprint | v1/v2/v3 Golden Fingerprint、v1→v2、受守卫 v2→v1、未知字段拒绝 |
| V5 Workflow Draft / Published Workflow | v1 Workflow Roundtrip 与既有 Review/Apply/Publish 回归，不改写历史版本 |
| V5 Execution Snapshot | Golden `1.0` Snapshot 解析，历史 Snapshot 不迁移 |
| V5 TestCase / Suite / Plan | Backend 全量回归与既有 Schema 保持通过 |
| Existing MCP Tools | Golden MCP Tool 列表与官方 SDK Contract Test；Skill Tool 必须为其子集 |
| MCP stdio / Streamable HTTP | 同一 `flowtest-mcp` Server/Gateway 契约，关闭 MCP 不影响 Web/API |
| Standalone Upgrade | Windows Bundle、Standalone Schema `20260830_0050` 与升级回归 |
| Compact / Full | Compose 核心 Smoke；复审清除 P0/P1 后显式 `run_rc_gates=true` 执行 Compact RC |
| Backup / Restore | Compose 隔离卷恢复与 Compact 非空备份恢复 |
| Upgrade / Rollback | V2→V3 CI 与 Compact Offline Upgrade 自动回滚证据 |
| Standalone → Compact | `storage_transfer.py` 与 `standalone-transfer-manifest.json` 双端 Revision 校验 |

## 7. CI 执行策略

普通 PR 与 Main Push 运行 Backend、Frontend（适用时）、Security、Standalone、Upgrade 和核心 Compose
Smoke。Compact 验收及 API/Workflow/1000-task/S29 容量门禁保留在同一 Compose Workflow，但仅在最新复审
无 P0/P1 后显式 `workflow_dispatch` 且 `run_rc_gates=true` 时执行。Required Gate 普通路径只等待核心
`smoke`，避免每个小修重复消耗 RC 级资源；`skills/**` 仍由 Backend 与 Security 门禁覆盖。该策略已由
普通合并的 Bootstrap PR #65/#66 固化，S56 RC 合并前仍必须记录一次成功的显式重门禁运行。

## 8. Local Tests 与 Coverage

当前已完成：

- Skill Creator `quick_validate.py`：PASS；
- S56 Skill/Evaluation 与 V6 Golden 定向集：`17 passed`；
- S48～S55 Evidence/Compiler/Stale/Conflict/MCP/Preview/Cleanup 跨阶段定向回归：`26 passed`；
- Ruff Format、Ruff、Mypy：PASS；
- `evaluate_v6_core.py --check`：PASS。

最终 PR Remote Backend CI 负责仓库全量 Pytest 与 Coverage；本节不在结果产生前预填覆盖率。

## 9. Remote CI、Compose 与 Review

### S55 合并后 Main 基线

| Workflow | Run ID | Conclusion |
| --- | ---: | --- |
| Backend CI | `33308150863` | success |
| Frontend CI | `33308150850` | success |
| Security CI | `33308150847` | success |
| Standalone Windows Bundle | `33308150815` | success |
| V2 to V3 Upgrade CI | `33308150821` | success |
| Compose Smoke Test | `33308150834` | success |
| Required Gate Controller | `33308150818` | success |

S56 PR 的 Remote CI Run IDs、`run_rc_gates=true` RC Run、最新 `@codex review` P0/P1、Review Thread、
Merge 与合并后 Main Push 结果在流程完成后补录。代码审计使用 GitHub `@codex review`，不以本地模型自审
替代；最新复审 P0/P1 为零即可按用户指令合并，P2 记录为 Remaining Risk。

## 10. Security 与 Remaining Risks

已实现硬边界：Production Preview 拒绝、一次性 Approval、Tenant/Project/Service Account 绑定、Secret
只写与脱敏、外部 MCP 不可信、无任意代码、无写 SQL、无自动 Apply/Publish、Cleanup 失败可见、Stale
Revision 拒绝。

外部门槛仍未宣称完成：连续 RC 观察、公司 Windows 实机/长时运行、独立安全审批和人工签署。因此本次
可在代码与自动化证据闭环后判定 `V6_RC_READY=YES`，但 `GA_READY` 必须保持 `NO`。
