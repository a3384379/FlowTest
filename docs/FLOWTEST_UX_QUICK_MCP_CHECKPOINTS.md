# FlowTest 基础体验与轻量 MCP 实施进度

更新：2026-09-10。实际基线为 `591641b`；当前改动仍在工作区，未提交、未 push、未 merge。用户已有的 `deploy/ruoyi/compose.yaml` 修改完整保留。

两份 `FlowTest_*.md` 是实施方案和阶段提示词，属于输入材料，不代表代码已经完成。本文件记录当前源码、迁移、测试和未验证边界。

## 固定决策

- 安装级默认自动脱敏为 `off`。OFF 不运行敏感识别器，不遮盖、替换或因敏感分类阻断已经有权处理的内容，也不扩大日志或数据采集范围。
- 项目可以通过权限受控的设置显式选择 `off` 或 `on`；项目未设置时继承安装级策略。
- 排队的工作流执行、AI 任务和 Runner lease 固定创建时的策略及版本，后续设置变更不会污染已排队任务。
- 默认生成模式为 `quick`。Quick 只创建待审查草稿，不自动 preview、apply、publish 或执行业务；深度路径继续保留。

## S0：完成

- 已读取方案、阶段提示词、当前仓库规范和实际工作区差异。
- 已在 `docs/` 保留两份原始附件，并区分“实施资料”和“实施结果”。
- 已确认默认 OFF 与原规范的冲突，并按用户授权同步 `AGENTS.md` 和 `CONTRIBUTING.md`。

## S1：导出、环境选择和目标解析完成

- 四种导出支持 ASCII 文件名回退、UTF-8 `filename*`、正确 MIME 和跨域文件名响应头；错误 Blob 会解析标准错误，不生成假成功文件。
- HAR、cURL、Bruno、Excel 保留当前支持的请求语义、重复 Query、Body 类型和 multipart 文件引用边界；超过导出上限或缺版本会明确失败。
- 接口控制台、请求目标和工作流共享按用户/项目隔离的环境选择；失效的显式选择不会静默回退到第一项。
- 环境地址、服务 Endpoint、网关路径和绝对 URL 继续由统一目标解析器处理；显式绑定缺失时阻止请求。
- 复现、修复和边界见 [`FLOWTEST_UX_QUICK_MCP_S1_NOTES.md`](FLOWTEST_UX_QUICK_MCP_S1_NOTES.md)。

## S2：策略、迁移和任务上下文完成

- `backend/app/core/redaction.py` 提供不可变、请求范围的策略；日志、导出、契约、FlowSpec、Evidence、MCP 和 AI 入口均在 OFF 下跳过敏感遍历，ON 分支保留原有处理。
- 项目提供 `GET/PUT /projects/{project_id}/redaction-policy`，界面显示生效模式、来源和策略版本；仅具备 `MANAGE_SECURITY` 的调用者可以修改。
- `20260909_0054_experience_policies.py` 增加项目策略及环境/工作流归档字段；`20260910_0055_task_redaction_policies.py` 增加工作流执行和 AI 任务的策略快照，并有 upgrade/downgrade。
- Standalone SQLite 增量升级会补齐上述字段和索引；执行协调器、Celery/Standalone、AI Runner、远程 Runner 和结果落库都会恢复快照策略。
- OFF/ON、无扫描桩、类型保持和持久策略隔离回归位于 `backend/tests/test_redaction_policy_off.py` 及相关入口测试。

## S3：资源生命周期和接口选择完成

- 环境支持编辑和归档式删除；列表、搜索和新执行入口排除已归档环境，历史快照保留。
- 工作流支持带权限和引用检查的归档式删除；活动执行、测试计划和子流程引用会返回结构化冲突，延迟保存不能复活资源。
- 工作流接口选择器改为服务端分页、名称/路径/说明搜索、方法筛选，并固定 `api_id + version`；不再受前 100 条限制。

## S4：草稿持久化完成最小可用范围

- 工作流草稿移入资源身份隔离的本地 Store，保存 schema、base revision、编辑版本和更新时间；路由卸载、刷新和页面切换可以恢复。
- 保存响应与较晚本地编辑、远端 revision 冲突、删除清理和存储异常均有保护；环境选择不会覆盖草稿。
- 当前范围保留浏览器存储能力；已实现页签激活、关闭单个/其他/全部非固定页签及 dirty 草稿的保存/丢弃/取消确认，并由 Store、Hook 和组件回归覆盖。IndexedDB 迁移、多窗口冲突和无限撤销历史仍属于后续增强。

## S5：Quick 提案完成

- 新增强类型 `POST /mcp/flow/simple-proposals` 和 `flowtest.propose_simple_flow`，输入实际接口 ID/版本、少量步骤、绑定、断言和有界 polling。
- Quick 复用 FlowSpec 导入、权限、版本和提案幂等链，不要求 Test Context、Evidence、外部 DB/Code MCP 或完整内部 FlowSpec；结果是待审核草稿并返回 `needs_input`、诊断、指纹和 review URL。
- 同键同内容可重放，同键异内容冲突；`proposal_id + expected_revision` 保护修订。生成阶段不会发起真实业务请求。
- polling 只映射为最多 4 次的 GET/HEAD/OPTIONS 传输重试；提交类接口或更复杂的业务状态轮询会给出字段级诊断。

## S6：Skill、manifest 和评测完成

- `flowtest-generate-integration-flow` 的默认入口为 quick，deep 为用户明确要求时的可选路径。
- required tools/scopes、示例、references、agents、CHANGELOG、工具描述和所有 golden/eval fixtures 已同步；工具未安装时仍由服务端描述引导 quick 边界。
- 示例保留中文节点、输入断言、缺运行实参、重复 operationId、OFF 敏感样式值和部分成功恢复场景。

## S7：发布前验证状态

代码和本地回归已覆盖主要阶段，但以下项目仍需在相应环境完成，不能用单元测试代替：

- Compose 栈上的完整 Playwright 矩阵、Celery/Runner 独立部署目标一致性、运行中切环境和 20 次冷热性能采样。
- Windows 实机安装包、升级/回滚后的真实服务和 `tools/list`/quick 端到端验证。
- 超过 100 条接口的真实浏览器完整下载矩阵、跨窗口冲突及浏览器实机多页签 E2E。

当前可复核的命令和结果记录在 [`FLOWTEST_UX_QUICK_MCP_ACCEPTANCE.md`](FLOWTEST_UX_QUICK_MCP_ACCEPTANCE.md)。未验证项目保持为未验证，不作发布通过结论。
