# FlowTest 基础体验与轻量 MCP 验收记录

更新时间：2026-09-12

本文件保留 PR #98 修复时的历史验收记录。主线 `4469cc6` 复审新增的 B01—B05 及其对 A02/A04/A05 的补充验证，以 [主线复审修复验收记录](FLOWTEST_MAIN_4469CC6_REAUDIT_ACCEPTANCE.md) 为准。

审计基线：`9813c6601d78bc87323c0750e58cc8ea376da8be`（PR #98 复审固定 SHA）

已验证实现提交：`95471f7`（`fix: close PR 98 audit gaps`）

本记录归一描述 PR #97 的 F01—F08 与 PR #98 的 A01—A09 修复结果。方案文档和审计报告仅作为实施输入，不作为测试结论。验收没有访问真实开票、红冲或用户业务数据库。

## PR #98 审计问题收口

| 问题 | 修复后的契约 | 回归证据 | 结果 |
|---|---|---|---|
| A01 MCP 缺省语义 | MCP DTO 通过网关时递归保留 unset；省略字段与显式 `null`、`0`、`false`、空串、数组和对象保持不同语义 | 注册后的 MCP tool → gateway → ASGI 集成测试覆盖全部值形态 | 通过 |
| A02 轮询请求预算 | 节点首次请求由调度器领取预算；后续每次业务轮询单独领取；传输重试、轮询次数和 Preview 最坏预留使用同一乘法口径 | 预算不足时 Mock 只收到允许次数；Preview 预留、失败终态和恢复计数回归 | 通过 |
| A03 工作流跨资源保存 | 保存完成事件携带目标 workflow 与 generation；只有当前资源身份仍匹配时才更新当前编辑器 | 保存 A、切换并编辑 B、释放 A 响应的组件状态回归 | 通过 |
| A04 草稿生命周期 | save、rebase、discard、delete 同时更新内存与 localStorage；generation 阻止晚到回调复活草稿；存储失败时保留 dirty 并阻止无提示卸载 | 丢弃后重开、删除后晚响应、关闭多个页签、身份切换及存储清理失败回归 | 通过 |
| A05 API/项目配置竞态 | 保存捕获 resource identity 与 editVersion；保存中的后续编辑继续作为下一份草稿；同一 API 的服务端刷新不覆盖新编辑；程序化批量修改显式持久化 | API 延迟保存、同资源刷新、切换 API、项目配置延迟保存、批量修改和 `beforeunload` 组件回归 | 通过 |
| A06 导入 OFF | OFF 在敏感名称扫描和 JSON 遍历前返回原值；ON 继续替换普通敏感值并保留已有 Secret 引用；解析边界冻结请求级 policy | OFF 原文、ON 对照、已有 `{{secret.X}}`/`secret://` 保留及导入服务测试 | 通过 |
| A07 Preview 输入 | Preview execution 与 target fingerprint 均在准备 Snapshot 和业务 HTTP 前验证 required、nullable 与类型 | 缺失或错误类型返回 422，`prepare_preview` 未被调用 | 通过 |
| A08 调度超时 | 普通 API 节点外层时限覆盖单请求时限与 polling 总预算的较大值；工作流总时限仍由运行级限制约束；cleanup 保留显式上限 | 短请求时限、长 polling 预算的完整 Scheduler 回归 | 通过 |
| A09 幂等耗时 | 最终 timings 使用新 JSON 对象触发 ORM 更新；观测补写失败只回滚补写，不破坏已提交业务回执 | 关闭原 session 后重读持久化 timings；补写失败保持业务成功 | 通过 |

## PR #97 原问题状态

| 问题 | 当前状态 |
|---|---|
| F01 数组路径 | 支持对象字段与非负数组下标的受限组合，继续拒绝负下标和可执行表达式 |
| F02 polling | 业务状态轮询与传输重试分离，只读方法限制、失败终态、次数和总预算均进入执行契约 |
| F03 必填运行参数 | 类型、required、nullable、说明和缺省状态可持久化，并覆盖运行、调试和 Preview 准备入口 |
| F04 异步保存冲突 | workflow ID、resource identity、editVersion 和 generation 共同约束晚到响应 |
| F05 Skill 契约 | `default_mode=quick`，Quick/Deep 阶段分离，OFF 不扫描或阻止已授权值 |
| F06 全局工作区 | 模块页签、API、项目配置和多工作流草稿都有资源级恢复与失败保护 |
| F07 耗时归因 | resolve、build、validate_and_stage、transaction 与 total 不重复计段，最终值可持久化 |
| F08 证据归一 | 本文件绑定审计 SHA、实现提交、测试层和实际结果 |

