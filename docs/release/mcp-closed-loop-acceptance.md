# MCP Closed Loop S61/S62 验收账本

状态：S61A 已由 PR #90 合并并完成合并后主线门禁；S61B 本地实现与定向回归完成，待 PR
复审/Required Gate。S61C～S62B 未开始。不标记整体完成或 GA。

## 基线与交付范围

2026-09-08 从 PR #90 合并后的全绿 main 开始，基线见 [能力审计](../mcp-capability-audit.md)。
当前分支 `codex/v6-s61b-onboarding-initialization`，从 S61A 合并后全绿 main 创建。本轮交付
组织级幂等的 `ensure_project`、受限 test/sandbox 环境和 Service Target 初始化，同时更新连接
action、MCP Client/Server、MCP Golden、Standalone `20260908_0052` 基线及 Onboarding Skill。
工具数 39 → 42；新写入 Scope 仅开放 `mcp:project:bootstrap`，其他 S61C/S62 Scope 不提前开放。
详见 [ADR 0052](../adr/0052-mcp-onboarding-connection-and-scope.md) 和
[ADR 0053](../adr/0053-mcp-bootstrap-initialization.md)、[连接指南](../operations/mcp-connection-setup.md)。

## S61B 验证记录

- 空组织 Dry Run 不创建项目或组织级幂等回执；真实初始化要求固定组织、
  `mcp:project:bootstrap` 和 `Idempotency-Key`。同键同请求返回历史回执并标记 replay，
  同键不同请求返回冲突，不同键按组织内 `external_key` 复用项目。
- 新增 `external_key` 组织唯一约束和 `20260908_0052` Alembic/Standalone 基线；唯一约束处理
  不同键并发创建，失败的原子操作释放未完成回执，跨步骤不自动删除已创建资源。
- 环境只接受 `test`/`sandbox`，同名地址或分类冲突不覆盖；Service Target 校验项目/环境归属、
  Service 类型、Endpoint Variant、TLS 和现有出站网络策略。URL 凭据、查询/片段、明文 Header
  或 Token 均被拒绝，所有新资源写入审计。
- 定向 API 测试 `3 passed`，MCP Golden/连接 action、Skill Manifest/评测副本与 Standalone 基线
  回归通过；这些是隔离确定性证据，不替代真实宿主 MCP 或真实 LLM 验收。集中 PR 门禁尚未执行。

## S61A 验证记录

- 修改前的 4 个特征测试失败，确认旧 HTTP 缺失/非 Bearer 请求回落到进程账号，以及缺少连接端点。
- 新连接与配置测试覆盖机器身份、Scope、未知字段、协议版本、过期/撤销/禁用、组织禁用、用户 JWT
  拒绝、失效 Cookie、HTTP 两调用者与无凭据隔离、stdio、配置无令牌、非法参数不回显、Feature 过滤。
- 首次后端集中回归：1226 passed / 4 skipped / 1 failed，覆盖率 91.17%；唯一失败为
  `test_mcp_red_team_surface_has_no_uncontrolled_mutation_tools` 的旧精确工具清单。已将新增只读
  入口显式加入清单，保留禁止无控写入断言，修复后相关 80 项定向回归通过。
- 后续新增错误分类/令牌格式测试单独定向验证；最终完整集合以 PR Backend CI 为准，不把旧全量
  结果冒充修改后重新运行的全量结果。Ruff Format/Check、mypy、架构依赖检查均执行；最终 CI 待出。
- 前端集中检查：format、lint/TypeScript、build 通过；61 个文件、240 项测试通过，branch 80.34%。
- Onboarding Skill quick_validate、四个 Skill Manifest 契约检查、五包 Evaluation 资产同步检查通过。
- PR 复审 P1 修复：项目资产授权现在以 `service_account_id`、固定组织和 MCP scope 为边界，
  不读取创建者的 `is_system_admin` 或项目成员角色；setup 校验并拒绝敏感 URL path，避免把令牌
  写入 config_template/stdout。相关回归覆盖同组织无成员访问、跨组织 404、越权能力拒绝和
  URL 错误不回显。
- 真实 SDK Streamable HTTP 的 ASGI 传输测试通过，保持默认 Host 安全校验。进程内调用与 HTTP
  身份分别验证；这不是实际宿主或真实模型验收。Compose Playwright 由本次路径门禁 CI 执行，当前待出。

本轮没有执行实机、公司 Windows、容量或 Compact 重门禁；Windows CI 保留。没有操作用户若依
真实目标，未读取或改写用户 MCP 配置，启动时已有 RuoYi Compose 改动不进入本 PR。

## 分阶段状态

| 阶段 | 开发 | 合并/主线门禁 |
| --- | --- | --- |
| S61A 连接、权限契约 | 已完成 | PR #90 已合并，主线门禁全绿 |
| S61B 项目/环境/服务初始化 | 本地完成 | 待复审和 CI |
| S61C 有界契约导入 | 未开始 | 未开始 |
| S61D 读取/查找/Readiness/目标诊断 | 未开始 | 未开始 |
| S61E 零接入与生成 Skill | 未开始 | 未开始 |
| S62A 回归准备与 TestPlan 建议 | 未开始 | 未开始 |
| S62B 取消、结果续接与总验收 | 未开始 | 未开始 |

## 真实模型验收单独记录

当前会话未暴露 FlowTest MCP。未用用户 JWT、通用 REST、内部 SQL、Docker/.env 管理员凭据或
浏览器登录绕开此条件。宿主连接、实际安装 Skill、真实模型从零资产生成与 A/B 执行尚未验证。
这不是认定用户没有凭据，不影响先做隔离开发；需要真实接入时才请求缺失的明确授权或资源。
不得把 Golden、SDK、ASGI 或 Compose Fixture 写成生产 MCP-only 成功。

## 当前已可用的短指令示例

```text
发现当前会话的 FlowTest MCP 工具，不读取本机凭据。
若 inspect_connection 可用，检查当前机器身份、组织、scope 和版本。
列出我已获授权的项目，报告证据缺口和下一步。
缺工具或权限时准确说明原因，不切换浏览器/JWT/SQL 补权限。
不要创建凭据、自动审核、Apply、Publish 或执行测试。
```

该例仍只展示连接与读取；S61B 的零项目初始化必须由具备明确 Scope 的 MCP 工具执行，不能由
用户手工复制 UUID 代替。最终 S61/S62 示例在交付后更新。
