# FlowTest V6.0 S53 Data Recipe 与 Cross-system Oracle

## 1. 阶段状态

S52 实现与 Evidence Closure 已合并，S53 从当时最新 Main 创建独立分支
`codex/v6-s53-data-oracles`。实现 PR [#60](https://github.com/a3384379/FlowTest/pull/60)
已经普通 Squash Merge；最终精确 Head Review 的 P0/P1 为 0，精确 Head 与 Merge 后 Main Push
七项门禁均为 Success。当前仅剩本 Evidence Closure 文档 PR 及其 Main Push 门禁。

## 2. Implemented

- `flowtest-integration-plan-v2` 表达 Synthetic、Approved Dataset、Previous Step、Environment
  Variable、Secret Reference、Setup API、Existing Safe Record 与 Database Observation，每个 S53
  Data Recipe 均带 Source 与 Evidence。
- Synthetic 使用 Start Node 的有界 `uuid` / `unique_string` / `positive_integer` 生成器，
  每次执行生成新值，不固定生产 ID。
- Cross-API Assert 从两个已执行 Node 分别读取 JMESPath 结果；定义与发布校验均强制
  Expected Source 早于 Assert Source，禁止动态来源同时夹带固定 Expected 字面值。
- DB Read 只接受强类型 Credential、Dialect、Table、Column、Predicate 和 Workflow Variable，
  生成参数化只读 `SELECT ... LIMIT 2`；未暴露 Raw SQL 字段，并复用现有 SQL Node 受限
  执行路径。
- Data/Oracle Strength 保存 Deterministic、Requires Review、Source Ref、Confidence 与
  Applies To。低置信度、非确定性或相互冲突的 Oracle 保留 Review 诊断，不可编译为
  Release Gate。
- Setup API 如声明有副作用，必须引用 Cleanup Requirement。Database Observation 仅用作
  Design Evidence；作为运行数据时 Fail Closed。
- Secret 只保存 `secret://` 引用，Oracle 不得读取或输出 Password、Token、Cookie、
  Authorization 等敏感路径。Dataset Artifact 与 DB Credential 由 Application Service 校验
  Project 归属，DB Credential 同时校验 Dialect，不读取密文。

## 3. 复用与兼容性

- 继续使用 Integration Plan、FlowSpec、AIChangeSet / AIChangeItem、WorkflowService、
  WorkflowScheduler、Assert Node、Dataset Node 与 SQL Node；没有新增平行 DSL、表、Review 或执行引擎。
- v1 Schema 和历史 Fingerprint 保持兼容；v2 使用独立 Fingerprint 和 Compiler Version。
- 本阶段无数据库表变更，无 Alembic Migration。长期决策见
  [ADR 0043](../adr/0043-integration-plan-v2-data-oracles.md)。

## 4. 已完成验证

- 测试先行红灯：首次运行 `tests/test_s53_data_oracles.py` 因 S53 合同尚不存在而在收集阶段失败。
- S53 / S50 兼容 / Workflow Control / FlowSpec / Capability SDK / S51 MCP 聚焦回归：
  `64 passed`。
- 已变更 Python 源码的 Ruff Format、Ruff Check 与 Mypy 通过。
- 独立最小真实栈定向复现确认 DB Read 首次失败原因为项目出站策略未允许 `postgres`；修复后
  S53 Playwright 单例 `1 passed`，临时 `flowtest-s53-*` 容器、网络与卷均已清理，既有恢复栈未改动。
- 最终 Compose Full 的 24 条非 S29 Playwright 全部通过，覆盖 Login → Create → Query → DB Read、
  Cross-API Assert 与 DB Assert；Compact、升级回滚、备份恢复及全部容量门禁同时通过。
- 最终精确 Head 与 Merge 后 Main Push 的 Backend、Frontend、Security、Compose Full/Compact、
  Windows、Upgrade/Rollback 与 Required Gate 均为 Success；运行 ID 见第 7 节。

## 5. S53 Exit Criteria

| 条件                                                 | 当前状态 | 证据                                           |
| ---------------------------------------------------- | -------- | ---------------------------------------------- |
| Data Recipe 来源、Evidence、Strength 完整            | Pass     | 强类型合同与 Invalid Input 回归                |
| Cross-API / DB Assert 可编译且可执行                 | Pass     | 双运行输出断言、SQL Read 编译与 Scheduler 回归 |
| Cross-Tenant / Secret Literal / Write SQL 为 0       | Pass     | Project/Dialect 隔离与封闭 DB Contract 回归    |
| 低置信度、冲突与 Design-only 不自动进入 Release Gate | Pass     | Review / Blocker 诊断回归                      |
| Login → Create → Query → DB Read 真实执行与双断言    | Pass     | 定向最小栈 + 最终 Compose Playwright           |
| 精确 Head Review P0/P1 为 0                          | Pass     | PR #60 最终聚焦复审无重大问题                  |
| 精确 Head 完整门禁一次性全绿                         | Pass     | 七项远程门禁全部 Success                       |
| 普通 Squash Merge 与 Main Push Checks                | Pass     | PR #60 + Merge 后 Main 七项 Success            |

## 6. 范围边界

- S54 Cleanup Scheduler / Compensation Runtime 未在 S53 提前实现；S53 只保留可追溯
  Cleanup Requirement，有副作用的 Setup 在缺少该 Requirement 时阻断。
- 不自动 Publish、不执行生产环境、不读取 Credential 明文、不执行写 SQL。

## 7. Remote Evidence

### 实现 PR 精确 Head

| 门禁               | Run ID      | 结果    |
| ------------------ | ----------- | ------- |
| Backend CI         | 33269847945 | Success |
| Frontend CI        | 33269847930 | Success |
| Security CI        | 33269847928 | Success |
| Compose Smoke Test | 33269847942 | Success |
| Standalone Windows | 33269847972 | Success |
| V2 to V3 Upgrade   | 33269847926 | Success |
| Required Gate      | 33269846845 | Success |

- 最终聚焦 Codex Review 未发现重大问题，P0/P1 为 0。
- 三项 P2 按用户指定的阻塞级门槛记录为后续债务：重复 Synthetic Recipe 变量名；
  `constant` / `existing_safe_record` Recipe 作为 DB Read 参数来源；旧版 v1 `setup_api` Recipe
  缺少新来源字段时的兼容解析。对应历史 Review Thread 已记录延期处置并关闭，不再触发
  P2 修复—全量门禁循环。
- PR #60 已普通 Squash Merge；未使用 Admin Merge、Ruleset Bypass、Force Push 或直接推送 Main。

### Merge 后 Main Push

| 门禁               | Run ID      | 结果    |
| ------------------ | ----------- | ------- |
| Backend CI         | 33272970557 | Success |
| Frontend CI        | 33272970485 | Success |
| Security CI        | 33272970510 | Success |
| Compose Smoke Test | 33272970586 | Success |
| Standalone Windows | 33272970490 | Success |
| V2 to V3 Upgrade   | 33272970552 | Success |
| Required Gate      | 33272970479 | Success |

S54 只能在本 Evidence Closure PR 普通合并且其 Main Push Required Gate 成功后，从最新 Main
创建独立分支；Closure 不重复业务代码 Review、本地全量测试或容量门禁。
