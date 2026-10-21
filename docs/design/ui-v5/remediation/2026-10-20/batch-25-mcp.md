# M23 MCP 变更集整改回执

对应冻结审计：F-MCP-01、F-MCP-02。基线：`edb06bbc5259f0390b85bb45f731e72fd2fc8242`。后端精确只读合同已独立提交：`d3592576640c070b75e7ae9064d6e33028b14287`；前端和本回执另行提交。

## 实现

- 展示 Envelope 的实际 warnings 和可复制 Trace ID；治理区提供风险、置信度、原因代码、人工审核/审批要求、来源指纹及审批 ID、决定、人和时间。未知原因保留服务端代码。警告与服务端硬性审批、权限和修订冲突分别说明，不新增采集、扫描、日志或策略代换。
- 测试设计按意图、验收、场景、预期/断言、覆盖、证据、警告和审核要求提供结构化只读预览；知识图谱/状态模型与完整原文可展开核对。
- 测试用例展示引用工作流、原样保存的固定或未固定版本、环境与运行参数；不虚构独立断言。空版本明确写“未固定，发布时需确认”。
- 测试计划更新按提案涉及目标展示操作、原/拟版本、原/拟指纹、拟用环境、重试、参数、依赖和理由。原环境、重试、运行参数及完整原项列表并未冻结，明确提示来源不足；不会把当前计划读取结果当成历史 before。旧空 target_actions 保留新增建议语义，结构无效与空列表分开反馈。
- 原工作流创建图、控制块图形差异、基线修订号和服务端原子守卫保留。完整提案复用既有只读阅读器，可搜索、格式化、复制和下载完整内容，预览仍有既有限额。
- 所有结果入口统一校验 accepted、物化类型和 ID；移除了旧工作流入口的仅 ID 判断。工作流、用例和计划使用已有真正消费者。TestEngineering 不支持 TestDesign ID，故未发明 `?design=`，也未将 MCP ID 塞进只接受 REST 提案的 `?proposal=`。
- 测试设计结果使用新增 `GET /mcp/write/change-sets/{changeSet}/items/{item}/materialized-design`，在 MCP 页只读抽屉中打开实际保存资产。服务层沿既有精确 ChangeSet 授权，验证变更项所属、accepted、item/resource 类型、物化 ID 与实际资产 project/source_change_set；未知、未物化或错误关联返回标准错误及 Trace ID。读取不经过写入校验/敏感扫描，不增加 Audit。
- 读取/权限刷新失败与被拒审批不能启用物化。审批和逐项审核共享忙碌守卫；用户、组织、项目和 focus 切换隔离缓存及迟到回调。写回执必须匹配当前 ChangeSet/project、requested item 的预期状态和物化类型/ID，审批必须确认 approved；不一致时不写缓存、不报成功，保持禁写，提供只读重新读取恢复。
- 继续保持单次逐项审核请求，计划目标不拆成多个局部接受动作；没有自动批准、Apply、发布、执行或全局 MCP 发现。

## 涉及文件

后端：`app/api/v1/endpoints/mcp_controlled_write.py`、`app/schemas/test_design.py`、`app/services/mcp_controlled_write.py`、新增 `tests/test_mcp_materialized_design.py`。

前端：`MCPChangeSetsPage.tsx`、对应页面测试、`features/mcp/mcp-change-set-service.ts`；新增 `MCPGovernanceSummary.tsx`、`MCPStructuredPreview.tsx`、`MCPMaterializedResult.tsx`。未修改共享进度、冻结文档、数据库、依赖或 CI 治理。

## 针对性验证

先新增具名反例，再实现修复；红灯与后续完整日志保存在本工作树 `output/validation/m23-mcp/`（生成物未提交）。

