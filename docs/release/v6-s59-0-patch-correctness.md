# FlowTest V6.2 S59.0 Patch Correctness

## 1. 阶段状态

S59.0 Patch Correctness 从 S58 Evidence Closure 全绿 Main 基线
`989711c360ffaec19dc155b86fbeeebb0cf1c0f8` 创建独立分支
`codex/v6-s59-0-patch-correctness`。本阶段只收口会影响 S59 自动 Flow Patch 与 Affected Flow 精度的
六项正确性问题，不实现 Context Diff、Knowledge Diff、Maintenance Proposal 或自动 Apply。

## 2. 已实现收口

1. Cleanup Repair 由 Cleanup Signal 的独立分类决定；Main Phase 的 BAD_TEST 不再为 Cleanup Phase 的
   Network/Environment/Auth/Timeout 等故障开放 Cleanup Patch。
2. Binding Repair 可修改既有 Capability Node 的 `bindings`，但仍锁定 Node ID、Kind、Name、Position、
   Capability Identity、Configuration、Dependency、Operation 与 Target；任何越界变化继续 Fail Closed。
3. Contract Drift Repair 将 `version_strategy` 纳入 Operation Identity；普通 Contract Patch 不能夹带
   `pinned` / `current` 策略迁移。
4. `previous_step` 的 Workflow Variable 纳入 Data Recipe 跨来源唯一性检查，不能与 Constant、Synthetic
   或其他运行来源声明同名变量。
5. Body Mapping 在编译前检查完整嵌套路径：既拒绝初始 Body 标量/数组父节点冲突，也拒绝同一目标 Operation
   上父子 Mapping 相互覆盖。
6. State Knowledge 对全限定 Java 引用提取末端 Class Name 后再计算启发式 Token，避免 `com` 等包名前缀
   让无关 Service、Mapper 与 Entity 产生 `may_use_repository` / `may_map_entity`。

## 3. 安全与兼容边界

- 不新增数据库表或 Alembic Migration，不改变 FlowSpec / Integration Plan Schema Version。
- Capability Binding 只允许在既有 Capability Node 上替换强类型 Binding 列表，不允许增删节点或修改配置。
- Cleanup 独立分类只收紧 Repair Kind，不放宽 Product Defect Guard；任一 Product Defect 仍禁止测试 Repair。
- Body Mapping 预检与现有 Runtime `_set_body` 语义对齐，允许为缺失或 `null` 父路径创建对象，拒绝标量、
  数组和父子 Mapping 冲突。
- Java 启发式修复不改变显式 Evidence Edge；无法唯一关联时继续不猜测。

## 4. 已完成验证

- 新增 7 个原缺陷触发场景，旧实现全部红灯；修复后四个相关测试文件 `62 passed`。
- 后端全仓 Ruff Format 与 Ruff Check 通过。
- Mypy `353` 个 Source File 无错误。
- 后端全量 Pytest `1019 passed, 4 skipped`，Coverage `90.94%`。
- 本阶段无前端变更；Compose、Security、Windows 与 Required Gate 由单次 PR CI 集中验证，不在每个修改后
  重复运行本地重门禁。
- PR #80 最终复审 P0=`0`、P1=`0`，精确 Head Required Gate 全绿并普通 Squash Merge。
- 合并后 Backend CI 发现测试将随机 `trace_id` 中偶然出现的短字符串误判为 Secret 泄漏；Hotfix PR #81
  排除且仅排除 `trace_id`，继续扫描完整错误 Envelope。该 PR 的复审 P0=`0`、P1=`0`，精确 Head
  Required Gate 全绿并普通合并。

## 5. Exit Criteria

| 条件                                      | 当前状态 | 证据                             |
| ----------------------------------------- | -------- | -------------------------------- |
| Cleanup 非测试故障不开放 Cleanup Repair   | Pass     | 混合 Main/Cleanup 分类回归       |
| Capability Binding 可修且其他节点字段锁定 | Pass     | Scope Allowlist 回归             |
| Contract Drift 不改变 version_strategy    | Pass     | Operation Identity 回归          |
| previous_step 不与其他变量来源冲突        | Pass     | Plan Validation/Compilation 回归 |
| Body Mapping 完整路径可执行               | Pass     | 初始 Body 与父子 Mapping 回归    |
| 全限定 Java 引用不产生包名误关联          | Pass     | State Knowledge FQN 回归         |
| 本地集中后端门禁                          | Pass     | Ruff/Mypy/Pytest/Coverage        |
| PR 最终复审 P0/P1 为 0                    | Pass     | PR #80、PR #81                  |
| Required Gate 与普通合并                  | Pass     | PR #80、PR #81                  |

S59.0 Patch Correctness 已完成；Unified Proposal Discovery 已从后续 Main 创建独立分支。
