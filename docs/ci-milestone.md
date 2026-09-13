# 阶段节点 CI

FlowTest 的 PR 使用 `ci:milestone` 标签启动完整远程 CI。开发过程中的普通提交不会自动启动远程重任务，开发者应先完成本地定向检查，在一个功能阶段稳定后再运行完整门禁。

## 使用流程

1. 在同一功能阶段内集中开发、修复和本地验证。
2. 阶段候选稳定后，为 PR 添加 `ci:milestone` 标签。
3. Backend、Frontend、Security、Compose、Windows、Upgrade 和 Required Gate 根据变更路径运行。
4. 如果门禁后又修改了代码，先移除再重新添加 `ci:milestone`，使最新 PR Head 获得新的完整门禁结果。
5. 合并到 `main` 后仍自动运行完整 CI。

所有工作流按 PR 或分支设置并发组。新的阶段门禁启动时，会取消同一 PR 上仍在运行的旧门禁，避免重复占用 Runner。`workflow_dispatch` 保留为人工补跑入口。
