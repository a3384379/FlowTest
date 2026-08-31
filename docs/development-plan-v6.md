---
title: FlowTest V6.0 完整开发方案（GitHub 复核优化版）
document_type: Development Target
status: READY_AFTER_H0
document_version: 2.0
created_at: 2026-08-23
reviewed_at: 2026-08-27
baseline_repository: a3384379/FlowTest
current_main_sha: 945912c399a3e158a18bc5ad132dd1fb283641d3
v5_merge_commit_sha: 68fbde4b634589d13f263ed0d5a7827ca79aa3b0
v5_final_head_sha: 5c056d2ad37affc2e60f74a910e44364401e0292
current_migration_head: 20260823_0045
target_branch: codex/v6.0
product_theme: Visual AI Integration Test Engineer
supersedes: FlowTest_V6.0_Development_Plan_CN.md v1.0
language: zh-CN
---

# FlowTest V6.0 完整开发方案（GitHub 复核优化版）

> 本文档基于 2026-08-27 的 GitHub `main`、V5 合并结果、远程 CI、合并后 Review Threads 和当前代码重新审查。  
> 本文档替代 V6 方案 v1.0，作为后续 V6.0、V6.1 和 V6.2 开发的统一目标。  
> 任何代码实现、PR 描述或发布说明与本文冲突时，必须先修改 ADR 和本文档，不得通过实现事实静默改变产品目标。

---

# 0. 最终启动结论

## 0.1 是否可以启动 V6 开发

结论不是简单的“可以”或“不可以”，而是：

```text
V6 需求、ADR、回归测试和 H0 Hotfix：立即启动
V6 正式功能分支：H0 修复并合并后启动
V6 Sandbox Preview：Cleanup Runtime 与真实 Key Rotation 达标后启动
V6 正式发布：自动化、实机、长时运行和安全审批全部完成后启动
```

当前判定：

| 工作 | 判定 | 说明 |
| --- | --- | --- |
| 更新 V6 方案、ADR、Golden Set | GO | 不改变运行时，可立即执行 |
| 修复 V5 合并后发现的问题 | GO，最高优先级 | 两个 P1、两个 P2 均在当前 `main` 真实存在 |
| 创建 V6 功能分支并开发 S48 | CONDITIONAL GO | 必须从 H0 修复后的 `main` 创建 |
| 直接从当前 `main@945912c` 开始大规模 V6 Migration | NO-GO | 会把已知权限、SSRF 和 Standalone 升级缺陷固化为 V6 基线 |
| V6 Context、Planner、Compiler 的纯领域开发 | GO AFTER H0 | 不依赖 V5 GA |
| MCP 创建 FlowSpec Draft | GO AFTER H0 | 必须复用现有 ChangeSet 审核路径 |
| MCP 自动 Publish | NO-GO | V6 不提供 |
| MCP 正式环境自动执行 | NO-GO | V6 不提供 |
| Sandbox Preview | LATER | 必须先有清理/补偿、环境分类、审批和预算 |
| 宣称 V5 GA | NO-GO | 真实 Key Rotation、实机和外部审批仍未完成 |

## 0.2 启动 V6 的最小前置门槛

在创建 `codex/v6.0` 之前必须完成：

1. 修复项目创建权限绕过。
2. 修复 URL 导入 DNS Rebinding。
3. 修复组织成员数量配额。
4. 修复 Standalone `0044 → 0045` 兼容升级。
5. 为四项修复增加后端、集成、安全和 Standalone 回归测试。
6. 关闭已被主线吸收的旧 Draft PR #38、#39，并标记为 superseded。
7. 删除对应过期分支，避免误合并。
8. 为 `main` 开启 Branch Protection 或 Repository Ruleset。
9. 将本方案提交为 `docs/development-plan-v6.md`。
10. 在 H0 修复后的 `main` 记录正式 V6 Baseline SHA。
11. 从该 SHA 创建 V6 分支。
12. 不从已经删除的 `codex/v5.0` 分支继续开发。

---

# 1. GitHub 当前代码事实

## 1.1 V5 已经合并

V5 功能 PR #40 已于 2026-08-27 合并：

```text
PR: #40
V5 Final Head: 5c056d2ad37affc2e60f74a910e44364401e0292
Merge Commit: 68fbde4b634589d13f263ed0d5a7827ca79aa3b0
```

随后 V5 验收记录 PR #41 合并，当前 `main` 为：

```text
945912c399a3e158a18bc5ad132dd1fb283641d3
```

因此，原方案中“等待 V5 合并”已经完成，不再是 V6 启动条件。

## 1.2 V5 自动化门禁已具备较好基础

V5 最终代码提交及 `main` 合并后已经有：

- Backend CI；
- Frontend CI；
- Security CI；
- Compose Smoke；
- Standalone Windows Bundle；
- Upgrade / Rollback CI。

V5 功能层已经具备 V6 所需的绝大多数基础设施：

- API Definition / Version；
- Canonical Contract；
- Service / Endpoint Variant；
- React Flow Workflow；
- FlowSpec；
- AIChangeSet；
- MCP Read；
- MCP TestDesign Draft；
- Test Engineering；
- Durable Execution；
- Change Regression；
- Failure Triage；
- Standalone / Compact / Full。

## 1.3 当前仓库治理仍不适合直接进入下一轮大开发

当前 GitHub 仓库仍存在：

```text
main: protected = false
repository rulesets: []
```

仍有两条旧 Draft PR：

```text
#38 Compact Runtime
#39 Standalone Runtime
```

它们已经与当前 `main` 分叉且无法直接合并，但对应能力已经通过 V5 主线吸收。继续保留会造成：

- 新成员误认为仍需合并；
- Codex/LLM 审查时重复分析旧代码；
- 误用旧分支作为后续 Baseline；
- 无 Branch Protection 时存在误合并风险。

## 1.4 V5 验收文档与合并后 Review 之间存在时间差

V5 验收记录基于合并前代码证据，曾判断没有已知 P0/P1。

PR 合并后新增 Review Threads，当前代码复核确认以下问题仍然存在：

| 优先级 | 问题 | 当前判断 |
| --- | --- | --- |
| P1 | Organization Viewer 可创建项目并成为 Project Owner | 真实存在 |
| P1 | URL 导入校验 DNS 后由 HTTPX 重新解析，存在 DNS Rebinding | 真实存在 |
| P2 | 新增 Organization Member 未执行 USER_COUNT 配额 | 真实存在 |
| P2 | Standalone 0044 数据库缺少 0045 Waiver 列且 Revision 未推进 | 真实存在 |

因此：

> V5 已完成主功能合并，但当前 `main` 不是适合作为 V6 数据迁移和安全能力开发起点的“零已知 P1/P2 基线”。

---

# 2. H0：V5 Post-Merge Correctness Hotfix

H0 不计入 V6 功能开发，它是建立 V6 Baseline 的前置修复。

建议：

```text
分支：codex/v5-post-merge-hotfix
PR：V5 Post-Merge Correctness & Security Hotfix
版本语义：可作为 v5.0.1 修复候选
```

## 2.1 P1：项目创建权限绕过

### 当前问题

当前流程：

```text
ProjectService.create
→ _tenant_for_create
→ OrganizationQuotaService.enforce(PROJECT_COUNT)
→ 创建 Project
→ 将调用者设为 Project Owner
```

`_tenant_for_create` 只确认组织上下文或成员身份，没有检查：

```text
tenant.allows("create_project")
```

而 Organization Viewer 的能力只有：

```text
read
```

因此 Viewer 可以通过创建项目把自己提升为该项目 Owner。

### 最小修复