## 后端门禁

在 `backend/` 执行：

- `uv run ruff format --check .`：通过，555 个文件格式正确。
- `uv run ruff check .`：通过。
- `uv run mypy app`：通过，390 个源文件无错误。
- 全量 `uv run pytest`：1326 passed、5 skipped；另有 5 项只因受限沙箱禁止绑定 loopback 端口而失败。
- 将这 5 项原命令在允许本机临时端口的环境中逐项重跑：5 passed。
- 全量运行覆盖率：90.12%，达到 90% 门槛。

因此所有后端用例断言均通过，但上述数字来自“全量受限运行＋5 项端口隔离重跑”，不是一次完全提权的单一 pytest 运行。数据库结构没有变化，本轮不新增 Alembic migration。

## 前端门禁

在 `frontend/` 执行：

- `pnpm format:check`：通过。
- `pnpm lint`：ESLint 与 `tsc -b` 通过。
- `pnpm test:coverage`：70 个测试文件、305 个测试通过。
- 覆盖率：Statements 85.75%、Branches 80.04%、Functions 85.38%、Lines 88.03%。
- `pnpm build`：通过。

回归覆盖工作流跨资源保存、丢弃与删除、localStorage 失败、用户/项目身份切换、API 同资源刷新和跨 API 保存竞态、项目配置保存竞态，以及程序化表单更新。

## Compose 与 Playwright

- 当前源码重新构建 backend、frontend、worker 和 mock-target。因本机 8080 端口已被其他测试容器占用，使用 `/private/tmp/flowtest-compose-e2e.override.yaml` 将 mock-target 映射到 18080。
- backend、frontend、worker、postgres、redis、minio 和 mock-target 最终均为 healthy。
- 使用本地专用 `audit-e2e@flowtest.dev` 系统管理员完成认证，不改普通管理员凭据。
- Playwright CLI 在同一修复工作树构建的镜像中实际加载流程编排、API 工作台和项目配置页面，确认工作流保存入口、API 编辑与保存入口、项目策略与配置入口可用；新建干净浏览器会话复验时，错误和警告控制台均为 0。
- 随后补充“同一 API 的服务端刷新不覆盖新编辑”守卫并再次重建最终镜像。该次会话复用的 refresh token 已被前一干净会话轮换，受保护页面返回登录页并记录一次预期的 401，因此不把这次认证失败计为页面通过；补充守卫由组件回归、全量覆盖率、类型检查、生产构建和 Compose 镜像构建验证。

异步竞态和存储异常通过可控 Promise 与 Storage 故障注入的组件测试验证；浏览器验收用于确认这些实现所在的真实受保护页面能在 Compose 栈中加载，不将页面烟雾检查描述成并发故障注入。

## 已验证边界

- Quick 提案只创建待审核草稿，`execution_status=not_run`；不会自动 preview、apply、publish 或调用真实业务。
- polling 不允许对提交类 POST 进行业务状态重复调用。提交和状态查询需要建模为不同步骤。
- OFF 不扫描、遮罩、替换或阻止已授权采集中的值，也不扩大日志或数据采集范围。
- 输入校验在 Snapshot 准备及业务 HTTP 前执行；缺参或类型不匹配返回可定位的 422 错误。
- `timings_ms.total` 从 `IdempotencyService.run` 进入到观测补写采样，表示服务/幂等操作耗时，不包含外层授权、完整 HTTP 网络传输或响应序列化。观测补写为 best effort；若补写失败，重放返回最后一次持久化成功的业务回执。

## 尚未实测

- 未对真实开票/红冲系统、用户内网 Endpoint 或业务数据库执行请求。
- 未运行 Windows 安装包、升级/回滚和跨浏览器实机矩阵。
- 未完成 20 次冷热模型样本的端到端 p95、LLM 分析时间和工具往返统计。
- 本轮真实浏览器检查覆盖受保护页面加载与运行时控制台；并发响应顺序、存储故障和网络预算由确定性后端或组件测试覆盖。
