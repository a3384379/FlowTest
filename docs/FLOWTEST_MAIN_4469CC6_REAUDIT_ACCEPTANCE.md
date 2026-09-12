# FlowTest 主线 4469cc6 复审修复验收记录

日期：2026-09-12

审计基线：`4469cc62fb3f1e2dba497838cecceb6ddbc48994`。输入报告：`FlowTest_Main_4469cc6_Reaudit.md`。

已验证实现提交：`4280dc347bd970bf8e205baca8445a4019b63ac9`（`fix: resolve main reaudit input budgets and draft lifecycle gaps`）。后续仅补充本验收文档，不改变运行代码。

本记录仅覆盖该报告 B01—B05。审计报告作为缺陷证据，不将报告中的建议或历史测试数字视为本次验收结果。

## 修复与可复现证据

| 问题 | 修复后的行为 | 回归证据 |
|---|---|---|
| B01 无默认值输入断言 | 断言引用按已声明的参数名校验；required、nullable、类型和默认值仍由原运行输入契约约束 | `test_s51_mcp_flow_proposals.py` 注册 MCP Tool → 网关 → ASGI 创建提案并重新读取定义；无 default 的必填参数可被断言引用，缺参拒绝、提供参数后 Scheduler 断言通过、未声明引用拒绝 |
| B02 请求预算 | preparation、嵌套运行与 Runner 共享估算和恢复计数；重试与轮询相乘，清理使用独立重试预算 | `test_s55_sandbox_preview.py` 真实 `prepare_preview_execution` → 嵌套 plan → Scheduler，准备得到 12 次主流程预算和独立清理预算，MockTransport 实际收到 4 次轮询及 2 次清理 |
| B02 崩溃恢复 | 每次后续轮询等待 checkpoint 预留成功才外发；累计预留数存于原 checkpoint JSON，终态不会降低已预留值 | `test_workflow_control_nodes.py` 验证发送前回调、第二次轮询取消、RUNNING checkpoint 恢复、总次数不超过 3；`test_runner_fabric.py` 使用独立数据库会话重读，乱序重复预留和较旧终态均不降低计数；历史记录兼容 observation 计数 |
| B03 SPA 草稿 | 登录会话持有按用户、项目、资源隔离的内存草稿；页面卸载后仍可恢复；存储失败时提供可取消的路由切换保护和全局刷新保护 | API 组件测试及 `workflow-session.test.tsx` 使用真实 data router 和模块卸载，覆盖存储异常、取消/继续切换、跨项目返回及丢弃后解除保护 |
| B04 ABA 保存 | API 保存捕获完整资源身份与会话单调 generation，旧保存结果不能删除 A→B→A 后的新编辑 | `APIWorkbench.test.tsx` 使用受控异步响应覆盖 ABA 和项目身份切换 |
| B05 服务器刷新 | 无本地草稿时跟随服务器版本；有本地编辑时保留内容并显示新版本提示 | `APIWorkbench.test.tsx` 分别覆盖 clean/dirty 的同资源版本刷新 |

实现没有增加数据库表或字段；`request_attempts` 为现有结果 JSON 和 Runner DTO 的兼容可选字段，旧数据缺省为 0，恢复时同时参考 attempts 和 observations。没有扩大日志或诊断采集范围。

## 最终工作树门禁

- 后端 `uv run ruff format --check .`：556 个文件通过；`uv run ruff check .` 通过；`uv run mypy app`：391 个源文件通过。
- 后端全量 `uv run pytest`：单次运行 **1336 passed、5 skipped**，覆盖率 **90.62%**，达到 90% 门槛。执行环境允许本地回环端口。首次全量中的新增测试字段名错误已修复，本数字来自修复后的完整重跑。
- 前端 `pnpm format:check`、`pnpm lint`、`pnpm build` 全部通过。
- 前端 `pnpm test:coverage`：71 个文件、**309 个测试通过**；Statements **86.20%**、Branches **80.45%**、Functions **85.63%**、Lines **88.45%**。
- backend、frontend、worker 由最终源码重新构建并启动，均通过 Compose 健康检查。mock-target 使用本地覆盖文件映射至 18080，其他项目的 Compose 配置未纳入本次变更。

## Compose 浏览器故障注入

Playwright CLI 使用最终镜像和本地专用验收账号，在现有 E2E 项目上完成以下实际 UI 操作：

1. 仅对 API/工作流草稿键注入 `Storage.setItem` 配额异常，不修改认证存储。
2. 编辑 API 路径，点击流程编排侧栏，取消导航；路径和编辑页保持不变。
3. 再次导航并确认保留草稿，接口模块实际卸载，流程模块正常加载。
4. 编辑工作流节点名称，返回接口模块；API 路径仍为本次编辑值。
5. 在其他模块派发可取消 `beforeunload` 事件，确认全局保护仍生效；返回流程模块，节点名称恢复为本次编辑值。

本地截图：`output/playwright/main-4469cc6-draft-session.png`。跨项目隔离、ABA 晚响应与 clean/dirty 版本刷新由确定性组件测试覆盖，不扩大为真实浏览器已验证范围。未保存或发布测试编辑，也未触发业务请求。

最终验收使用独立重新打开的浏览器。更早会话在本地镜像替换时引用旧资源文件而失败，该会话不计通过；登录前的一次未认证 refresh 401 不计为受保护页面运行错误。

最终受保护页面会话的控制台检查为 0 errors、0 warnings。

## 验证边界

MCP 用例的断言执行使用确定性 ControlExecutor，真实预览组合用例使用 HTTP MockTransport。数据库持久化回归与取消恢复回归分别验证持久层和执行层，未模拟操作系统直接杀死生产 Runner。

未访问用户真实业务系统或内网数据库，未进行 Windows 安装包升级/回滚、跨浏览器实机矩阵或模型性能采样。上述安装包与业务环境验收不在本次通过范围内。
