# ADR 0049：Context 与 State Knowledge 的版本化差异

状态：已采纳（S59A）

## 背景

S59 在现有 S45 Change Regression 中接入 V6 Context Evidence。开始选择受影响流程前，需要能够比较
固定的历史 Context Revision，明确证据、缺失项、冲突和知识关系发生了什么变化。

## 决策

- 增加纯领域函数，输出 `flowtest-context-diff-v1` 与 `flowtest-state-knowledge-diff-v1`。
- Evidence 使用指纹集合差；Repository、Contract、Data Profile、Existing Test 使用完整引用与版本对。
  同一来源可以同时存在多个版本，不按来源名称覆盖旧记录。
- Provider 差异以持久化 Evidence 的类型、Provider 名称/版本、来源引用/版本为身份，不读取源码或原始行。
- 知识节点按 ID 比较，报告新增、删除、Kind/Label/Facts 变化；多值 Fact 不降为单值字典。关系以
  `(source, target, relation)` 比较。节点、边、Facts、Evidence 的输入顺序不改变结果。
- 节点值和 Conflict Summary 只参与指纹比较，不复制到 Diff；返回节点 ID、Kind、变化 Fact 名和关系身份。
  Conflict 新增/消失按规范化后的完整冲突指纹报告；摘要或证据改变视为旧冲突移除、新冲突加入。
- 复用 Context Inspector 的项目 Read 授权。只读接口为
  `GET /projects/{project_id}/contexts/{context_id}/diff?before_revision=N&after_revision=M`。
  两个版本必须属于路径中的同一项目、同一 Context；缺失返回标准 404，非法版本号返回 422。
- 比较允许同版本及反向比较，并允许查看过期/关闭 Context 的历史事实。不自动选取 current，
  不改变当前 Revision、状态或持久化记录。
- Diff 永远标记 `requires_review=true`、`automatic_patch_allowed=false`。启发式关系的变化不能授予
  Patch 权限，后续 Affected Flow 与 Maintenance Proposal 必须单独完成证据匹配和受控写入校验。

## 边界

本阶段交付后端差异能力与 Golden/API 回归。S59B 负责 Affected Flow；S59C 负责可信 Maintenance
Provenance 并收口 PR #82 来源标签 P2；S59D 将结果接入既有 Change Regression Snapshot。
不新增表或平行维护状态机。差异上限由两份既有有界快照限定，完整保留新增和删除，不静默截断。