在任何配额检查和数据写入之前增加组织能力检查：

```text
if not tenant.allows("create_project"):
    raise ORGANIZATION_FORBIDDEN
```

不要仅依赖前端隐藏按钮。

### 回归测试

1. Organization Viewer 创建项目返回 403。
2. Organization Member 创建项目成功。
3. Organization Admin 创建项目成功。
4. Organization Owner 创建项目成功。
5. System Admin 创建项目成功。
6. Service Account 没有明确组织创建权限时不得创建项目。
7. 拒绝路径不增加 Project Count。
8. 拒绝路径不创建 ProjectMember。
9. 审计不能错误记录 `project.created`。

## 2.2 P1：URL 导入 DNS Rebinding

### 当前问题

当前 URL 导入：

```text
OutboundRequestGuard.enforce(url)
→ DNS 解析并校验地址
→ httpx.AsyncClient.stream("GET", url)
→ HTTPX 再次 DNS 解析
```

校验使用的 IP 和实际连接 IP没有绑定，也没有校验连接后的 Peer Address。

攻击主机可以：

```text
第一次解析 → 公网允许地址
第二次解析 → 127.0.0.1 / 私网 / 元数据地址
```

### 修复原则

必须满足以下任一可靠方案：

#### 方案 A：连接固定到已校验 IP

- 使用校验阶段返回的 IP；
- 保留原 Host Header；
- HTTPS 保留原 SNI 和证书校验；
- 重定向每一跳重新校验并重新 Pin。

#### 方案 B：连接后校验 Peer Address

- 获取实际网络流的服务器地址；
- 与校验结果及项目策略比较；
- 不匹配立即拒绝；
- IPv4/IPv6 都覆盖；
- 代理关闭；
- 不依赖不稳定的未公开 HTTPX 行为。

方案必须由安全回归测试证明，不能只增加第二次 DNS 校验。

### 回归测试

1. 校验解析为公网，实际连接为 loopback，必须拒绝。
2. 实际连接为 link-local，必须拒绝。
3. 实际连接为未授权私网，必须拒绝。
4. 实际连接不在第一次解析集合，必须拒绝。
5. Redirect 每一跳都执行相同保护。
6. Swagger UI Script、Config URL 和最终文档 URL 都受保护。
7. IPv4 与 IPv6。
8. Standalone 关闭严格策略时仍不得访问元数据地址。
9. 合法公网导入不回归。
10. 合法白名单私网导入不回归。

## 2.3 P2：组织成员配额未执行

### 当前问题

`OrganizationService.upsert_member` 在新成员分支直接插入记录，没有调用：

```text
OrganizationQuotaService.enforce(
    dimension=QuotaDimension.USER_COUNT
)
```

### 最小修复

只在 `member is None` 时检查配额：

```text
existing update: 不增加 usage
new member: increment = 1
```

### 并发要求

简单“先计数、后插入”存在并发超限风险。至少需要：

- PostgreSQL 对 Organization Governance/Quota 取得事务锁；或
- 使用组织维度 Advisory Lock；或
- 使用可证明等价的原子策略。

Standalone 单进程不能代替 PostgreSQL 并发语义验证。

### 回归测试

1. 达到 Hard Limit 后新增成员返回 429。
2. 更新已有成员角色不消耗新增额度。
3. 删除成员后可以重新添加。
4. 两个并发新增不能同时越过限制。
5. Viewer 不可管理成员。
6. 审计只记录成功写入。

## 2.4 P2：Standalone 0044 → 0045 升级不完整

### 当前问题

当前 Standalone Baseline 为：

```text
20260823_0045
```

但 Revision 推进列表只包含到：

```text
20260823_0043
```

`semantic_gap_waivers` 在 0045 新增：

```text
revision
supersedes_waiver_id
```

现有 `_ensure_change_regression_tables` 只执行 `CREATE TABLE IF NOT EXISTS`，不能为已有表增加列。

### 修复要求

1. 将 0044 加入可升级 Revision。
2. 对 `semantic_gap_waivers` 执行显式列检查。
3. 安全添加 `revision`，默认 1。
4. 安全添加 `supersedes_waiver_id`。
5. 补充索引和唯一约束兼容策略。
6. Existing Rows 不丢失。
7. 将 Standalone Meta 和 Alembic Version 推进到当前 Head。
8. Upgrade 可重复执行。

### 回归测试

构造真实 SQLite Fixture：

```text
Revision = 0044
semantic_gap_waivers 已存在
包含至少一条历史 Waiver
缺少 revision / supersedes_waiver_id
```

验证：

```text
启动当前版本
→ Schema 补齐
→ 历史记录保留
→ 查询成功
→ 新增 Waiver 成功
→ Supersede 成功
→ 再次启动幂等
→ Backup / Restore 可用
```

## 2.5 H0 退出条件

```text
P1_OPEN = 0
P2_OPEN = 0 或有明确接受记录
Backend CI = PASS
Security CI = PASS
Standalone Upgrade Fixture = PASS
Compose Smoke = PASS
Review Threads = RESOLVED
main Protection = ENABLED
Old PRs #38/#39 = CLOSED AS SUPERSEDED
```

H0 完成后的 `main` SHA 才是 V6 正式 Baseline。

---

# 3. 原 V6 方案需要修改的核心内容

## 3.1 保留不变的方向

以下方向正确，应继续保留：

1. V6 定位为 Visual AI Integration Test Engineer。
2. 外部 LLM 作为代码 MCP、数据库 MCP 和 FlowTest MCP 的编排器。
3. FlowTest 负责确定性校验、权限、编译、审核、执行和审计。
4. FlowSpec 作为可移植流程 IR。
5. MCP 只能创建 Draft，不能自动 Publish。
6. 标准路径 Visual First。
7. Evidence First。
8. Sandbox Preview。
9. Secret Ref 和 PII Redaction。
10. Change-aware Test Selection。
11. Skills 产品化。
12. Standalone、Compact、Full 保持同一核心语义。

## 3.2 必须修改的部分

### 修改一：V6 不能直接从当前 main 全面开工

原方案中的“V5 已合并即可创建 V6 分支”不够。

必须增加 H0：

```text
V5 Post-Merge Correctness Hotfix
```

### 修改二：不新建平行 FlowProposal 生命周期

原方案计划新增：

```text
flow_proposals
flow_proposal_reviews
```

当前代码已经有：

```text
AIChangeSet
AIChangeItem
FlowSpecService.create_import
FlowSpecService.review
FlowSpecService.apply
target_snapshot_sha256
target_revision
FlowSpec fingerprint
```

因此 V6.0 应：

```text
FlowProposal = AIChangeSet + AIChangeItem + Typed Source Snapshot 的产品视图
```

而不是建立第二套：

```text
Draft
Review
Apply
Stale
Audit
```

生命周期。

### 修改三：Built-in Java Provider 不应阻断第一条 V6 用户链路

原方案顺序为：

```text
Context
→ Java Provider
→ Graph
→ Planner
→ Compiler
→ MCP Draft
```

这会导致多个基础迭代后才出现用户可见价值。

原始目标本来就允许用户自行安装 Code MCP 和 Database MCP，因此更合理顺序是：

```text
Context / Evidence Envelope
→ Contract-based Multi-Operation Plan
→ FlowSpec Compiler
→ MCP Flow Draft
→ Visual Review
→ 再增强 Java Provider / State Graph
```

V6.0 必须先证明：

> 外部 LLM 提交标准 Evidence 后，FlowTest 能生成可视化 Flow Draft。

Built-in Java/Spring Provider 作为 V6.1 或并行增强，不阻断 Alpha。