- `make test-backend-targeted TARGETS='["tests/test_mcp_materialized_design.py", "tests/test_mcp_read.py", "tests/test_s51_mcp_flow_proposals.py", "tests/test_s62_planning_mcp.py"]'`：4 文件、34 项通过。新增结果读取覆盖未物化、实际保存内容而非后续提案、Viewer 允许读取、跨组织/跨项目/变更项所属/类型/状态/source 关联拒绝、标准 Trace ID，以及 OFF 下已有授权值原样返回且读取不增加 Audit。
- 既有 MCP 定向用例继续验证高风险审批 ID、控制块修订冲突、计划指纹冲突和原子事务；未更改这些写路径。
- `make test-frontend-targeted TARGETS='["src/pages/MCPChangeSetsPage.test.tsx", "src/features/api-console/ResponseCodeReader.test.tsx"]'`：2 文件、28 项通过，其中页面 24 项。包含两类图预览、五项最初审计反例、保存设计精确读取、409 不报成功、跨项目迟到回执、读取/权限刷新失败、审批忙碌、pending/错误结果类型，以及缺项/仍 pending/错误物化类型/无 approved 决定的不一致回执。
- 受影响 Ruff 格式/规则、`mypy app`、ESLint、Prettier、TypeScript 及 `pnpm --dir frontend build` 通过。
- 旧测试的简略接受响应已补齐实际后端始终返回的 materialized_resource_type/id；未降低断言、超时、重试或覆盖率门槛。
- 独立只读复审发现并整改的旧工作流链接绕过、回执确认不足及前期审批/过期/迟到守卫问题均有行为反例；最终只读复核未发现新的实质缺陷。

## 条件环境与未验收边界

本工作树未操作共享 QA 数据库、共享浏览器或 Compose，未创建/批准/接受真实 MCP 提案。真实 GUI 与 MCP 客户端验收、完整本地 `make check`、正式最新提交门禁、合并及合并后 CI，由整合负责人分别记录；上述局部验证不代表这些验收通过。

供整合负责人使用的最小 GUI 合成模板：`/tmp/m23-mcp-ui-fixture.template.json`。模板已用真实 `MCPControlledWriteCreate` 做纯 schema 校验，无持久化或执行。需替换项目、已发布工作流及环境 ID，并核对 workflow_version，使用独有名称/幂等键。propose 后产生测试设计与用例两个高风险待审项；可核对警告、低置信度原因、审批硬阻断、结构化内容及真实结果读取。它不发布或执行工作流；是否进行人工审批/接受由整合验收范围控制。

## 整合后的隔离 GUI 验收（2026-10-22）

整合负责人在既有独立 Compose、13078端口和 bundled Chromium 隔离会话运行真实合同。采用上述模板的单独 TestDesign 部分，没有为页面验收额外创建用例、计划或被测系统运行。

- 在隔离合成项目 `fc3f1f13-763a-43c0-88ae-8d9f26925ca7` 创建最小权限临时账号 `9835e67d-9e1e-41c1-a919-5fb3a7b46a86`，仅用于提出本次合成提案；无论提案成功与否均在 finally 撤销，本次已确认撤销。Token只存在运行内存，没有输出到日志或文件。
- ChangeSet `c5ab1c92-0a58-4baf-a641-e5a772d098e7`、item `2e1d1b1e-b433-4e8e-9be9-89d26dee71c6`：真实返回 high、治理置信度72%、3条警告及必须审批。审批前“接受并物化”禁用；场景、预期断言、覆盖内容、设计来源四个结构化区域和完整 Trace 正常呈现。空来源明确显示，不伪造证据。
- 页面显式审批一次，approval `9847d68a-e909-49dd-9f97-c5220114d7c0`；再显式接受一次，实际 TestDesign `67781adb-5eba-4749-8431-bf1b4120232b`。打开只读抽屉，真实 GET 返回同一资产、项目、来源 ChangeSet 和保存目标内容；刷新后仍能打开该资产。
- 提案准备3次业务写入（账号创建、提案、撤销），页面审批与接受2次，共5次；物化1份合成设计，AI入队、发布、执行均为0。其余读取检查业务写入0。没有重复创建提案或反复接受来替换失败结果。
- 390px审核页可用宽度375、整页宽375；物化抽屉可用宽度390、整页宽390，均无整页横向溢出。桌面与移动截图保留。第一段导航脚本误用 `/mcp`，源码真实入口为 `/mcp-changes`，改正后使用同一提案继续，未重复写入。

原始日志位于主验收工作树忽略目录 `output/playwright/audit-20261019/`：`remediation-mcp-seed.log`、`remediation-mcp-review-browser.log`、`remediation-mcp-accept-browser.log`（`passed:true`）、`remediation-mcp-snapshot-r2.log`。真实外部 MCP 客户端连接、用例或计划物化、控制流生产运行和正式发布仍未由本次单设计专项验证；28项目标测试及既有后端原子/冲突合同与本专项分别记账。
