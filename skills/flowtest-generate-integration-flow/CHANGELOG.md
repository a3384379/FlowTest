# Changelog

## 1.0.0-rc.2 — 2026-09-05

- 交付包内 Golden 标注、Baseline、Fixtures、评分模型、来源清单及独立 evaluator。
- 声明 Python / Pydantic 运行依赖；不再依赖仓库路径运行评测，保留 rc.1 Manifest 解析兼容。
- 明确标注聚合不等于重跑后端测试或部署验收；空证据、失败硬门禁和 Baseline 漂移返回非零。

## 1.0.0-rc.1 — 2026-08-30

- Added the complete Context → Evidence → Plan → Compile → Dry Run → Proposal → Visual Review workflow.
- Added optional Sandbox Preview with explicit test-environment and one-time-approval boundaries.
- Added version, tool, scope, approval, stop-condition, security, example, and Golden Evaluation contracts.