### 修改四：不能默认假设 FlowSpec 顶层语义已经可执行

当前 FlowSpec 虽然定义：

```text
bindings
assertions
cleanup
synthetic_data
secret_ref
security_policy
```

但当前转换到 Workflow 时：

- 全局 Bindings 被判为 Unsupported；
- 全局 Assertions 被判为 Unsupported；
- Cleanup 被判为 Unsupported；
- Synthetic / Secret Parameter Source 被判为 Unsupported；
- 非默认 Security Policy 被判为 Unsupported。

V6 Compiler 必须：

```text
Binding → Edge FieldMapping
Assertion → Assert Node
Data → Dataset / Variables / Setup API / Existing Secret Mechanism
Preview Budget → Proposal / Preview Sidecar
```

不能只填充 FlowSpec 顶层字段后声称可执行。

### 修改五：Cleanup 需要执行引擎新语义

当前 Scheduler 在失败且 `fail_fast=true` 时：

```text
取消 Active Nodes
将 Remaining Nodes 标为 Cancelled
结束执行
```

因此将 Cleanup API 放在普通下游节点不能保证失败或取消后执行。

V6.0 必须新增：

- Main Phase；
- Cleanup / Compensation Phase；
- Bounded Cleanup；
- Graceful Cancel；
- Force Cancel；
- Cleanup Result；
- Cleanup Failure；
- 主测试结果与清理结果分离。

这不是 UI 功能，而是核心执行语义。

### 修改六：Context / Graph 初期不要建过多表

原方案一次规划了十余张新表。

V6.0 建议最小化为：

```text
test_contexts
test_context_revisions
context_evidence_items
preview_approvals
preview_runs
```

以下内容先保存为版本化、类型化 JSON Snapshot：

```text
IntegrationTestPlan
KnowledgeSnapshot
Node/Edge Evidence
Compiler Diagnostics
```

达到明确查询和容量瓶颈后，再将 Graph Node/Edge 规范化为独立表。

### 修改七：UI 复用现有 WorkflowDesigner

原方案不应再开发第二套 React Flow Canvas。

建议：

```text
WorkflowDesigner
+ proposalMode
+ ghostDiff
+ evidenceOverlay
+ reviewActions
+ previewOverlay
```

`FlowSpecReviewDialog` 保留为高级 Raw JSON / Mapping 模式。

### 修改八：Key Rotation 不能留到最后

H1 启动前，真实 Key Rotation 仍未实现。

V6 会新增：

- Context Evidence；
- Proposal Snapshot；
- Preview Plan；
- 可能包含敏感业务元数据的 Artifact。

因此 Key Rotation 必须作为并行 H1 Track，在 Sandbox Preview 之前完成，而不是只作为最终 GA Checklist。

### 修改九：Skill 数量不应阻断核心能力

V6.0 只要求一个旗舰 Skill：

```text
flowtest-generate-integration-flow
```

其他 Skill 在核心 MCP Contract 稳定后进入 V6.1/V6.2。

### 修改十：准确率指标先建立基线，再设发布门槛

诸如：

```text
Operation Mapping ≥ 95%
Binding Accuracy ≥ 90%
```

必须在 Golden Set 定义、标注和统计方法固定后再作为 Release Gate。

V6.0 初期硬门槛应是：

```text
Static Validation = 100%
Secret Leak = 0
Cross-Tenant = 0
Unreviewed Apply = 0
Stale Overwrite = 0
Production MCP Preview = 0
```

---

# 4. 优化后的产品版本列车

原方案把所有能力放入一个超大的 V6.0，范围过宽。

优化为：

| 版本 | 目标 | 核心交付 |
| --- | --- | --- |
| V5.0.1 / H0 | 修复合并后正确性与安全问题 | 2 P1、2 P2、仓库治理 |
| V6.0 Core | 外部 LLM 能生成并预览可视化集成测试 | Context、Plan、Compiler、MCP Draft、Visual Review、Data/Oracle、Cleanup、Preview、1 个 Skill |
| V6.1 Intelligence | 提高代码和业务语义理解 | Java/Spring Provider、Entity/State Graph、Advanced Oracle、Repair |
| V6.2 Continuous QA | 持续维护测试资产 | Change Maintenance、完整 Skills、Provider 扩展、质量趋势 |

这样可以：

1. 更早交付用户价值。
2. 降低一次性 Migration 风险。
3. 先验证外部 LLM + MCP 交互是否有效。
4. 避免先建设大而全 Knowledge Graph。
5. 避免 V6 重复 V5 的超大 PR 模式。
6. 使 Alpha 在 S51，而不是原方案的 S54 之后。

---

# 5. V6.0 Core 产品定义

## 5.1 一句话定义

> 外部 LLM 通过 Code MCP、Database MCP 和 FlowTest MCP 获取授权证据，FlowTest 将证据确定性编译成可审核、可预览、可执行的多接口可视化集成测试流程。

## 5.2 V6.0 必须闭环

```text
User Intent
→ Context Revision
→ Typed Evidence
→ Integration Test Plan
→ Executable FlowSpec
→ AIChangeSet Draft
→ WorkflowDesigner Proposal Mode
→ Human Review
→ Sandbox Preview
→ Apply Workflow Draft
```

## 5.3 V6.0 P0

1. Context Revision。
2. External Evidence Envelope。
3. Multi-Operation Integration Plan。
4. Plan → Executable FlowSpec。
5. MCP `propose_flow_draft`。
6. 可视化 Proposal Review。
7. Edge Mapping。
8. Assert Node。
9. Data Recipe 基础。
10. Cleanup / Compensation Runtime。
11. Sandbox Preview。
12. 一个正式 Skill。
13. Golden Evaluation。
14. Backward Compatibility。
15. Security、Migration、Standalone、Compact、Full 门禁。

## 5.4 V6.0 明确不做

1. FlowTest Server 主动连接任意第三方 MCP。
2. 自动 Publish。
3. 自动生产执行。
4. 任意脚本。
5. 数据库写 SQL。
6. 完整 Java 编译级分析。
7. 图数据库。
8. 多 Agent。
9. Provider Marketplace。
10. 自动修改源码。
11. 自动 Repair。
12. 全量 Change Maintenance。
13. 五个 Skill 同时完成。

---

# 6. 复用现有代码而不是重新建设

## 6.1 Proposal 生命周期

复用：

```text
AIChangeSet
AIChangeItem
FlowSpecService
```

V6 MCP Flow Proposal 建议写入：

```text
AIChangeSet.source_type = "flow_spec"
AIChangeSet.actor_type = "service_account"
AIChangeSet.source_ref = "mcp://..."
AIChangeItem.item_type = "workflow"
```

`source_snapshot` 增加版本化结构：

```json
{
  "schema_version": "v6-flow-proposal-source-v1",
  "context_revision_id": "uuid",
  "context_fingerprint": "sha256",
  "integration_plan": {},
  "plan_fingerprint": "sha256",
  "node_evidence": {},
  "edge_evidence": {},
  "compiler_version": "6.0",
  "preview_policy": {}
}
```

现有 FlowSpec Service 继续负责：

- Normalize；
- Validate；
- Mapping；
- Review；
- Target Revision；
- Target Snapshot；
- Apply；
- Audit。

## 6.2 Test Engineering

当前单 API Test Engineering 不删除，也不强行改造成整个 V6 Planner。

V6 Planner 可以复用它生成：

- 单 Operation 边界 Scenario；
- 单 Operation Oracle；
- Contract Coverage；
- Negative Case。

然后将结果作为多 Operation Plan 的局部 Scenario。

## 6.3 Change Regression

复用：

