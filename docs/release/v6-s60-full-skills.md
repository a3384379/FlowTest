# S60 — Full Skills 与 Continuous QA

## 范围与交付

基线为 S60A PR #87 合并后全绿 main。本批分支 `codex/v6-s60-full-skills` 一次完成剩余 S60，
开发期间只做必要定向回归；全部实现完成后集中验收、一个 PR、最终复审及 Required Gate。
不再为每个 Skill 单独推送或执行容量门禁。当前及后续均不要求公司 Windows 或其他实机测试。

四个新 Skill 与原旗舰 Skill 均可整目录复制安装：

| Skill | 实际交付 | 写入边界 |
| --- | --- | --- |
| flowtest-project-onboarding | 契约盘点、Context、Evidence、接入缺口 | 授权范围的 Context/Evidence |
| flowtest-complete-coverage | 现有覆盖分析、确定性设计、缺口提案 | 待审核 Test Design |
| flowtest-change-aware-regression | Context/Knowledge Diff、Affected Flow、已有 Run 的维护提案 | 原子创建并关联 AIChangeSet |
| flowtest-triage-and-repair | 实际失败诊断、受限修复、人工 Re-preview | 待审核 Repair Proposal |

所有包包含 SKILL.md、agents/openai.yaml、冻结 Manifest、自包含 evals 与评测说明。
Manifest 从领域 Profile 生成，并对真实注册工具、scope、阶段、禁止自动操作和独立运行路径进行回归。
不引入第二个 Context 管理中心、Repair/Change Maintenance 页面、数据表或状态机。

## MCP 契约

当前版本 `s60-continuous-qa-v1`，保留全部历史工具和旧版本 Skill Manifest。
新增工具均使用 `request` 强类型参数，不把执行 Context 暴露为调用方参数：

| 工具 | 权限 | 行为 |
| --- | --- | --- |
| flowtest.inspect_context_diff | mcp:read | 固定两个 Revision 的 Context/Knowledge 差异 |
| flowtest.inspect_affected_flows | mcp:read | 分页、预算与 requires_review 原样保留 |
| flowtest.diagnose_failure | mcp:read | 终态失败诊断；省略原始名称、路径、Body |
| flowtest.inspect_change_regression | mcp:read | 读取现有 Run 快照，不同步或推进执行 |
| flowtest.propose_repair | mcp:flow:propose | 默认 Dry Run；实际写入需要幂等键 |
| flowtest.propose_maintenance | mcp:flow:propose | 默认 Dry Run；必须绑定已有 Context Regression Run |

所有工具同时执行租户/项目授权。Repair/Maintenance 的授权、Context、目标版本、敏感值、白名单与
可信 Provenance 在 Claim 前校验，提交前重验；Claim 按 Service Account 隔离。提案、关联、Audit 和
Claim 完成记录原子提交，失败不会遗留孤立 Proposal。Dry Run 不创建 Proposal 或 Claim。

`inspect_change_regression` 的提案状态是快照，不冒充实时状态；Skill 在决策或 Preview 前重新读取
`inspect_flow_proposal`。现有 API 的同步执行行为不变，新只读入口专用 `inspect`。
只读输出有大小上限并执行敏感扫描，拒绝时仅返回标准错误码与 Trace ID，不回显输入内容。

## 人工控制与持续质量

沿用 S45/S59：Change → Impact → Context/Knowledge Diff → Affected Flow → Maintenance Proposal →
人工 Review → 可选 Sandbox Preview → 人工 Apply/Publish → 固定版本 TestPlan → 正式 Execution →
Release Gate。MCP 只提供上述分析和提案入口；没有 Accept、Apply、Publish 或正式执行工具。

Preview 必须重新确认 accepted + unapplied、非生产环境，以及绑定当前执行 Service Account 的
Fresh One-time Approval；Preview 和 Cleanup 结果不代替正式执行覆盖，不豁免 Release Gate。
Product Defect Guard、独立 Cleanup 分类、启发式不授予 Patch 权限和版本策略锁定均复用原领域服务。

## 遗留项实际修复

- S59D 已接受 P2：维护校验移至暂存 ChangeSetApproval 之前。过期 Context 的内部提交不再带出
  尚未验证的审核记录；定向用例先复现旧代码持久化 1 条，再验证修复后为 0。
