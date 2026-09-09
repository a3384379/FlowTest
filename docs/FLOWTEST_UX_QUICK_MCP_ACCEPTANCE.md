# FlowTest 基础体验与轻量 MCP 验收记录

更新时间：2026-09-10
实际基线：`591641b`
工作区状态：改动未提交、未 push、未 merge；启动时已有的 `deploy/ruoyi/compose.yaml` 修改保留。

两份 `FlowTest_*.md` 是本轮实施资料。本记录只描述当前工作区实际完成和实际验证的内容，不把方案中的目标或静态源码检查写成发布结论。

## 已执行通过

### 后端

- `UV_CACHE_DIR=/private/tmp/flowtest-uv-cache uv run --no-sync ruff format --check .`：通过（554 个文件）。
- `UV_CACHE_DIR=/private/tmp/flowtest-uv-cache uv run --no-sync ruff check .`：通过。
- `UV_CACHE_DIR=/private/tmp/flowtest-uv-cache uv run --no-sync mypy app`：通过（390 个源文件）。
- `UV_CACHE_DIR=/private/tmp/flowtest-uv-cache uv run --no-sync alembic heads`：`20260910_0055 (head)`。
- `UV_CACHE_DIR=/private/tmp/flowtest-uv-cache uv run --no-sync pytest -q`：通过；全部测试通过，5 个跳过，2 个既有 `PytestCollectionWarning`，覆盖率 90.51%（要求 90%）。回归命令在允许绑定临时 `127.0.0.1` Mock 端口的本地权限下执行，未访问真实业务地址。
- Quick、OFF 脱敏、导出、目标解析、归档生命周期及 Runner/Standalone 相关目标测试均包含在上述回归中。

### 前端

- 在 `frontend/` 执行 `pnpm format:check && pnpm lint && pnpm test:coverage && pnpm build`：全部通过。
- Vitest：70 个测试文件、285 个测试通过。
- 覆盖率：Statements 85.84%、Branches 80.01%、Functions 85.19%、Lines 88.20%。
- Vite 生产构建完成，生成 `frontend/dist/` 静态资源。

### 生成物与规范

- `python3 scripts/build_skill_evaluation.py` 已执行，Quick 工具已同步到相关 Skill 评测 fixture。
- `git diff --check` 通过。
- OFF 策略已同步到 `AGENTS.md`、`CONTRIBUTING.md`、后端配置、项目设置界面、MCP/Skill 描述和任务策略快照；显式 ON 的旧特征测试通过 `redaction_on` 标记保留原有 ON 语义。

## 本轮实现覆盖

- 导出文件名使用 ASCII fallback 与 UTF-8 `filename*`，Blob 错误不会保存为伪文件；HAR、cURL、Bruno、Excel 的边界和版本校验保留。
- 环境选择按用户/项目隔离，失效环境不再静默回退；统一目标解析覆盖服务 Endpoint、网关路径和绝对 URL 语义；环境支持编辑与归档式删除。
- 工作流支持权限与引用检查后的归档式删除；服务端分页接口选择器支持名称、路径、说明、方法筛选。
- 工作流草稿按资源身份保存 schema、基础 revision、编辑版本和更新时间，处理刷新、远端冲突、删除清理和存储失败。
- 草稿变更会刷新页签 dirty 标记；登出或换用户时清理旧用户的本地草稿和会话页签。API 工作台的批量 Header 和字段输入按项目脱敏策略工作，OFF 保留原值，ON 才启用旧的占位符规则。
- `POST /api/v1/projects/{project_id}/mcp/flow/simple-proposals` 与 `flowtest.propose_simple_flow` 提供强类型 Quick 提案；结果只落待审查草稿，支持幂等重放和 `proposal_id + expected_revision` 修订，不自动 preview、apply、publish 或执行真实业务。
- 安装级及项目级脱敏策略默认为 OFF；排队的工作流执行、AI Job 和 Runner lease 固定创建时的模式与策略版本。

## Compose 与 Playwright 验证

- `docker compose config --quiet` 通过。默认 Compose 的 `127.0.0.1:8080` 与启动前已存在的用户容器 `flowtest-ruoyi-ruoyi-1` 冲突；未停止该容器，改用临时端口覆盖并创建隔离的 `flowtest-e2e` 项目。
- 隔离项目执行 `docker compose -p flowtest-e2e -f compose.yaml -f /private/tmp/flowtest-e2e-fresh.override.yaml up -d --build --wait`，当前源码对应的服务均健康；验收结束后已删除该项目及临时卷。默认 FlowTest 栈仍保持运行。
- `FLOWTEST_E2E_BASE_URL=http://localhost:3001 pnpm --dir frontend e2e:setup`：通过（1 个测试）。完整 Playwright 运行共 27 个测试，7 个通过、20 个失败；通过项包括 S15、S17、S18、S22、S31 首个发布门禁、S50、S51。
- 未通过项主要受现有验收前置或部署能力矩阵影响：S19 缺少预置 Pilot 项目，S21/S23/S24/S25/S27/S28/S30/S31 后续用例依赖未启用的 AI、GraphQL、事件协议、性能/影响分析或服务目录能力，S29 缺少 Runner lease 证据，S26 的模板名称返回 409，S14/S16 为浏览器交互等待或断言不一致，S57/S58/v1 在长时间串行运行中未完成认证前置。S49/S53 的历史断言仍按 ON 脱敏编写，而 Compose 默认策略已按本轮决定为 OFF；这些结果不能直接作为当前 OFF 契约的回归结论。

## 未验证或受环境限制

- Windows 实机安装包、升级/回滚、适配器字符编码、`tools/list` 和 Quick 端到端未验证；本地没有 Windows 打包运行环境。
- 20 次冷热样本的稳定 p95、超过 100 条接口的真实浏览器下载矩阵、跨窗口冲突、浏览器实机多页签 E2E 和运行中切环境仍未完成验收。关闭单页签、关闭其他和关闭全部的 dirty 确认已有前端单元/组件回归。
- 因上述环境验证缺失，本记录不宣称发布门槛全部通过；需在目标部署环境补跑相应矩阵后再做发布决定。