- `OperationIdentity`
- `SemanticCoverageFact`
- Contract Fingerprint
- Existing Test Coverage
- Current TestPlan Scope
- Change Constraint

V6.0 不再建立另一套 Operation Identity。

## 6.4 WorkflowDesigner

新增：

```text
mode = edit | runtime | proposal
```

Proposal Mode：

- 只读候选图；
- Ghost Diff；
- Node/Edge Evidence；
- Accept / Reject；
- Mapping 编辑；
- Preview Overlay。

## 6.5 Execution

Sandbox Preview 复用现有 Workflow Snapshot、Scheduler、Worker、Runner、Event 和 Report。

只新增：

```text
run_purpose = preview
source_change_set_id
preview_approval_id
budget
```

不建立第二套 Preview Engine。

---

# 7. Context 与 Evidence 最小设计

## 7.1 TestContext

```text
id
organization_id
project_id
name
objective
target_environment_id
status
current_revision
created_by_type
created_by_id
expires_at
created_at
updated_at
```

状态：

```text
collecting
ready
incomplete
conflicted
expired
closed
```

## 7.2 TestContextRevision

```text
id
context_id
revision
repository_revisions
contract_revisions
data_profile_revisions
existing_test_revision
knowledge_snapshot
completeness
fingerprint
created_at
```

Revision 一旦创建不可原地修改。

## 7.3 ContextEvidenceItem

```text
id
context_revision_id
source_type
provider_name
provider_version
source_ref
source_revision
subject_ref
finding_payload
semantic_role
deterministic
confidence
fingerprint
redactions
warnings
created_at
expires_at
```

## 7.4 不在 V6.0 新建的表

暂不新建：

```text
provider_runs
evidence_conflicts
operation_graph_nodes
operation_graph_edges
integration_test_plans
flow_proposals
flow_proposal_reviews
skill_run_records
```

理由：

- Provider 元数据可先进入 Evidence Item 和 Audit；
- Conflict 可在 Revision Snapshot 中保存；
- Graph 可先保存 Typed Snapshot；
- Plan 可进入 ChangeSet Source Snapshot；
- Flow Proposal 复用 AIChangeSet；
- Skill Run 可先用 Audit + Trace。

## 7.5 Evidence Envelope

外部 LLM 提交的是 Typed Claims，不是无界原始代码或数据库行。

```json
{
  "schema_version": "flowtest-external-evidence-v1",
  "provider": {
    "type": "code_mcp",
    "name": "example-code-mcp",
    "version": "1.2.0"
  },
  "source": {
    "ref": "repository://owner/repo",
    "revision": "commit-sha"
  },
  "subject_ref": "operation://order.create",
  "findings": [],
  "redactions": [],
  "warnings": []
}
```

## 7.6 Evidence 安全

拒绝：

- Bearer Token；
- Cookie；
- Password；
- API Key；
- Connection String；
- PEM；
- 原始 PII；
- 任意 Prompt Instruction 字段；
- 无界文件内容；
- 无 Revision 来源；
- 跨租户资源引用。

代码注释、接口说明和数据库 Comment 一律作为不可信数据。

---

# 8. Integration Test Plan

## 8.1 Schema

```text
flowtest-integration-plan-v1
```

## 8.2 输入

```text
context_revision_id
objective
target_environment
preferred_operations
excluded_operations
coverage_policy
data_policy
cleanup_policy
request_budget
```

## 8.3 输出

```text
actors
preconditions
steps
branches
bindings
data_recipes
oracles
cleanup_plan
coverage_targets
unresolved_items
confidence
evidence_refs
```

## 8.4 Planner V6.0 能力

V6.0 首批支持：

1. 用户显式选择 Operation。
2. 根据 Request/Response 字段匹配建立候选 Binding。
3. 根据 Existing Workflow 识别可复用 Auth/SubFlow。
4. 根据 Contract 生成正常和负面局部 Scenario。
5. 根据 Operation 方法和明确 Evidence 推断 Create/Query/Update。
6. 根据外部 Evidence 使用 Entity/State Claim。
7. 生成 Cleanup Requirement。
8. 生成可执行性和 Missing Evidence。
9. 生成多个候选 Plan，但不自动选择低置信度结果。

## 8.5 Planner V6.0 不做

- 无证据推断完整业务状态机；
- 从整个代码库自动构建完整调用图；
- 自动写数据库；
- 任意 Function Calling；
- 自动执行；
- 自动发布。

## 8.6 Binding

来源：

```text
previous_response
runtime_variable
environment_variable
dataset
secret_reference
setup_api
external_evidence_candidate
```

目标：

```text
path
query
header
cookie
body
workflow_variable
```

V6.0 必须支持：

- 完全同型自动绑定；
- 安全模板转换；
- 多候选人工选择；
- Secret 值禁止普通绑定；
- Object/Scalar 冲突阻断；
- String/Number 转换默认需 Review。

---

# 9. FlowSpec Compiler

## 9.1 Compiler 定位

```text
IntegrationTestPlan
→ Portable FlowSpec
→ Existing FlowSpec Pipeline
```

Compiler 是纯领域代码，不：

- 持久化；
- 访问网络；
- 访问 Secret；
- 执行 API；
- 直接创建 Workflow。

## 9.2 V6.0 可执行编译规则

| Plan 语义 | 编译结果 |
| --- | --- |
| Operation Step | API Node |
| Response Extraction | Extract Node 或 Edge Mapping Source |
| Field Binding | `WorkflowEdge.mappings` |
| Status / Schema / Field Oracle | Assert Node |
| Branch | Condition Node + Condition Edge |
| Dataset | Dataset Node |
| DB Read Oracle | SQL Read Node + Assert Node |
| Delay / Poll | Delay + Condition/Loop 或受控 Capability |
| Existing Auth Flow | SubFlow |
| Secret | Existing Credential / Secret Reference Mechanism |
| Data Setup | API Node / Dataset |
| Cleanup | Cleanup Runtime Phase，不是普通下游节点 |

## 9.3 FlowSpec v1 / v2 决策

V6 不创建第二套 DSL。

S48 必须通过 ADR 确定：

### 保持 v1 的条件

- 新 Cleanup/Run Policy 可以作为向后兼容可选字段；
- 现有 v1 Import/Export 不受影响；
- Fingerprint 能正确包含新语义；
- 外部消费者不会因 `extra=forbid` 被破坏。

### 升级 v2 的条件

任一条件不满足时：

```text
flowtest-flow-spec-v2
```

并要求：

1. v1 继续可导入。
2. v1 → v2 确定性转换。
3. v2 Fingerprint 新版本。
4. Existing Workflow 导出可选择 v1/v2 或默认 v2。
5. Upgrade 不修改历史 Execution Snapshot。
6. 明确兼容矩阵。

## 9.4 Compiler Pass

```text
Normalize
Resolve Operations
Resolve Resources
Build Main Graph
Compile Edge Mappings
Compile Data
Compile Assert Nodes
Compile Cleanup Plan
Compile Security / Preview Sidecar
Validate
Fingerprint
Diff
```

## 9.5 不进入 FlowSpec Fingerprint 的内容

- LLM 名称；
- Prompt；
- Provider 名称；
- Context UUID；
- Evidence 展示文案；
- Review 状态；
- Preview 状态。

进入 Fingerprint 的内容：

- Operation Identity；
- Node/Edge；
- Mapping；
- Assert；
- Cleanup Execution Semantics；
- Runtime-relevant Settings；
- Version Strategy；
- Contract Fingerprint。

---

# 10. Cleanup / Compensation Runtime

## 10.1 为什么是 P0