- S60A 已接受 P2：构建与 --check 均拒绝 Fixture 重命名/删除后的多余旧副本；不会静默删除文件。
  先以临时目录复现，再验证两个模式均失败关闭。

以上是本地代码修复，不以“Review Thread resolved”替代修复证据；最终合并状态另行记录。

## 评测与验收口径

唯一评分源为后端 v6_evaluation；五个包由同一脚本生成副本，--check 直接比较内容。
复制包后在禁止导入 app、禁止联网的独立进程中实际执行 Evaluator。
这仅是既有 V6 产品 Golden 标注聚合，**不是四个 Skill 的 LLM 效果实验**，也没有重跑生产业务。
四个 Skill 的工具行为另由真实 MCP SDK → HTTP → 领域服务 → 数据库回归验证。

本地集中验收：

- Backend Format/Ruff、mypy（含仓库脚本）及领域依赖边界通过。
- 完整 Pytest：1201 passed、4 skipped、1 个旧 Environment Lab 子进程用例两秒超时；
  Coverage 91.12%。该用例原样单独复核通过；未修改代码，不将首轮记录写成全绿。
- Frontend Format/Lint/TypeScript/Build 通过；238 tests passed，Branch Coverage 80.30%。
- 四个 Skill 元数据校验、生成源一致性校验通过；复制安装到仓库外，在没有 FlowTest 安装、
  仅有声明 Pydantic 依赖的 Python 3.13 环境逐包执行 --check 全部通过。
- Compose 现有 S58 Review/Re-preview Playwright：2 passed；另以新 MCP 创建 Binding Repair，
  验证诊断、无写入 Dry Run、相同键返回同一提案，原审核页面待审核时 Preview 禁用，接受后
  真实 Worker 的 Preview 与 Cleanup 均 passed。验收提案 `02d0b7af-d954-479b-a20d-27a5c5e8b7f3`；
  未 Apply、未发布或正式执行。
- 新增 48 项测试包含四个 Skill 的真实 MCP/HTTP 链路、默认 Dry Run、幂等与事务回滚、租户隔离、
  无自动审核/应用、人工接受后一次性 Preview、独立包运行和冻结工具契约。

### 最终合并与主线证据（2026-09-06 补录）

[PR #88](https://github.com/a3384379/FlowTest/pull/88) 已于 2026-09-06 01:07:49 UTC 普通合并。
最终 Head `19ec13d69d7b60e796dd62603c6eba8287df8236`；合并提交
`6440e305cd2987ccec2f635b0e3ca0ca28933dc4`。最终复审没有新增 P0/P1，PR Required Gate 成功。
合并后实际触发的六个工作流均为 completed/success：

| 工作流 | Run ID |
| --- | --- |
| Backend CI | 34003088905 |
| Standalone Windows Bundle | 34003088895 |
| Upgrade / Rollback | 34003088907 |
| Security CI | 34003088897 |
| Compose Smoke | 34003088898 |
| Required Gate Controller | 34003088902 |

最终远程后端验收为 1201 passed / 6 skipped、Coverage 91.12%；与上面的本地首轮记录分开保留。
此次主线没有单独触发 Frontend CI，不写成“七项全绿”；跳过的 Compact/容量门禁不算执行通过。
[最终验收评论](https://github.com/a3384379/FlowTest/pull/88#issuecomment-5556111129) 汇总 Review 与 CI。

PR #88 首轮复审：工具中文说明 P1 已修复并增加契约回归。另有 1 项 P2 按用户策略接受为后续
技术债，当前未修复；详细内容保留在原复审记录，不在此重复披露。线程解决不代表代码已修复。
上述为合并时的债务状态；后续修复状态统一见 [V6.2 收尾](v6-2-consolidation.md)。
回滚为普通 revert 本批代码和新增包，无数据库迁移；原工具、原 Skill 与原业务生命周期保持可用。

## 后续评估，不属于本次交付

Provider Marketplace 需独立供应链签名/兼容治理；Server-side MCP Federation 需新增信任和出站边界；
额外语言需新的保守 Provider/Golden；Property Testing 需可复现 Seed 和 Oracle 合约；
Traffic Record → FlowSpec 需用户同意、脱敏与采集边界。均保持评估状态，不自动启用或纳入 P0。
S60 开发完成不等于生产 GA 授权；连续 RC、外部恢复、安全审批及人工签署不由此自动满足。
