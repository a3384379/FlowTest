# S59A Context Diff / Knowledge Diff

## 基线与范围

S59.0 PR #80 与 PR #82 已普通合并；PR #82 合并后七项 main 工作流均已成功。S59A 从该全绿 main
创建独立分支，实现版本化 Context/Knowledge Diff 与授权只读接口。

PR #82 仍有一项接受的 P2：来源标签依赖调用者可控的 `source_ref`，后续 S59C 必须依据持久化可信
Provenance 分类。审查线程关闭表示接受技术债，不表示该缺陷已修复。

## 交付

- 纯领域 Context Diff：证据、Provider/来源版本、契约/数据/测试版本、完整性、冲突。
- 纯领域 Knowledge Diff：节点身份、Kind、标签指纹、变化 Fact 名、关系；包括 State Candidate。
- Context Inspector 同项目、同 Context 的固定历史版本比较接口，支持同版本与反向比较。
- Diff 不包含节点 Fact 值、标签原文、Conflict Summary、源码或数据库原始行。
- Golden、顺序稳定性、多版本、多值 Fact、最大图差异和项目隔离回归。

设计边界见 [ADR 0049](../adr/0049-context-knowledge-diff.md)。本阶段不产生或自动接受、应用、发布 Patch。

## 验收状态

- 本地集中后端验收：Ruff Format / Ruff Check / Mypy 全部通过。
- 全量 Pytest：1032 passed / 4 skipped；覆盖率 90.95%，达到 90% 门槛。
- 远程 CI、Compose Playwright 与 PR 复审尚待完成，以 PR 实际结果为准。

S59B 在本阶段合并后继续；当前不能将整个 S59 标记为完成。
