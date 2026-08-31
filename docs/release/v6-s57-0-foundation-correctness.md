# V6.1 S57.0 Foundation Correctness 验收记录

日期：2026-08-31  
阶段：S57.0 — V6.1 Foundation Correctness & Accepted P2 Closure  
结论：`S57_0_COMPLETE=YES`、`START_S57=GO`、`START_S58=NO-GO_UNTIL_S57`

## 1. 范围与判定边界

S57.0 不新增 S57/S58 产品功能，而是在 Built-in Provider、State Knowledge 和 Repair 自动化之前，关闭
会被后续阶段复制或放大的 10 项代码、契约与流程正确性 P2。Context Inspector UI 与 Skill 自包含
Evaluation Assets 仍按既定路线分别在 S57 和最迟 S60 收口。

本文更新当前开发路线，不修改 V6 Core 历史验收事实。`V6_RC_READY=YES` 保持不变；连续 RC、公司实机、
外部恢复演练、安全审批和人工签署尚未完成，因此 `GA_READY=NO`。

## 2. 原 12 项 P2 的最终状态

| 原始 P2                                               | 结果              | 交付                  |
| ----------------------------------------------------- | ----------------- | --------------------- |
| S49：授权早于幂等记录                                 | 已修复            | PR #73                |
| S50：Body Mapping 目标必须是对象型 JSON Body          | 已修复            | PR #71                |
| S50：Scenario Path/Cookie 静态值保留                  | 已修复            | PR #71                |
| S52：私有 DTO Member 的 Jackson 默认可见性            | 已修复            | PR #72                |
| S52：普通 `@Controller` Response Body 语义            | 已修复            | PR #72                |
| S53：重复 Synthetic Variable                          | 已修复            | PR #71                |
| S53：Constant/Existing-safe-record DB Read 来源       | 已修复            | PR #71                |
| S53：Plan v1 `setup_api` 兼容                         | 已修复            | PR #71                |
| S56：Evaluation Gate 使用舍入值                       | 已修复            | PR #73                |
| S56：Preview Skill 缺少 Accepted + Unapplied 前置检查 | 已修复            | PR #73                |
| S49：Context UI                                       | 纳入 S57 退出条件 | S57 Context Inspector |
| S56：Skill Evaluation Assets 不自包含                 | 最迟 S60 收口     | S60 Full Skills / QA  |

因此应使用以下统一口径：

```text
ORIGINAL_P2_TOTAL = 12
ORIGINAL_CORRECTNESS_P2_CLOSED = 10
ORIGINAL_PRODUCTIZATION_P2_DEFERRED = 2
```

“Review Thread 已回复/关闭”与“代码已修复”不再混用；上表的“已修复”均已有代码和回归测试证据。

## 3. PR A — Planner / Compiler / Data Correctness

PR #71 完成：

- Body Binding 只允许写入对象型 JSON Body；
- Scenario Request Template 保留 Path/Cookie；
- Synthetic Variable 重名进入确定性诊断；
- Constant 与 Existing-safe-record 可作为 DB Read 参数来源；
- Plan v1 `setup_api` 兼容历史快照，Plan v2 保持严格约束；
- 覆盖 Plan v1/v2、Fingerprint、FlowSpec v1/v2、Standalone、Historical Snapshot、Compiler
  Diagnostics、Runtime Mapping 与 DB Read。

最终复审 P0=`0`、P1=`0`。新增两项 P2 已单独接受：

- `previous_step` 与其他来源的跨命名空间变量冲突；
- Body Mapping 嵌套路径与同目标多 Mapping 的完整路径预检。

两项均不属于原始 S57.0 十项的未完成部分。

## 4. PR B — Java Evidence Correctness

PR #72 完成：

- 将 Java 结构字段和 DTO Wire 字段分开建模；
- DTO 只暴露 Public Field、公开 Getter/Setter 或显式 `@JsonProperty`；
- `@JsonAutoDetect` 与无法确定的 Lombok 场景 Fail Closed，并要求人工复核；
- JPA Field/Column 不再被 `@JsonIgnore` 等 JSON 过滤误删；
- 普通 `@Controller` 只有在类/方法 `@ResponseBody` 或返回 `HttpEntity`/`ResponseEntity` 时生成
  Response DTO Evidence；
- Interface Route 合并 Controller、Contract 和 Implementation 的 Body 语义。

集中门禁包含后端全量 982 passed / 4 skipped、前端 223 tests、Compose S52 2 passed。最终复审
P0=`0`、P1=`0`。新增两项 P2 已单独接受：Lombok `@FieldDefaults` 和 `Mono<ResponseEntity<T>>` 等异步
Wrapper；它们不阻断 S57 启动。

## 5. PR C — Governance / Evaluation / Skill Flow

PR #73 完成：

- MCP Flow Proposal 按 Scope → Tenant/Project/Context Validation → Sensitive Check → Idempotency Claim →
  Transactional Action 执行；缓存命中前也重新授权；事务 Action 内保留二次校验；
- 无效 Project/Context 在创建任何 Idempotency Record 前返回稳定 404；
- Evaluation 展示值可以舍入，硬门禁使用 `Fraction` 精确比较原始 numerator/denominator；
- Preview 前重新 `inspect_flow_proposal`，必须同时满足 Proposal/Item Accepted、Revision Current、
  `applied=false`，之后才可请求一次性审批并执行；
- Unit、Contract 与真实 PostgreSQL Compose E2E 均覆盖上述顺序。

集中门禁包含后端 985 passed / 4 skipped、覆盖率 90.83%，前端 223 tests 与构建、S49 Compose
2 passed。GitHub Codex Review 未发现重大问题，P0=`0`、P1=`0`；远端 Backend 首次因既有 Workflow
取消测试遇到 SQLite `database is locked`，仅重跑失败 Job 后通过，代码与复审 Commit 未改变。最终
Required Gate 全绿并普通 Squash Merge。

## 6. 门禁与复审策略

- 每个 PR 在实现稳定后只运行一次集中本地门禁；
- GitHub Codex Review 只阻塞 P0/P1；P0=`0`、P1=`0` 后不因新增 P2 进入循环；
- 普通 PR 跳过 Compact 和容量 RC 重门禁；它们只在显式 `run_rc_gates=true` 时执行；
- 不使用 Admin、Bypass、Force Push 或直接推送 Main；
- 不用重复计算 SHA 代替实际开发和验证。

## 7. 后续串行路线

```text
S57.0  Foundation Correctness       COMPLETE
S57    Built-in Provider / State    GO
S58    Diagnosis / Repair           AFTER S57
S59    Change-aware Maintenance     AFTER S58 AND CORRECTNESS DEBT REVIEW
S60    Full Skills / Continuous QA  AFTER S59
```

S57 的实现重点是把现有 Java/Spring 静态 POC 正式化为 Built-in Provider，将可追溯 Evidence 派生到
State Knowledge，并提供 Context Inspector。RuoYi Golden 必须证明：

```text
Route → DTO → Service → Mapper/Entity → Table
```

整个分析过程只读取有界、版本固定的 Java 文本，不编译或执行目标代码。
