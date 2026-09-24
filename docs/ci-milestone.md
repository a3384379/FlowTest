# PR CI 开关

FlowTest 的 PR 通过 GitHub 标签选择一次远程检查。普通提交不会自动启动远程重任务；先完成适用的本地验证，再给稳定的候选提交加标签。

| 标签 | 用途 | PR 合并门禁 |
| --- | --- | --- |
| `ci:light` | 仅 `README.md`、PR 模板和 `docs/` 下的 Markdown 文档 | Quick CI：检查差异空白错误。不会运行功能测试、构建、容器或安全扫描；其他路径的 PR 会被 Required Gate 拒绝。 |
| `ci:milestone` | 功能、依赖、部署或需要完整回归的改动 | 按路径运行 Backend、Frontend、Security、Compose、Windows、Upgrade，并由 Required Gate 汇总。 |

两个标签同时存在时门禁失败；先移除旧标签再添加新标签。CI 工作流自身的修改仍须经受控 Bootstrap 合并，不能用轻量标签绕过。`main` 合并后不再重复运行同一组完整 CI；需要补跑时使用各工作流的 `workflow_dispatch`。

## 使用流程

1. 在同一功能阶段内集中开发、修复和本地验证。
2. 根据改动风险，为 PR 添加 `ci:light` 或 `ci:milestone`。
3. 等待当前 PR Head 的 `Required Gate` 成功，再合并。
4. 如果门禁后又修改了代码，先移除再重新添加所选标签，使最新 Head 获得新的检查结果。改变模式时先移除旧标签，再添加新标签。

所有工作流按 PR 设置并发组。新的门禁启动时，会取消同一 PR 上仍在运行的旧门禁，避免重复占用 Runner。GitHub 对 `labeled` 事件会创建其他工作流的跳过记录，但只有所选模式的检查会实际执行。