业务集成测试会创建订单、支付记录、临时用户、Mock 数据。

没有失败和取消清理：

- Preview 会污染测试环境；
- 自动生成的流程不可重复；
- 数据库 Oracle 会越来越不稳定；
- LLM 生成的流程风险不可接受。

## 10.2 建议模型

Workflow Node 增加通用执行元数据：

```text
phase: main | cleanup
run_when: success | failure | cancel | always
cleanup_for: [node_id]
best_effort: bool
```

默认：

```text
phase = main
```

因此现有 Workflow 完全兼容。

## 10.3 Scheduler 语义

```text
执行 Main DAG
→ 固定 Main Result
→ 计算已激活 Cleanup Steps
→ 使用独立、有界 Cleanup Token
→ 执行 Cleanup DAG
→ 汇总 Main Result + Cleanup Result
```

规则：

1. Main Failure 不能因 Cleanup 成功变为 Passed。
2. Main Passed + Required Cleanup Failed，整体至少为 Failed 或 Passed-With-Cleanup-Failure，需 ADR 固定。
3. Best Effort Cleanup Failure 不静默，进入 Warning 和 Report。
4. 用户普通 Cancel 进入 Graceful Cleanup。
5. Force Cancel 可以跳过 Cleanup，但必须明显审计。
6. Cleanup 不能触发无限 Retry。
7. Cleanup 有独立 Timeout 和 Request Budget。
8. Cleanup Snapshot 固定。
9. Cleanup 节点不可作为普通业务输出依赖。
10. Cleanup 结果进入 Preview Evidence。

## 10.4 测试

- Main Passed / Cleanup Passed；
- Main Failed / Cleanup Passed；
- Main Failed / Cleanup Failed；
- Cancel / Cleanup；
- Force Cancel；
- Parallel Side Effects；
- Cleanup Ordering；
- Retry；
- Resume；
- Runner Reclaim；
- Standalone；
- Compact；
- Full；
- Snapshot Replay。

---

# 11. MCP V6.0

## 11.1 现有能力继续保留

```text
list_projects
inspect_project
discover_services
inspect_contract
inspect_flow
inspect_run_evidence
inspect_source_evidence
inspect_data_profile
generate_test_design
analyze_test_coverage
inspect_change_impact
validate_flowspec
diff_flowspec
export_flowspec
propose_test_design
```

## 11.2 V6.0 新增 Tools

### Context

```text
flowtest.begin_test_context
flowtest.inspect_context_requirements
flowtest.ingest_external_evidence
flowtest.inspect_test_context
flowtest.close_test_context
```

### Plan / Compile

```text
flowtest.plan_integration_test
flowtest.validate_integration_plan
flowtest.compile_integration_flowspec
flowtest.explain_compiler_diagnostics
```

### Flow Draft

```text
flowtest.propose_flow_draft
flowtest.inspect_flow_proposal
```

### Preview

```text
flowtest.request_preview
flowtest.inspect_preview_evidence
```

## 11.3 Scope

V6.0 首批只增加：

```text
mcp:evidence:write
mcp:flow:propose
mcp:preview:execute
```

保留：

```text
mcp:read
mcp:write
```

但：

> 现有 `mcp:write` 不得自动获得新 Scope。

V6.1 再增加：

```text
mcp:repair:propose
mcp:test-plan:propose
```

## 11.4 propose_flow_draft

内部复用：

```text
FlowSpecService.create_import
```

差异：

- Actor Type 为 Service Account；
- Source Ref 为 `mcp://...`；
- 保存 Context Revision；
- 保存 Integration Plan；
- 默认 `dry_run=true`；
- 必须有 Idempotency Key；
- Patch 必须有 Expected Revision；
- 只创建 ChangeSet Draft。

## 11.5 V6 不提供

```text
publish_flow
execute_production_flow
delete_workflow
read_secret
create_credential
run_arbitrary_sql
run_script
grant_scope
```

---

# 12. Visual Proposal Review

## 12.1 不创建第二套画布

复用：

```text
frontend/src/flow/WorkflowDesigner.tsx
```

新增 Proposal Mode。

## 12.2 Proposal Mode

显示：

- Existing Graph；
- Proposed Graph；
- Added Node；
- Modified Node；
- Removed Node；
- Rewired Edge；
- Mapping Change；
- Assert Change；
- Cleanup Change；
- Evidence；
- Confidence；
- Unresolved；
- Preview Status。

## 12.3 页面结构

### 左侧

- Context；
- Objective；
- Contract Revision；
- Evidence Sources；
- Missing Evidence；
- Conflict；
- Coverage。

### 中间

- WorkflowDesigner Proposal Mode；
- Service Swimlane；
- Ghost Diff；
- State / Coverage Overlay。

### 右侧

- Node Config；
- Binding；
- Data；
- Oracle；
- Cleanup；
- Evidence；
- Review Actions。

## 12.4 FlowSpecReviewDialog

继续保留为：

- Raw JSON；
- Cross-instance Mapping；
- Advanced Validate；
- Advanced Diff。

不作为普通用户的 AI Flow 主路径。

---

# 13. Data Recipe 与 Oracle

## 13.1 V6.0 Data Source

```text
synthetic
approved_dataset
previous_step
environment_variable
secret_reference
setup_api
existing_safe_record
database_observation
```

## 13.2 数据原则

1. 不生成固定生产 ID。
2. 不把 PII 写入 FlowSpec。
3. Secret 只引用。
4. 默认使用 API Setup，不使用写 SQL。
5. Database MCP 只提供设计期 Evidence。
6. Runtime DB 校验使用既有只读 SQL Node。
7. Data Recipe 必须有来源和 Evidence。
8. 有副作用必须有 Cleanup。

## 13.3 V6.0 Oracle

### 协议

- Status；
- Header；
- Schema；
- Content-Type；
- Time。

### 字段

- JSONPath/JMESPath；
- Type；
- Required；
- Enum；
- Value；
- Collection Size。

### Cross-API

- Create ID == Query ID；
- Update Request == Query Result；
- Amount / Status 一致；
- Token Subject 一致。

### DB Read

- Row Exists；
- State；
- Amount；
- Relation；
- Cleanup Result。

### State

V6.0 只执行外部 Evidence 或 User Confirmed 明确提供的状态规则，不自动构建完整状态机。

---

# 14. Sandbox Preview

## 14.1 复用执行引擎

Preview 是：

```text
WorkflowExecution(run_purpose=preview)
```

不是新引擎。

## 14.2 前置条件

1. Proposal 已 Review Accept。
2. Environment 为 Test/Sandbox。
3. Context 未过期。
4. Target Revision 未 Stale。
5. Secret 已配置。
6. Cleanup 可执行。
7. Budget 明确。
8. 一次性 Approval。
9. Scope 满足。
10. 出站策略满足。

## 14.3 默认预算

```text
max_nodes = 100
max_requests = 50
max_dataset_rows = 20
max_parallelism = 5
max_runtime_seconds = 600
```

正式值由基准测试确认。

## 14.4 硬拒绝

- Production Environment；
- Approval 重放；
- Missing Cleanup；
- Unresolved Blocker；
- Secret Literal；
- Stale Proposal；
- 超预算；
- Cross-Tenant；
- Unsupported Node；
- Arbitrary Script。

## 14.5 Preview Evidence

- Proposal Fingerprint；
- Context Fingerprint；
- Execution Snapshot；
- Binding Trace；
- Assert Result；
- Cleanup Result；
- Budget Usage；
- Redactions；
- Trace ID；
- Approval ID。

---

# 15. External Evidence Adapter 与 Java/Spring

