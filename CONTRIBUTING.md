# 参与开发

## 分支与提交

- 功能分支：`feat/<short-name>`
- 修复分支：`fix/<short-name>`
- 提交信息采用 Conventional Commits，例如 `feat(api): add project endpoint`
- 一个 Pull Request 聚焦一个可验证目标

## 开发中的定向验证

```bash
make test-backend-targeted TARGETS='["tests/test_imports_api.py"]'
make test-frontend-targeted TARGETS='["src/lib/api.test.ts"]'
```

`TARGETS` 是非空 JSON 路径数组，可传多个真实测试文件；文件名中的空格按一个目标处理。后端定向测试明确使用 `--no-cov`，前端使用普通 Vitest 测试，不运行全量覆盖率。按改动范围补充 Ruff、格式、lint、类型检查或构建。引擎、调度、认证授权、租户隔离、执行快照、共享契约、数据库、依赖与部署变更需要扩大相关集成和部署验证。

完整本地前后端检查仍使用 `make check`。Compose Playwright、跨部署形态、历史升级和发布验收按变更风险及合并/发布门禁执行；不要把每次编辑都当作发布验收。CI 治理调整由独立授权的变更处理，不使用 `ci:light` 规避代码门禁。

普通 PR 在新门禁激活后自动获得按路径和风险选择的检查；追加提交会验证新版本。`ci:light` 不能降低最低档位，`ci:milestone` 请求完整验收，双标签按较重要求。合并依据当前提交的受信 `Required Gate`，手动工作流和周期结果仅供诊断/回归。当前激活状态与操作边界见 [第三阶段 CI 说明](docs/development-efficiency-phase3.md)。

涉及数据库模型的变更必须包含 Alembic 迁移；涉及 API 契约的变更必须更新测试和 OpenAPI 示例。

## 完成定义

- 本地定向验证：记录实际命令、结果和未运行的完整检查；仅说明当前改动范围内的结论。
- 可合并：最新提交的远程必需门禁通过，真实阻断缺陷已处理；不能复用旧提交的成功状态。
- 可发布：适用的完整发布验收完成，包括相关部署形态与端到端验证。
- 遵循当前项目脱敏策略：默认 OFF 不自动扫描或改写已授权内容；开启 ON 时不得写入未脱敏的敏感日志
- 文档与变更保持一致
- 独立的非阻断改进可记录后续跟踪；同一失败只在获得新信息或相关修复后重试。保留完整日志，报告先摘取有关的失败信息。