## 15.1 V6.0 主模式

```text
External LLM
  ├── Code MCP
  ├── Database MCP
  └── FlowTest MCP
```

FlowTest 接收标准 Evidence，不要求内置所有语言 Parser。

## 15.2 V6.0 必须支持的 Java Evidence

即使没有内置 Parser，Evidence Contract 必须能表达：

- Controller Route；
- DTO Field；
- Validation；
- Service Call；
- Feign Call；
- Mapper/Repository；
- Table/Column；
- Enum/State；
- Exception；
- Kafka Event。

## 15.3 Built-in Java Provider

移至 V6.1，或作为并行但不阻断 Core 的工作。

代码仓库已经有若依本地测试目标，可作为：

- Java/Spring Golden Project；
- MySQL Golden Profile；
- Login / CRUD / Permission Flow；
- Compose E2E。

CI 仍应使用更小的固定 Java Fixture，避免每次单元测试构建完整若依。

---

# 16. Skills

## 16.1 V6.0 旗舰 Skill

```text
flowtest-generate-integration-flow
```

步骤：

```text
选择项目
→ 创建 Context
→ 检查 Missing Evidence
→ 调用 Code/DB MCP
→ Ingest Evidence
→ Plan
→ Compile
→ Dry Run
→ Propose Draft
→ 提示用户进入 Visual Review
```

## 16.2 V6.1/V6.2 Skill

```text
flowtest-project-onboarding
flowtest-complete-coverage
flowtest-change-aware-regression
flowtest-triage-and-repair
```

## 16.3 Skill 要求

- Manifest；
- Version；
- MCP Minimum Version；
- Required Tools；
- Required Scopes；
- Human Approval；
- Stop Conditions；
- Security Rules；
- Examples；
- Golden Eval；
- Changelog。

---

# 17. Parallel Hardening Tracks

V6 功能开发可以与 V5 发布验证并行，但不能忽略。

## H1：真实 Key Rotation

> 实施状态（2026-08-30）：已在 H1 独立阶段完成事务性 Re-encrypt/Verify/Activate/Rollback/Audit，
> 覆盖当前已持久化的 Secret、本地 Credential、Encrypted Execution Plan、Import Preview 和 Webhook Secret。
> Full/Compact/Standalone 共享同一套密文包络和密钥引用语义，Backup/Restore 保留引用并要求独立恢复密钥环。
> S55 新增任何需要加密的 Preview 持久化数据必须复用活动组织密钥解析器。

必须在 Sandbox Preview 前完成：

```text
Create New Key Version
→ Re-encrypt
→ Verify
→ Activate
→ Rollback
→ Audit
```

覆盖：

- Secret；
- Credential；
- Encrypted Execution Plan；
- 新增 Context/Preview 中需要加密的数据；
- Standalone；
- Compact；
- Full；
- Backup/Restore。

## H2：外部运行证据

V6.0 GA 前：

1. Windows 公司云桌面实机。
2. Standalone 长时运行。
3. Compact 长时运行。
4. Standalone → Compact 迁移。
5. Backup / Restore。
6. Upgrade / Rollback。
7. 连续 RC。
8. Security Review。
9. Production Authorization Review。
10. 人工签署。

---

# 18. 优化后的迭代路线

## 18.1 版本映射

| 阶段 | 迭代 | 版本 |
| --- | --- | --- |
| Hotfix | H0 | V5.0.1 |
| Core | S48～S56 | V6.0 |
| Intelligence | S57～S58 | V6.1 |
| Continuous QA | S59～S60 | V6.2 |

---

## S48 — V6 Contract Freeze、Golden Set 与 Repository Governance

### 前置

H0 已合并。

### 目标

固定 V6 核心契约，不增加大规模运行功能。

### 交付

1. 记录正式 V6 Baseline SHA。
2. 提交 `docs/development-plan-v6.md`。
3. ADR：
   - External LLM Orchestration；
   - Context Revision；
   - Proposal Reuse；
   - Integration Plan；
   - FlowSpec v1/v2；
   - Cleanup Runtime；
   - Preview Security。
4. 固定现有 FlowSpec v1/v3 Golden。
5. 固定 AIChangeSet Lifecycle Golden。
6. 固定 MCP Existing Contract。
7. 创建 Golden Project：
   - Small Contract Fixture；
   - Small Java Fixture；
   - RuoYi Full Target；
   - DB Profile Fixture。
8. 定义 Eval 标注方法。
9. V6 Feature Flag 只为即将开发的功能创建，不一次创建全部空 Flag。

### 验收

```text
V6_BASELINE_FROZEN
P1_OPEN = 0
P2_OPEN = 0
MAIN_PROTECTED = YES
OLD_DRAFT_PRS = CLOSED
```

---

## S49 — Context Revision、External Evidence 与 Proposal Adapter

### 目标

建立最小 Context，不建设大而全 Graph 平台。

### 后端

- TestContext；
- TestContextRevision；
- ContextEvidenceItem；
- Fingerprint；
- TTL；
- Completeness；
- Conflict Snapshot；
- External Evidence Validation；
- Audit；
- Retention；
- Data Classification。

### Proposal

增加 FlowSpec MCP Adapter，复用 FlowSpecService 和 AIChangeSet。

### MCP

```text
begin_test_context
inspect_context_requirements
ingest_external_evidence
inspect_test_context
```

### UI

- Context List；
- Context Detail；
- Evidence Summary；
- Missing Evidence；
- Conflict。

### 验收

```text
同一 Revision Fingerprint 稳定
过期 Context 不能创建 Proposal
Secret Leak = 0
Cross-Tenant = 0
```

---

## S50 — Multi-Operation Plan 与 Executable FlowSpec Compiler MVP

### 目标

只基于现有 API Contract、Service、Existing Workflow 和用户选择，完成第一条多接口编译链。

### 能力

```text
2～5 个 API Operation
→ Sequence
→ Response-to-Request Binding
→ Status/Schema/Field Assert
→ Edge Mapping
→ FlowSpec
```

### 非目标

- Java Provider；
- 完整 State Graph；
- DB Oracle；
- Cleanup Failure Runtime；
- Preview。

### 验收

Golden：

```text
Login
→ Create
→ Query
```

编译后的 FlowSpec：

- Validate = true；
- Importable = true；
- 可创建 Workflow Draft；
- Fingerprint 稳定。

---

## S51 — MCP Flow Draft 与 Visual Proposal Alpha

### 目标

首次完成用户可见闭环。

### MCP

```text
plan_integration_test
compile_integration_flowspec
propose_flow_draft
inspect_flow_proposal
```

### UI

- WorkflowDesigner Proposal Mode；
- Ghost Diff；
- Node/Edge Evidence；
- Accept / Reject；
- Apply Draft；
- Raw JSON Advanced Mode。

### Alpha 退出条件

```text
External LLM → MCP → Visual Flow Draft = YES
AUTO_PUBLISH = NO
PRODUCTION_EXECUTION = NO
```

---

## S52 — Evidence Adapter、Entity Mapping 与 Java Provider POC

### 目标

把外部 Code/DB Evidence 真正用于 Operation、Field 和 Entity Binding。

### 交付

- Java Evidence Contract；
- DB Evidence Contract；
- Operation → Entity Candidate；
- Field → Column Candidate；
- Confidence；
- Conflict；
- User Confirmed Rule；
- RuoYi POC；
- Python Provider 兼容。

### Built-in Java

只要求 POC，不阻断 V6.0。

### 验收

- External MCP Java Claim 可进入 Context；
- DB Schema Claim 可进入 Context；
- Create ID → Query Path Candidate；
- Conflict 不静默解决。

---

## S53 — Data Recipe、Cross-API Oracle 与 DB Read Oracle

### 目标

使流程不再只是接口顺序，而是可执行测试。

### 交付

- Synthetic Data；
- Dataset；
- Setup API；
- Secret Reference；
- Cross-API Assert；
- SQL Read Assert；
- Data Evidence；
- Oracle Strength；
- Design-only Blocker。

### 验收

```text
Create → Query → DB Read
```

字段、状态和数据库结果一致。

---

## S54 — Cleanup / Compensation Runtime

### 目标

在失败、取消和重试情况下可靠清理数据。

### 交付

- Workflow Contract；
- FlowSpec Contract Decision；
- Scheduler Main/Cleanup Phase；
- Graceful Cancel；
- Force Cancel；
- Cleanup Snapshot；
- Cleanup Report；
- Resume / Reclaim；
- Standalone / Compact / Full。

### 验收

正常、失败、取消、Runner 重启下 Cleanup 语义一致。

---

## S55 — Sandbox Preview Beta

### 目标

审核后的 Proposal 可以在沙箱预览。

### 交付

- Environment Classification；
- One-time Approval；
- Preview Budget；
- Preview Execution Purpose；
- Live Overlay；
- Binding Trace；
- Cleanup Result；
- Preview Evidence；
- Production Hard Reject。

### Beta 退出条件

```text
VISUAL_REVIEW = YES
SANDBOX_PREVIEW = YES
CLEANUP = YES
PRODUCTION_MCP_PREVIEW = NO
```

---

## S56 — Flagship Skill、Evaluation、Compatibility 与 V6.0 RC

### 目标

完成 V6.0 Core 发布闭环。

### 交付

- `flowtest-generate-integration-flow` Skill；
- Model-independent Eval；
- Golden Projects；
- Migration；
- Standalone；
- Compact；
- Full；
- MCP stdio / HTTP；
- Backup/Restore；
- Upgrade/Rollback；
- Security；
- Documentation；
- Alpha → Beta → RC 证据。

### V6.0 RC 门槛

- H0 完成；
- H1 Key Rotation 完成；
- Core Gate 全绿；
- 无 P0/P1；
- Preview 生产硬拒绝；
- FlowSpec/Workflow Compatibility；
- Skill Contract Test。

### S56 实现与证据入口

- Flagship Skill：`skills/flowtest-generate-integration-flow/`；
- Model-independent Eval：`scripts/evaluate_v6_core.py` 与 `backend/tests/fixtures/v6_golden/evaluation-baseline.json`；
- 使用手册：`docs/operations/mcp-integration-flow-skill.md`；
- RC Evidence：`docs/release/v6-core-rc-acceptance.md`。

Operation/Binding Precision 只报告 Golden Set 的精确分子与分母，不在无统计依据时补写 95%/90% 发布
阈值。普通 PR 运行核心路径门禁；Compact 与容量 RC 重门禁在最新复审无 P0/P1 后显式触发。

### V6.0 GA 门槛

- H2 外部证据完成；
- 连续 RC；
- 安全审批；
- 实机；
- 人工签署。

---

## S57.0 — V6.1 Foundation Correctness 与 Accepted P2 Closure

### 目标

在扩展 Java Provider、State Knowledge 和 Repair 之前，关闭会被后续自动化复制或放大的基础正确性
债务。

### 已完成范围

- Planner / Compiler / Data：对象型 JSON Body、Path/Cookie、变量唯一性、DB Read 来源、Plan v1
  `setup_api` 兼容；
- Java Evidence：Jackson 默认可见性、普通 `@Controller` Response Body 语义、JPA 结构字段独立性；
- Governance / Evaluation / Skill：授权早于 Idempotency Claim、硬门禁使用未舍入比例、Preview 前
  重新确认 Proposal 已接受且未 Apply。

### 分阶段门槛

- PR #71、#72、#73 均已普通 Squash Merge；
- 最终复审 P0=`0`、P1=`0`；
- Context Inspector UI 是 S57 退出条件；
- Skill 自包含 Evaluation Assets 最迟在 S60 完成；
- 复审新增 P2 独立记账，不重新计入原 12 项。

---

## S57 — Built-in Java/Spring Provider 与 State Knowledge（V6.1）

### 目标

提升无需外部 LLM 手工整理 Evidence 的自动化程度。

### 支持

- Spring MVC；
- Bean Validation；
- Feign；
- MyBatis；
- JPA；
- Enum；
- Exception；
- Kafka；
- State Candidate。

### 验收

RuoYi Golden：

```text
Route → DTO → Service → Mapper/Entity → Table
```

可追溯、无代码执行。

同时交付面向用户的 Context Inspector，展示 Revision、Evidence Summary、Missing Evidence、Conflict、
State Candidate、Provider Finding 与关联 Flow Proposal。S57 不新建平行 Proposal 生命周期。

---

## S58 — Failure Diagnosis 与 Repair Proposal（V6.1）

### 目标

形成测试侧安全修复闭环。

### 交付

- Repair Proposal；
- Binding/Data/Cleanup Repair；
- Contract Drift Repair；
- Oracle Weakening；
- Product Defect Guard；
- Re-preview；
- AIChangeSet Patch。

### 硬门槛

Product Defect 不自动修改测试。

---

## S59 — Change-aware Continuous Maintenance（V6.2）

### 目标

代码、契约和数据库变化驱动 Flow Patch 和 TestPlan 建议。

### 交付

- Context Diff；
- Knowledge Diff；
- Affected Flow；
- Patch Proposal；
- Current TestPlan Gap；
- CI Summary；
- Release Gate Integration。

---

## S60 — Full Skills、Provider Extension 与 Continuous QA（V6.2）

### 目标

补齐完整 Skill 体系和可持续质量运营。

### Skill

```text
flowtest-project-onboarding
flowtest-complete-coverage
flowtest-change-aware-regression
flowtest-triage-and-repair
```

### 后续评估

- Provider Marketplace；
- Server-side MCP Federation；
- Additional Languages；
- Property Testing；
- Traffic Record → FlowSpec。

这些能力不自动进入 P0。

---

# 19. 分支与 PR 策略

## 19.1 Branch

H0：

```text
codex/v5-post-merge-hotfix
```

V6：

```text
codex/v6-s48-contract-foundation
codex/v6-s49-context-evidence
codex/v6-s50-plan-compiler
...
```

不建议再次使用一个持续数万行变更的单一长期 PR。

## 19.2 PR Gate

`main` 必须：

1. Require Pull Request。
2. Require Conversation Resolution。
3. Require Backend CI。
4. Require Frontend CI。
5. Require Security CI。
6. Require Compose Smoke。
7. Require Standalone Windows。
8. Require Upgrade/Rollback。
9. 禁止 Force Push。
10. 禁止 Branch Delete。
11. 最少一项人工确认或 Owner Merge。
12. Draft 不可合并。

## 19.3 PR 大小

建议：

- Domain Contract 与 Migration 分离但保持顺序；
- UI 与 Backend Contract 可分 PR；
- 单 PR 尽量不再次达到数百文件；
- Refactor 和 Feature 分开；
- 先 Characterization Test；
- 每个 PR 写明 Non-goal 和 Rollback。

---

# 20. Migration 与兼容

## 20.1 迁移起点

V6 正式起点不是硬编码的 `0045`，而是 H0 完成后的最终 Head。

S48 记录：

```text
V6_BASELINE_MIGRATION_HEAD
```

## 20.2 兼容

必须保持：

- V5 FlowSpec Import；
- V5 Fingerprint 验证；
- V5 Workflow Draft；
- V5 Published Workflow；
- V5 Execution Snapshot；
- V5 TestCase/Suite/Plan；
- V5 MCP Read Tools；
- Standalone Transfer；
- Compact/Full Database。

## 20.3 新数据分类

每个 V6 新字段必须标记：

```text
Public Metadata
Internal Metadata
Sensitive Business Metadata
Secret
PII
Execution Evidence
Audit
```

并明确：

- Encryption；
- Rotation；
- Retention；
- Backup；
- Export；
- Support Bundle；
- Redaction。

---

# 21. 测试策略

## 21.1 H0

- Authorization；
- DNS Rebinding；
- Quota Concurrency；
- Standalone 0044 Upgrade。

## 21.2 Domain

- Context Fingerprint；
- Evidence Normalize；
- Plan Normalize；
- Compiler Determinism；
- Mapping Type；
- Oracle Strength；
- Cleanup State；
- Proposal Stale；
- Preview Approval。

## 21.3 Property

- Normalize 幂等；
- Fingerprint 稳定；
- Diff；
- Binding；
- Cleanup 不改变 Main Result；
- Repair 不弱化 Oracle。

## 21.4 Security

- Prompt Injection；
- Source Comment Injection；
- DB Comment Injection；
- Secret；
- PII；
- SSRF；
- DNS Rebinding；
- Cross-Tenant；
- Scope；
- Approval Replay；
- Production Preview；
- Stale Revision。

## 21.5 E2E

### V6.0 Core Golden

```text
Login
→ Create
→ Query
→ Cross-API Assert
→ DB Read Assert
→ Cleanup
→ Preview
→ Apply Draft
```

### Java Golden

- Small Static Fixture；
- RuoYi Full Target。

### Runtime

- Standalone；
- Compact；
- Full；
- Worker Restart；
- Runner Reclaim；
- Cancel；
- Cleanup；
- Upgrade；
- Backup/Restore。

---

# 22. 指标与发布门槛

## 22.1 第一阶段先建立 Baseline

S48～S52 统计：

- Operation Candidate Precision；
- Binding Candidate Precision；
- Compiler Success；
- Manual Edit Rate；
- Preview First-pass；
- Evidence Conflict Rate。

S56 才根据 Golden Set 确定正式阈值。

## 22.2 从第一天执行的硬门槛

| 指标 | 门槛 |
| --- | ---: |
| FlowSpec 静态校验 | 100% |
| Secret / Token / Cookie 泄漏 | 0 |
| Cross-Tenant | 0 |
| 未审核 Apply | 0 |
| Stale Overwrite | 0 |
| Production MCP Preview | 0 |
| Arbitrary Code | 0 |
| Write SQL | 0 |
| Cleanup 静默失败 | 0 |
| Product Defect 自动弱化测试 | 0 |

---

# 23. 主要风险

| 风险 | 处理 |
| --- | --- |
| 基线仍有 P1 | H0 后才分支 |
| FlowProposal 重复建设 | 复用 AIChangeSet / FlowSpecService |
| FlowSpec 设计字段不可执行 | 编译到 Node/Edge；必要时版本升级 |
| Cleanup 失败路径不可执行 | S54 新增 Runtime Phase |
| 先造大 Graph 再验证价值 | Context Snapshot MVP |
| Java Provider 延迟用户价值 | 外部 Evidence 优先，Built-in 后置 |
| 第二套 React Flow | 复用 WorkflowDesigner |
| Scope 过多 | V6.0 只增加 3 个 Scope |
| Skills 反向锁死 MCP | 先一个旗舰 Skill |
| Key Rotation 留到最后 | H1 前移 |
| 固定准确率无统计依据 | 先 Golden Baseline |
| 大 PR 再次失控 | 按 S 拆分、主分支保护 |
| Preview 污染环境 | Cleanup、Approval、Budget、Test Environment |
| LLM 结论错误 | Evidence、Confidence、Unresolved、Human Review |

---

# 24. V6.0 开发启动 Checklist

## 必须全部为 YES

```text
[ ] 项目创建权限 P1 已修复
[ ] URL Import DNS Rebinding P1 已修复
[ ] Organization USER_COUNT P2 已修复
[ ] Standalone 0044 Upgrade P2 已修复
[ ] 四项 Review Threads 已 Resolve
[ ] PR #38 已关闭为 Superseded
[ ] PR #39 已关闭为 Superseded
[ ] 旧分支已清理
[ ] main Branch Protection / Ruleset 已启用
[ ] H0 全量 CI 通过
[ ] V6 Plan v2 已提交
[ ] V6 Baseline SHA 已记录
[ ] V6 Migration Head 已记录
[ ] V6 分支从修复后的 main 创建
```

满足后：

```text
V6_DEVELOPMENT_START = GO
```

未满足时：

```text
V6_DOCS_AND_HOTFIX = GO
V6_FEATURE_BRANCH = NO-GO
```

---

# 25. V6.0 最终 Definition of Done

## 产品

- 外部 LLM 可通过 MCP 创建多接口 Flow Draft。
- Flow Draft 在现有 WorkflowDesigner 中可视化审核。
- 标准用户无需编辑 JSON。
- Binding、Assert、Data 和 Cleanup 可执行。
- Sandbox Preview 可用。
- 旗舰 Skill 可安装。
- Draft 经审核后可 Apply 为 Workflow Draft。
- 不自动 Publish。

## 正确性

- Context Revision 固定。
- Plan Fingerprint 稳定。
- FlowSpec Validate 通过。
- Target Revision Stale 阻断。
- Cleanup 失败不隐藏。
- Main Result 不被 Cleanup 改写。
- Existing V5 Assets 不回归。

## 安全

- Secret Leak = 0。
- Cross-Tenant = 0。
- Auto Publish = 0。
- Production MCP Preview = 0。
- Arbitrary Code = 0。
- Write SQL = 0。
- Approval Replay = 0。
- DNS Rebinding = 0。

## 兼容

- Standalone 升级通过。
- Compact 升级通过。
- Full 升级通过。
- Backup/Restore 通过。
- Transfer 通过。
- V5 FlowSpec 通过。
- V5 Snapshot 通过。
- Existing MCP 通过。

## 发布

- H0 完成。
- H1 完成。
- H2 完成。
- Remote CI 全绿。
- 无 P0/P1。
- RC 观察通过。
- 安全审批通过。
- 人工签署完成。

---

# 26. 最终开发判断

当前项目已经具备启动 V6 的主要功能基础：

- FlowSpec；
- Workflow ChangeSet；
- Review / Apply；
- React Flow；
- MCP；
- Evidence；
- Test Engineering；
- Durable Execution；
- Change Regression；
- Failure Triage；
- 多运行档位。

真正需要做的是把这些能力连接成一条受控编译链，而不是再增加一套平行系统。

推荐执行顺序：

```text
H0 修复当前 main
→ 保护仓库
→ S48 固定契约
→ S49 Context/Evidence
→ S50 Plan/Compiler
→ S51 MCP + Visual Alpha
→ S53 Data/Oracle
→ S54 Cleanup Runtime
→ S55 Preview Beta
→ S56 V6.0 RC
```

最终结论：

> **现在可以立即启动 V6 准备和 H0 修复；在两个 P1、两个 P2及仓库治理完成后，可以正式启动 V6.0 功能开发。原方案方向正确，但必须缩小 V6.0 Core、复用现有 AIChangeSet/FlowSpecService/WorkflowDesigner、前移 Cleanup 和 Key Rotation，并将 Built-in Java Provider、Repair、完整 Change Maintenance 拆入 V6.1/V6.2。**
